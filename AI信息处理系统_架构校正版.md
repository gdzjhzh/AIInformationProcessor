# AI 信息处理系统：架构校正版

本文档以后作为当前仓库的执行基线。原始方案文档保留作参考，但实施顺序和模块职责以本文件为准。

## 核心原则

1. `Obsidian` 是最终知识库，所有长期内容都要终沉到 Vault。
2. `Memos` 不是主库，而是碎片收藏、IM 收件和 AI 增强支路。
3. `n8n` 负责流程编排，承接图中的 `AI Info Processor`。
4. `Qdrant` 负责三级降噪的向量检索，不在 n8n 内存里做全量比较。
5. 所有输入先统一转成 `NormalizedTextObject`，再进入打分、分类、摘要、去重和落库流程。
6. `回顾分析层` 不是主干流水线里的下一站，而是读取已有内容再回写到 `Obsidian` 的反馈回路。

## 阶段 0：统一对象契约

阶段 0 不是可选优化，而是后续所有入口、去重、摘要和回写的共同基线。没有统一对象契约，RSS、转录、手动提交和 Memos 支路会各自长出一套字段体系，最终导致重复写入、无法幂等更新、frontmatter 漂移和后续复盘口径不一致。

### 分层约束

系统按四层落地：

- `数据面`：所有入口先产出 `NormalizedTextObject`，主干负责 AI enrich、Embedding、Qdrant 判定和 Obsidian 写入。
- `支路面`：`Memos / im2memo` 是可选增强支路，不参与主干串行依赖。
- `反馈面`：`Every Day Analysis / 微信群总结 / ManicTime` 只读取已沉淀内容，再回写总结结果。
- `控制面`：订阅管理 Web 端只负责配置、分组和开关，不直接承载主干处理逻辑。

### NormalizedTextObject

所有入口在进入主干前，至少要产出下面这组字段：

```yaml
item_id: string
source_type: rss | youtube_xml | podcast | transcript | manual | memos
source_name: string
original_id: string
canonical_url: string
title: string
author: string
published_at: string
ingested_at: string
media_type: text | audio | video | image
content_text: string
content_html: string
upstream_task_id: string
upstream_view_token: string
upstream_summary: string
content_hash: string
score: number
category: string
tags: string[]
dedupe_action: full_push | diff_push | silent
status: raw | enriched | deduped | archived
vault_path: string
```

字段说明：

- `item_id`：幂等主键，用于稳定更新同一条内容。
- `canonical_url`：优先保留平台最终链接，供去重和回溯使用。
- `content_text`：后续 embedding、评分、摘要统一消费的主文本。
- `content_html`：可选保留原始正文，用于需要更丰富渲染的场景。
- `upstream_task_id / upstream_view_token / upstream_summary`：保留上游服务回执，但只作为内部追踪字段。
- `vault_path`：写入 Vault 后的稳定目标路径，用于后续补写而不是重新造一份新笔记。

### item_id 与幂等规则

- 优先使用 `canonical_url` 生成稳定哈希。
- 若缺失 `canonical_url`，退化为 `source_type + original_id`。
- 若仍缺失，再退化为 `title + published_at + author` 的组合哈希。
- `item_id` 一旦确定，同一条内容后续重复抓取时应更新同一路径，而不是制造第二份笔记。
- `content_hash` 只用于内容变化检测，不能替代 `item_id`。

### 文件命名与 frontmatter 规则

默认文件名：

`{date}_{source_type}_{item_id[:10]}_{slug}.md`

建议 frontmatter：

```yaml
---
title: 标题
item_id: 6d6e2f96ab2c
source_type: rss
source_name: OpenAI YouTube
original_id: yt:abc123
canonical_url: https://example.com/post
published_at: 2026-04-17T09:00:00-04:00
ingested_at: 2026-04-17T09:05:00-04:00
media_type: text
content_hash: sha256:...
workflow: rss-to-obsidian-raw
score: 0
category: pending
tags:
  - inbox
  - ai-information-processor
dedupe_action: full_push
status: raw
upstream_task_id:
upstream_summary:
---
```

约束：

- `published_at`、`ingested_at` 一律写入带时区的 ISO 8601。
- `upstream_view_token` 不进入公开正文，只保留在内部字段或私有 metadata。
- `status` 反映对象阶段，而不是工作流名称。
- 后续 `Workflow 1A / Workflow 2` 只补写同一份 frontmatter，不再引入第二套 note 结构。

### 统一时区规则

- 主干仓库统一使用同一个 `TZ`，由 `deploy/.env` 和 `compose.yaml` 向所有容器传递。
- 文件命名、`published_at`、`ingested_at`、Daily 路由和复盘统计必须共享同一时区口径。
- 如需展示原始平台时区，可额外保留字段，但主干写库时间一律遵循系统统一时区。
- `Video Transcript API` 若外部独立部署，接入时也必须显式对齐主干时区。

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
- `Video Transcript API`: 音视频下载、转录与校对，输出可复用的上游文本对象
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

### 阶段 0：先固化统一对象 contract

目标：
`定义 NormalizedTextObject / item_id / 命名 / frontmatter / 时区规则`

要求：

- 先把主干 contract 写成文档和模板，不让每个入口各自造字段。
- 先确定文件稳定命名和幂等更新规则，再接更多入口。
- 先统一时间口径，再做 Daily 路由、复盘统计和外部服务接入。

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
- `Video Transcript API` 只负责下载、转录、校对，上游摘要仅作为 `upstream_summary` 参考字段
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

1. 先补齐 `阶段 0` 文档、对象契约、稳定命名和 frontmatter 规范。
2. 把 `01_rss_to_obsidian_raw` 改成输出统一对象并走统一 writer。
3. 再补 `Workflow 1A` 的结构化 AI enrich 与 `Workflow 2` 的 Qdrant gate。
