# n8n 接入要点

当前仓库按 `Obsidian 主库` 模式执行。n8n 只负责编排，不应该继续演变成没有测试边界的业务代码仓。后续所有入口都先收口成统一对象，再复用主干节点链路。

## 主干原则

- 入口适配器只负责把外部内容转换成 `NormalizedTextObject`。
- Obsidian 写入器只保留一套 frontmatter 和命名规则。
- `AI enrich`、`Qdrant gate`、`Vault writer` 必须能被多个入口复用。
- `Memos` 是支路，不是 n8n 主干运行依赖。
- 通知与写库解耦，避免“写库失败阻塞通知”或“通知失败阻塞落库”。

## 工作流拆分

### `00_common_normalize_text_object`

职责：把任意入口统一映射为主干对象。

最小输出字段：

```json
{
  "item_id": "stable-hash",
  "source_type": "rss",
  "source_name": "OpenAI YouTube",
  "original_id": "platform-item-id",
  "canonical_url": "https://example.com/post",
  "title": "Post title",
  "author": "Author",
  "published_at": "2026-04-17T09:00:00-04:00",
  "ingested_at": "2026-04-17T09:05:00-04:00",
  "media_type": "text",
  "content_text": "normalized plain text",
  "content_html": "<p>optional</p>",
  "upstream_task_id": "",
  "upstream_view_token": "",
  "upstream_summary": "",
  "content_hash": "sha256:...",
  "score": 0,
  "category": "pending",
  "tags": [],
  "dedupe_action": "full_push",
  "status": "raw",
  "vault_path": ""
}
```

约束：

- `item_id` 优先由 `canonical_url` 或 `source_type + original_id` 生成。
- `content_text` 是后续评分、摘要、embedding 唯一主文本。
- `vault_path` 由统一 writer 生成，不允许各入口自行定义另一套命名。

### `01_rss_to_obsidian_raw`

职责：RSS / YouTube XML / 播客的主干基线。

建议节点顺序：

1. `Schedule Trigger`
2. `Feed Sources`
3. `RSS Feed Read`
4. `Build Normalize Input`
5. `IF route_to_transcript`
6. `04_video_transcript_ingest`（播客 / 音频候选）或 `00_common_normalize_text_object`（普通文本）
7. `02_enrich_with_llm`
8. `03_qdrant_gate`
9. `05_common_vault_writer`

说明：

- 当前仓库里的 `deploy/n8n/workflows/01_rss_to_obsidian_raw.json` 已串联 `02_enrich_with_llm`、`03_qdrant_gate` 和共享 `05_common_vault_writer`，应视为“RSS -> enrich -> gate -> Vault”的主干基线模板。
- 播客类 RSS item 应在 `Build Normalize Input` 后直接分流到 `04_video_transcript_ingest`，不要把节目简介当正文直接送进 `00 -> 02 -> 03`。
- 若仓库继续保留 `active=false`，文档中要明确它是导入模板，不是默认生产态工作流。
- 空配置时允许保留演示 RSS，但只作为 smoke test，不作为长期默认源。
- `Build Markdown` 现在属于 `05_common_vault_writer` 内部职责，应写回 `summary / reason / enriched_at`，不要让 enrich 结果停留在临时执行数据里。
- `silent` 必须真正跳过写库；`diff_push` 则应把匹配上下文一起写入 note，便于核对实际降噪结果。

### `02_enrich_with_llm`

职责：统一执行评分、分类、标签和摘要。

输入：`NormalizedTextObject`

建议节点顺序：

1. `Execute Workflow Trigger` 或 `Manual Trigger + Example Normalized Text Object`
2. `Validate Normalized Text Object`
3. `Build LLM Request`
4. `HTTP Request -> {{$env.LLM_BASE_URL}}/chat/completions`
5. `Parse And Merge Enrichment`

输出要求：LLM 返回固定 JSON schema，并补写到同一对象上：

```json
{
  "score": 0.82,
  "category": "AI Infra",
  "tags": ["openai", "model-release"],
  "summary": "一段最终摘要",
  "reason": "为什么值得保留或降权"
}
```

约束：

- `summary` 是主干最终摘要，不再从别处复制第二份摘要字段。
- `Video Transcript API` 若上游已返回摘要，只写入 `upstream_summary` 供参考。
- 同一条对象只更新同一份 frontmatter 和正文，不再产出第二种 note 结构。
- 被 `01_rss_to_obsidian_raw` 调用时，应通过 `Execute Workflow Trigger` 直接消费上游 item，不再重新造一份示例对象。
- 作为 `01` 的子工作流导入时，`02_enrich_with_llm` 必须处于可执行状态，否则 `Execute Workflow` 会直接报 `Workflow is not active`。
- 工作流应在调用 LLM 之前校验 `item_id / source_type / source_name / title / content_text` 和 `LLM_BASE_URL / LLM_MODEL / LLM_API_KEY`。
- 推荐沿用 OpenAI-compatible Chat Completions 接口，并把 `response_format` 固定成 `json_object`。
- 回写对象时应新增 `summary`、`reason`、`enriched_at`，并把 `status` 更新为 `enriched`。

### `03_qdrant_gate`

职责：执行 embedding、近邻搜索和三级动作判定。

建议节点顺序：

1. `Execute Workflow Trigger` 或 `Manual Trigger + Example Enriched Item`
2. `Validate Gate Input`
3. `Build Embedding Request`
4. `HTTP Request -> {{$env.EMBEDDING_BASE_URL}}/embeddings`
5. `Build Qdrant Search Request`
6. `Qdrant Search -> http://qdrant:6333/collections/{collection}/points/search`
7. `Code: Decide Action`
8. `Build Qdrant Upsert Payload`
9. `Return Gate Result`

判定规则：

- `< 0.85`：`full_push`
- `0.85 ~ 0.97`：`diff_push`
- `> 0.97`：`silent`

默认应通过环境变量显式收口为：

- `EMBEDDING_INPUT_MAX_CHARS=8000`
- `QDRANT_DIFF_THRESHOLD=0.85`
- `QDRANT_SILENT_THRESHOLD=0.97`

约束：

- `EMBEDDING_MODEL` 与 `QDRANT_VECTOR_SIZE` 必须绑定，不能留一个空模型配一个写死维度。
- `EMBEDDING_INPUT_MAX_CHARS` 应作为 provider 兼容层参数，而不是继续硬编码在 workflow 里。
- `Qdrant` 在主干里是写入前判定器，不是事后增强件。
- `03_qdrant_gate` 的输入应来自 `02_enrich_with_llm`，至少带上 `summary`，不要回退成只看 raw 文本。
- 工作流应输出 `should_write_to_vault`、`should_notify`、`should_upsert_qdrant` 和 `notification_mode`，让下游分支而不是把判断硬编码进别的节点。
- `item_id` 是业务幂等主键，不要直接拿去当 Qdrant 点 ID；应生成稳定的 `qdrant_point_id` UUID。
- `03_qdrant_gate` 现在只负责 `search / decide / build deferred upsert payload`；真正的 Qdrant upsert 必须等 `05_common_vault_writer` 写库成功后再执行，避免索引先于主库落地。
- 若最近邻命中的 `payload.item_id` 与当前对象相同，要先区分“同一篇文章内容未变”与“同一篇文章更新了内容”：
  - 相同 `content_hash`：`silent`
  - 不同 `content_hash`：`diff_push`

### `04_video_transcript_ingest`

职责：把 `VideoTranscriptAPI` 接成一个外部入口适配器，而不是把它重写进 code node。

建议节点顺序：

1. `Webhook` 或手动触发
2. `POST /api/transcribe`
3. `Poll /api/task/{id}`
4. `GET /view/{token}?raw=calibrated`
5. `00_common_normalize_text_object`
6. `02_enrich_with_llm`
7. `03_qdrant_gate`
8. `Return Mainline Result`

边界约束：

- `VideoTranscriptAPI` 负责下载、转录、校对。
- 主干负责打分、分类、标签、最终摘要；真正的 Vault 写入由调用者再统一交给 `05_common_vault_writer`。
- `view_token` 只做内部追踪，不能当公开分发链接。

### `05_common_vault_writer`

职责：共享 Obsidian 写入层，只消费已经过 `03_qdrant_gate` 的主线对象。

输入：至少包含 `item_id / title / published_at / should_write_to_vault`，并优先携带 `summary / reason / dedupe_action / notification_mode / matched_payload`。

建议节点顺序：

1. `Execute Workflow Trigger` 或 `Manual Trigger + Example Gate Result`
2. `Prepare Vault Write Context`
3. `IF should_write_to_vault`
4. `Build Markdown`
5. `Write Binary File`
6. `IF should_upsert_qdrant`
7. `Qdrant Upsert`
8. `Return Vault Result`

边界约束：

- `05_common_vault_writer` 内部自己处理 `skip / write / return status`，上游入口不再各自维护一套 `IF should_write_to_vault`。
- 文件命名、frontmatter、`vault_path` 生成规则只保留这一套，避免 `01 / 06 / 后续入口` 再长出第二套 note 结构。
- 统一返回 `vault_path / vault_write_status`，并保留 `vault_write` 兼容字段，供旧入口逐步迁移。
- `should_write_to_vault=false` 时必须返回 `skipped`，而不是让各入口自行约定空值或缺字段。
- `Qdrant Upsert` 只允许发生在 `Write Binary File` 成功之后；如果 Vault 没写成，索引必须保持未提交状态。

### `06_manual_media_submit`

职责：本地手动投递媒体 URL，只负责把 YouTube / 播客 / 其他音视频链接接入主链。

建议节点顺序：

1. `Webhook` 或手动触发
2. `Normalize Manual Media Request`
3. `04_video_transcript_ingest`
4. `05_common_vault_writer`
5. `Respond to Webhook`

边界约束：

- 这个入口只接 `media URL`，不接文章正文、剪藏文本或通用手动笔记。
- URL 进入后先走 `04_video_transcript_ingest`，不要重新发明一套转录或摘要逻辑。
- `04_video_transcript_ingest` 只返回主线结果，不在内部直接写 Vault；写库统一走共享 `05_common_vault_writer`。
- 触发方式可以是 `Webhook / Quicker / Tasker / 简单表单`，但进入主链前必须统一成同一份输入对象。
- `source_type` 应保留内容来源语义，例如 `podcast` 或 `transcript`，不要因为它是手动触发就整体改成 `manual`。
- 可以追加 `manual-submit` tag，用来标识触发方式；不要让它污染去重、统计和来源语义。
- 默认本地 webhook 路径使用 `POST /webhook/aip/local/manual-media-submit`。
- 在当前 repo JSON 直同步到 SQLite 的运行模式下，live webhook 实际注册路径以 `webhook_entity.webhookPath` 为准；必要时先从 `deploy/data/n8n/database.sqlite` 查询后再调用。

### `07_memos_branch_ingest`

职责：支路增强，不抢主干角色。

建议节点顺序：

1. `Webhook` 或 `Memos` 事件
2. `00_common_normalize_text_object`
3. `02_enrich_with_llm`
4. `03_qdrant_gate`
5. `05_common_vault_writer`

## Qdrant 集合初始化

在 n8n 里先执行一次：

```http
PUT http://qdrant:6333/collections/{{$env.QDRANT_COLLECTION}}
Content-Type: application/json

{
  "vectors": {
    "size": {{$env.QDRANT_VECTOR_SIZE}},
    "distance": "Cosine"
  }
}
```

## Qdrant 搜索请求样例

```http
POST http://qdrant:6333/collections/{{$env.QDRANT_COLLECTION}}/points/search
Content-Type: application/json

{
  "vector": {{$json.embedding}},
  "limit": 1,
  "with_payload": true
}
```

## Qdrant Upsert 样例

```http
PUT http://qdrant:6333/collections/{{$env.QDRANT_COLLECTION}}/points
Content-Type: application/json

{
  "points": [
    {
      "id": "{{$json.qdrant_point_id}}",
      "vector": {{$json.embedding}},
      "payload": {
        "item_id": "{{$json.item_id}}",
        "title": "{{$json.title}}",
        "canonical_url": "{{$json.canonical_url}}",
        "published_at": "{{$json.published_at}}",
        "dedupe_action": "{{$json.dedupe_action}}"
      }
    }
  ]
}
```

## 三级降噪代码节点

```javascript
const match = $json.qdrant_result?.[0];

if (!match || match.score < 0.85) {
  return [{ json: { ...$json, action: 'full_push' } }];
}

if (match.score < 0.97) {
  return [{ json: { ...$json, action: 'diff_push', matched_payload: match.payload } }];
}

return [{ json: { ...$json, action: 'silent', matched_payload: match.payload } }];
```

## 提示词约定

- `LLM_MODEL` 负责打分、摘要、标签和评论
- `EMBEDDING_MODEL` 只负责生成向量
- 不要把打分模型和 embedding 模型混成一个配置项
- 若切换 embedding 模型，必须同步检查 collection 维度是否匹配

## Obsidian 文件约定

- 主库路径：`/vault`
- 收件箱目录：`/vault/{{$env.OBSIDIAN_INBOX_DIR}}`
- Daily Notes 目录：`/vault/{{$env.OBSIDIAN_DAILY_DIR}}`

建议文件名：

`{date}_{source_type}_{item_id[:10]}_{slug}.md`

建议 frontmatter：

```yaml
---
title: 标题
item_id: 6d6e2f96ab2c
source_type: rss
source_name: 来源名称
canonical_url: 原文链接
published_at: 2026-04-17T09:00:00-04:00
ingested_at: 2026-04-17T09:05:00-04:00
content_hash: sha256:...
score: 0
category: pending
tags:
  - inbox
  - ai-information-processor
dedupe_action: full_push
status: raw
---
```
## 运行态同步

- 仓库内的 `deploy/n8n/workflows/*.json` 才是工作流定义的 source of truth
- 不要继续手改 `deploy/data/n8n/database.sqlite`
- 对外只使用 `python deploy/n8n/scripts/publish_runtime.py` 作为发布入口
- `publish_runtime.py` 内部会调用 `sync_workflows.py`，并把它固定为唯一 SQLite 写入步骤
- 发布链路固定为 `sync -> restart n8n -> check_runtime_alignment`
- 根目录 `DEBUG_LOG.md` 是统一调试日志，发布/同步/校验脚本都会追加到这里
- 使用 `python deploy/n8n/scripts/smoke_qdrant_gate.py` 在终端侧检查 embedding 配置、collection 维度和三种 `dedupe_action` 的实际分支结果
- `sync_workflows.py` 会先备份活动 SQLite 库，再补齐 `workflow_entity` 和 `workflow_history`
- 被 `Execute Workflow` 调用的子工作流，必须同时具备：
  - `workflow_entity.active = true`
  - `workflow_entity.activeVersionId = versionId`
  - `workflow_history.versionId = versionId`
- 当前 `02_enrich_with_llm` 和 `03_qdrant_gate` 都依赖这三项，缺任意一项都会在运行时触发 `Workflow is not active`
