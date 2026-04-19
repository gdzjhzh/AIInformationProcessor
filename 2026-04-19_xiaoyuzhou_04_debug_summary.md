# 小宇宙链接跑通 `04 -> 00 -> 02 -> 03` 排障总结

日期：2026-04-19

目标：
- 启动 `CapsWriter` 和 `FunASR`
- 用真实小宇宙链接 `https://www.xiaoyuzhoufm.com/episode/69b4d2f9f8b8079bfa3ae7f2`
- 在 live 主实例里把 `04 -> 00 -> 02 -> 03` 跑通

## 最终结果

已经跑通。

验证证据：
- live webhook 返回 `HTTP 200`
- 返回体包含 `item_id`、标题、`dedupe_action`
- n8n 主库里有两组完整成功执行：
  - `121 -> 125`
  - `126 -> 130`
- 对应工作流分别是：
  - `90 Local Verify Transcript Mainline`
  - `04 Video Transcript Ingest`
  - `00 Common Normalize Text Object`
  - `02 Enrich With LLM`
  - `03 Qdrant Gate`

## 这次真正遇到的问题

### 1. 小宇宙链接能进 `04`，但一开始出不了 transcript

现象：
- `VideoTranscriptAPI` 能识别小宇宙链接并下载音频
- 但 `04` 无法拿到正文 transcript

根因：
- ASR 后端没有起来
- 具体是 `CapsWriter` / `FunASR` 不可用时，`04` 会在转写阶段失败
- 早期报错是：`无法连接到 FunASR 服务器`

处理：
- 启动 `CapsWriter`，宿主机监听 `6016`
- 启动 `FunASR`，宿主机 / 容器可达 `8767`
- 验证 `video-transcript-api` 容器能连到 `host.docker.internal:6016` 和 `host.docker.internal:8767`

结论：
- 小宇宙平台本身没问题
- 之前卡住是转写后端没起来，不是 `04` 不支持小宇宙

### 2. `90` 验证入口只返回泛化 `500`

现象：
- live webhook 只返回 `{"message":"Error in workflow"}`
- 看不到 `04` 子流程的真实失败原因

根因：
- `90` 里调用 `04` 的 `executeWorkflow` 节点默认把子错误包成父流程错误
- webhook 侧只能看到泛化失败

处理：
- 给 `90_local_verify_transcript_mainline.json` 里的 `04 Video Transcript Ingest` 节点加了 `onError: continueRegularOutput`
- 调整返回节点，把子流程错误转成结构化 JSON 返回

结论：
- 后续排障不再只剩一句 `500`
- 能直接看到 `04` 实际失败在哪个子阶段

### 3. n8n 自己的 JS task runner 默认超时太短

现象：
- transcript 服务已经成功返回
- 但 n8n 侧仍然报：
  - `Task request timed out`
  - `Task request timed out after 60 seconds`

根因：
- n8n 默认配置里：
  - `N8N_RUNNERS_TASK_REQUEST_TIMEOUT = 60`
  - `N8N_RUNNERS_TASK_TIMEOUT = 300`
- 对播客链路来说，这个窗口偏紧

处理：
- 在 `deploy/compose.yaml` 和 `deploy/.env` 增加：
  - `N8N_RUNNERS_TASK_REQUEST_TIMEOUT=600`
  - `N8N_RUNNERS_TASK_TIMEOUT=1800`
- 重新拉起 n8n

结论：
- 这个问题属于 n8n 运行时配置问题，不是业务 workflow 本身的问题

### 4. 真正卡住主链的最后一个问题在 `03 Qdrant Gate`

现象：
- `00` 和 `02` 成功
- `03` 失败
- 数据库里对应执行是：
  - `117`：`04` 失败，停在 `03 Qdrant Gate`
  - `120`：`03` 自身失败

直接错误：
- `Embedding response did not include data[0].embedding`

继续追到原始响应后发现：
- `Call Embedding API` 实际拿到的是：
  - `{"error":{"message":"No successful provider responses.","code":404}}`

根因：
- 当前 embedding provider 配置是 `OpenRouter`
- 这条小宇宙 transcript 很长
- `03_qdrant_gate.json` 原来把 embedding 输入截到 `12000` 字符
- 实测这条 provider 在当前模型/通道下：
  - `12000` 字符失败
  - `10000` 字符失败
  - `9500` 字符失败
  - `9000` 字符成功
  - `8000` 字符稳定成功

处理：
- 把 `03_qdrant_gate.json` 里的 embedding 输入上限从 `12000` 收到 `8000`
- 同步 workflow 到 live SQLite
- 重启 n8n 后重跑

结论：
- 问题不在解析代码
- 问题在当前 provider 对超长 embedding 输入的不稳定响应

## 过程中做过的关键修改

### 运行时与排障辅助

- `deploy/n8n/workflows/90_local_verify_transcript_mainline.json`
  - 让 `90` 能把 `04` 的子错误透出来

- `deploy/n8n/scripts/verify_transcript_mainline.py`
  - 支持传真实 URL、`media_type`、`use_speaker_recognition`
  - 支持调整 transcript polling 参数

### n8n 运行时配置

- `deploy/compose.yaml`
  - 增加 n8n runner timeout 环境变量

- `deploy/.env`
  - 增加：
    - `N8N_RUNNERS_TASK_REQUEST_TIMEOUT=600`
    - `N8N_RUNNERS_TASK_TIMEOUT=1800`

### 主链逻辑

- `deploy/n8n/workflows/03_qdrant_gate.json`
  - embedding 输入截断从 `12000` 调整到 `8000`

- `deploy/n8n/workflows/04_video_transcript_ingest.json`
  - 保留了前面为主链调试加的中间整理节点，用于减小传给 `03` 的 payload 噪声

### 外部服务

- `backups/vendor/funasr_spk_server`
  - 做了本地可运行修正后启动

- `backups/vendor/capswriter`
  - 下载 release 和模型后启动服务端

## 现在的稳定状态

### 服务状态

- `CapsWriter`
  - 监听 `6016`

- `FunASR`
  - 监听 `8767`
  - 容器健康

### 主链状态

真实小宇宙链接已经能在主实例里跑通：
- `90 -> 04 -> 00 -> 02 -> 03`

已验证成功执行：
- `121 -> 125`
- `126 -> 130`

其中第二次复验的结果是：
- `dedupe_action = silent`
- `matched_score = 0.9577811`

这说明：
- transcript 已经成功生成
- enrich 已完成
- embedding + Qdrant gate 已完成
- 第二次复验因为内容已入库，走了去重静默路径

## 这次排障的结论

这次不是单点故障，而是一条串行故障链：

1. ASR 服务没起来，导致 `04` 无法生成 transcript
2. `90` 只返回泛化 `500`，导致真实错误不可见
3. n8n runner 的 `60s` 默认请求超时，会打断长链路
4. `03` 的 embedding 输入过长，当前 OpenRouter 通道会返回 provider 失败

真正把链路跑通，需要同时解决这四层问题。

## 后续建议

如果后面要把小宇宙正式接进 RSS 主入口，建议继续做两件事：

1. 把播客类 RSS item 自动分流到 `04`
2. 把 `03` 的 embedding 输入上限参数化，不要继续硬编码在 workflow 里

