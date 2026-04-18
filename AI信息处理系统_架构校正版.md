# AI 信息处理系统：架构校正版

本文档以后作为当前仓库的执行基线。原始方案文档保留作参考，但实施顺序和模块职责以本文件为准。

## 核心原则

1. `Obsidian` 是最终知识库，所有长期内容都要终沉到 Vault。
2. `Memos` 不是主库，而是碎片收藏、IM 收件和 AI 增强支路。
3. `n8n` 负责流程编排，承接图中的 `AI Info Processor`。
4. `Qdrant` 负责三级降噪的向量检索，不在 n8n 内存里做全量比较。
5. 所有输入先统一转成文本，再进入打分、分类、摘要、去重和落库流程。
6. `回顾分析层` 不是主干流水线里的下一站，而是读取已有内容再回写到 `Obsidian` 的反馈回路。

## 主干与回路

### 主干流水线

```text
信息采集层（RSS源生成）
    ↓
处理系统层（AI打分 + 三级降噪去重）
    ↓
存储与增强层（Memos + im2memo飞书机器人 + memo auto）
    ↓
知识总基地（Obsidian 本地同步）
```

解释：

- 这是系统的主数据面
- `Obsidian` 是主干的最终沉淀点
- `Memos` 负责中间存储和增强，不替代最终知识库

### 回顾分析回路

```text
ManicTime + 每日复盘 + 群聊总结
    ↓
读取当天活动记录 + 已沉淀内容
    ↓
生成复盘、总结、回顾
    ↓
回写到 Obsidian
```

解释：

- 回顾分析层不应该画在 `Obsidian` 前面作为串行步骤
- 它的职责是消费主干已经生成的内容，再产出新的总结内容
- 因此它是反馈环，不是主干中的线性节点

## 架构映射

### 信息采集层

- `RSSHub`: B 站、小宇宙等平台
- `YouTube XML`: 频道订阅
- `WeChat to RSS`: 公众号
- `播客 RSS`: 小宇宙、Apple Podcast 等原生订阅

### 处理系统层

- `AI Info Processor`: 长文打分、分类、摘要、Embedding 去重
- `rss2im`: 短文本过滤
- `Video Transcript API`: 音视频转录与摘要
- `手动提交`: Tasker / Quicker / Web 快速投递

### 存储与增强层

- `im2memo`: IM 机器人一键收藏
- `Memos`: 碎片化笔记临时存储
- `memo auto`: 标签、评论、补充摘要、关联推荐

### 知识总基地

- `Obsidian (Local First)`: 最终 Markdown 沉淀

### 回顾分析层

- `Every Day Analysis`: 每日复盘
- `微信群总结`: 群聊回顾与整理
- `ManicTime`: 行为与时间记录输入源

## 当前仓库已经落地的部分

- `deploy/compose.yaml` 已跑通 `RSSHub / n8n / Qdrant / Memos / Redis`
- `n8n` 已具备承载 `AI Info Processor` 的基础环境
- `Qdrant` 已作为三级降噪基础设施加入
- `vault/` 已作为默认 Obsidian Vault 本地目录

## 当前仓库还缺的部分

- `rss2im`
- `Video Transcript API`
- `手动提交`
- `memo auto`
- `Every Day Analysis`
- `微信群总结`
- `订阅管理 Web 端`

## 执行顺序

### 阶段 1：主干先跑通

目标：
`RSS/YouTube/播客 -> n8n -> AI 打分/摘要 -> Obsidian Markdown`

要求：

- 先不引入复杂转录
- 先不引入 Memos 增强支路
- 先确认 Markdown 能稳定进入 Vault

### 阶段 2：加入通知与去重

目标：
`主干流程 + 飞书/企业微信推送 + Qdrant 三级降噪`

要求：

- 推送与落库解耦
- 相似度阈值采用：
  - `< 0.85`：完整推送
  - `0.85 ~ 0.97`：增量摘要
  - `> 0.97`：静默处理

### 阶段 3：加入 Memos 支路

目标：
`im2memo -> Memos -> memo auto -> Obsidian`

要求：

- Memos 只做中间增强，不抢主库角色
- 增强后的内容仍然要沉到 Obsidian

### 阶段 4：加入多入口

目标：

- `Video Transcript API`
- `手动提交`
- `rss2im`

要求：

- 所有入口统一转成文本对象
- 再复用主干处理流程

### 阶段 5：加入回顾分析

目标：

- `Every Day Analysis`
- `微信群总结`
- `ManicTime` 与语音复盘

要求：

- 分析结果同样回写到 Obsidian
- 不把分析层接到主干前面，而是作为独立反馈回路

### 阶段 6：加入订阅管理 Web 端

目标：

- 可视化管理 RSS / YouTube XML / 播客 / WeChat to RSS 订阅源
- 支持分组、启停、推送策略和去重策略管理

要求：

- 这是控制面，不阻塞主干数据链路
- 等主干流程稳定后再做，避免前期频繁返工

## 对当前实现的纠偏结论

- 之前的实现偏向 `Memos 中心化`
- 校正后的实现应改为 `Obsidian 中心化`
- `Memos` 保留，但角色降为支路缓存与增强层

## 当前下一步

下一步的具体落地任务应是：

1. 在 `n8n` 中创建第一条 `写入 Obsidian Markdown` 的工作流。
2. 设计 Markdown 文件命名、目录和 frontmatter 规范。
3. 再补飞书推送和 Qdrant 去重。
