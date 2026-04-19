# 并发处理架构指南

## 概述

本文档介绍视频转录API的并发处理架构，包括多视频并发处理和LLM处理队列的设计与实现。

---

## 1. 双队列架构

### 1.1 主任务队列 (`task_queue`)

**类型**：`asyncio.Queue`

**功能**：处理视频转录的主要流程（下载、转录）

**并发性**：支持多个视频同时处理

**处理器**：`process_task_queue()` - 异步协程

### 1.2 LLM处理队列 (`llm_task_queue`)

**类型**：`queue.Queue`（线程安全）

**功能**：处理大模型API调用和微信消息发送

**排队机制**：确保同一视频的内容连续发送

**处理器**：`process_llm_queue()` - 单独线程运行

### 1.3 LLM专用线程池

**新增**：`llm_executor` - LLM专用线程池

**配置**：`concurrent.llm_max_workers`（默认10）

**功能**：
- `process_llm_queue` 出队后提交到线程池
- 不同任务可并行执行
- 单任务由 `task_lock` 保证顺序

---

## 2. 并发流程

```
用户请求1 → 主任务队列 → 线程池（并发处理）→ LLM队列 → 顺序处理（校对、总结、发送）
用户请求2 → 主任务队列 → 线程池（并发处理）→ LLM队列 → 顺序处理（校对、总结、发送）
用户请求3 → 主任务队列 → 线程池（并发处理）→ LLM队列 → 顺序处理（校对、总结、发送）
    ↓              ↓              ↓                    ↓                ↓
   立即返回      立即提交      多个视频真正并发      按完成顺序排队     保证连续性
```

**关键改进**：
- 任务提交到线程池后立即返回，不等待完成
- 多个视频可以真正同时进行下载、转录
- 使用回调函数处理任务完成事件
- LLM处理仍然保持排队机制

---

## 3. 转录文本处理流水线

| 场景 | 判定条件 | 处理模块 | 并发策略 |
| --- | --- | --- | --- |
| 平台字幕 / CapsWriter 短文本 | `use_speaker_recognition=False` 且 `len(transcript) < min_summary_threshold` | `_process_original_logic` | 仅校对线程；总结跳过 |
| 平台字幕 / CapsWriter 中长文本 | `use_speaker_recognition=False`，长度超过阈值 | `_process_original_logic` 两线程 + `_process_txt_segmented`（分段） | 校对线程 & 总结线程并行；分段校对内部最多 10 个线程 |
| FunASR（未触发结构化） | `use_speaker_recognition=True` 但缺少 `platform/media_id` 或结构化失败 | `_process_json_segmented` | 先提取 speaker mapping，再同时启动分段校对 + 总结；段内并发同上 |
| FunASR + 结构化 | `use_speaker_recognition=True` 且具备 `platform/media_id/transcription_data` | `_process_with_structured_output` / `process_llm_task_with_structure` | 说话人推断 → 结构化校对（chunk 并发）→ 结构化总结（串行） |
| LLM 队列调度 | 所有 LLM 任务 | `_handle_llm_task` 由 `llm_executor` 承载 | 全局最多 `llm_max_workers` 个任务并行，单任务受 `task_lock` 限制 |

---

## 4. 具体实现

### 4.1 导入优化

```python
import threading
import queue
import asyncio
from concurrent.futures import ThreadPoolExecutor
```

### 4.2 全局变量

```python
# LLM处理队列，使用线程安全的队列
llm_task_queue = queue.Queue(maxsize=100)

# LLM处理锁，确保同一时间只有一个视频在进行LLM处理
llm_processing_lock = threading.Lock()

# LLM专用线程池
llm_executor = ThreadPoolExecutor(max_workers=10)
```

### 4.3 任务队列处理器（修复并发问题）

```python
async def process_task_queue():
    """处理任务队列，实现真正的并发"""
    while True:
        task = await task_queue.get()
        # 提交任务到线程池，但不等待结果
        future = executor.submit(process_transcription, task_id, url)

        # 添加回调函数来处理任务完成
        def task_completed(future_result):
            result = future_result.result()
            task_results[task_id] = result

        future.add_done_callback(task_completed)
        # 立即处理下一个任务，不等待当前任务完成
```

### 4.4 LLM队列处理器

```python
def process_llm_queue():
    """在单独线程中运行，确保同一视频的校对和总结文本按顺序发送"""
    while True:
        llm_task = llm_task_queue.get()  # 阻塞等待
        with llm_processing_lock:        # 确保串行处理
            # 处理校对和总结，按顺序发送微信消息
```

### 4.5 LLM任务处理器（新增）

```python
def _handle_llm_task(task_id: str, task_data: dict):
    """
    将 LLM 任务提交到线程池执行

    Args:
        task_id: 任务ID
        task_data: 任务数据
    """
    logger.info(f"LLM任务出队: {task_id}，提交到线程池")

    def task_done_callback(future):
        """任务完成回调"""
        try:
            future.result()
            logger.info(f"LLM任务处理完成: {task_id}")
        except Exception as e:
            logger.error(f"LLM任务处理失败: {task_id}, 错误: {e}")
        finally:
            llm_task_queue.task_done()

    # 提交到线程池
    future = llm_executor.submit(_process_llm_task_internal, task_id, task_data)
    future.add_done_callback(task_done_callback)
```

### 4.6 服务启动优化

```python
@app.on_event("startup")
async def startup_event():
    # 启动主任务队列处理器（异步）
    asyncio.create_task(process_task_queue())

    # 启动LLM队列处理器（单独线程）
    llm_thread = threading.Thread(target=process_llm_queue, daemon=True)
    llm_thread.start()
```

---

## 5. 关键修复

### 5.1 并发问题修复

**问题**：原始实现中虽然有线程池，但使用了 `await future.result()` 等待每个任务完成，导致任务实际上是串行执行的。

**解决方案**：
1. 移除 `await future.result()` 的等待逻辑
2. 使用 `future.add_done_callback()` 添加回调函数
3. 任务提交到线程池后立即处理下一个任务
4. 通过回调函数异步更新任务结果

**效果**：现在多个视频可以真正同时进行下载、转录等操作。

---

## 6. 优势分析

### 6.1 提升并发性能
- **真正的并发处理**：多个视频可以同时下载和转录，不再串行等待
- **资源利用率提升**：CPU和网络资源得到更好利用
- **响应时间优化**：用户请求可以立即返回任务ID
- **吞吐量提升**：系统可以同时处理更多视频任务

### 6.2 保证消息有序性
- **微信消息连续性**：同一视频的校对文本和总结文本不会被其他视频打断
- **用户体验提升**：阅读体验更加连贯
- **内容关联性**：校对文本和总结文本始终对应同一个视频

### 6.3 系统稳定性
- **错误隔离**：单个视频的LLM处理异常不会影响其他视频
- **资源保护**：LLM API调用的并发数得到控制
- **内存管理**：队列大小限制防止内存过度使用

---

## 7. 配置参数

### 7.1 并发配置

```json
{
  "concurrent": {
    "max_workers": 3,        // 主任务队列最大并发数
    "queue_size": 10,        // 主任务队列大小
    "llm_max_workers": 10    // LLM专用线程池最大并发数
  }
}
```

### 7.2 LLM队列配置
- **队列大小**：100（硬编码，可根据需要调整）
- **处理模式**：串行处理，确保顺序性
- **线程模式**：daemon线程，随主程序退出

---

## 8. 监控和日志

### 8.1 日志定位提示

系统增加了详细的日志记录：
- LLM任务加入队列的时机和信息
- LLM任务开始和完成的时间
- 队列状态和异常情况

**关键日志**：
- `LLM任务出队...提交到线程池`
- `开始处理LLM任务`
- `LLM任务处理完成`
- `TXT/JSON长文本校对/总结任务开始/完成`
- `校对任务开始/完成`

通过筛选 `task_id` 即可还原单个任务的执行顺序与并发情况。

---

## 9. 使用示例

### 9.1 手动测试

```bash
# 快速提交多个任务（几乎同时）
curl -X POST "http://localhost:8000/api/transcribe" \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{"url": "video1_url"}' &

curl -X POST "http://localhost:8000/api/transcribe" \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{"url": "video2_url"}' &

curl -X POST "http://localhost:8000/api/transcribe" \
  -H "Authorization: Bearer your-token" \
  -H "Content-Type: application/json" \
  -d '{"url": "video3_url"}' &
```

### 9.2 自动化测试

```bash
# 运行单元测试
python tests/unit/test_llm_concurrency.py
```

测试验证：
- 两个任务可同时进入 LLM 处理
- 缓存和通知正常工作
- `task_done()` 正确调用

### 9.3 系统行为
- **并发处理**：多个视频同时开始下载和转录
- **任务提交**：所有任务几乎瞬间提交完成
- **处理进度**：可以看到多个任务同时在不同阶段进行
- **LLM排队**：校对和总结按完成顺序排队发送
- **消息连续性**：每个视频的校对和总结文本连续发送

---

## 10. 注意事项

1. **线程安全**：LLM队列使用线程安全的`queue.Queue`
2. **资源控制**：通过锁机制控制LLM API的并发调用
3. **异常处理**：每个组件都有完善的异常处理机制
4. **服务重启**：daemon线程确保服务可以正常重启
5. **速率限制**：LLM API 并发大幅提升后，需注意模型速率限制与 WeCom 通知限流

---

## 11. 后续关注点

- 若要让结构化总结也与校对并行，需重构 `process_llm_task_with_structure` 使其在说话人推断后即可提供"总结输入"
- LLM API 并发大幅提升后，需注意模型速率限制与 WeCom 通知限流，必要时在外层加 throttling
- 动态调整：根据系统负载动态调整并发数
- 优先级队列：为不同类型的任务设置优先级
- 负载均衡：支持多实例部署和负载均衡
- 性能监控：添加详细的性能指标监控

---

## 更新日志

### 2025-11-17
- 新增 LLM 专用线程池 `llm_executor`
- 重构 `_handle_llm_task` 函数，支持任务并发处理
- 完善日志系统，便于定位并发问题
- 添加单元测试验证并发正确性
- 完善转录文本处理流水线文档

### 早期版本
- 实现双队列架构
- 修复原始实现的串行问题
- 添加回调机制处理任务完成
