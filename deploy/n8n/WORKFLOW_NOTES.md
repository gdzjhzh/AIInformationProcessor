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
4. `00_common_normalize_text_object`
5. `Vault Writer`

说明：

- 当前仓库里的 `deploy/n8n/workflows/01_rss_to_obsidian_raw.json` 应视为“主干基线模板”。
- 若仓库继续保留 `active=false`，文档中要明确它是导入模板，不是默认生产态工作流。
- 空配置时允许保留演示 RSS，但只作为 smoke test，不作为长期默认源。

### `02_enrich_with_llm`

职责：统一执行评分、分类、标签和摘要。

输入：`NormalizedTextObject`

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

### `03_qdrant_gate`

职责：执行 embedding、近邻搜索和三级动作判定。

建议节点顺序：

1. `Input`
2. `Embedding HTTP Request`
3. `Qdrant Search`
4. `Code: Decide Action`
5. `IF`
6. `Qdrant Upsert`
7. `Vault Writer` 与 `Notifier` 分支

判定规则：

- `< 0.85`：`full_push`
- `0.85 ~ 0.97`：`diff_push`
- `> 0.97`：`silent`

约束：

- `EMBEDDING_MODEL` 与 `QDRANT_VECTOR_SIZE` 必须绑定，不能留一个空模型配一个写死维度。
- `Qdrant` 在主干里是写入前判定器，不是事后增强件。

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
8. `Vault Writer`

边界约束：

- `VideoTranscriptAPI` 负责下载、转录、校对。
- 主干负责打分、分类、标签、最终摘要和落库。
- `view_token` 只做内部追踪，不能当公开分发链接。

### `05_memos_branch_ingest`

职责：支路增强，不抢主干角色。

建议节点顺序：

1. `Webhook` 或 `Memos` 事件
2. `00_common_normalize_text_object`
3. `02_enrich_with_llm`
4. `03_qdrant_gate`
5. `Vault Writer`

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
      "id": "{{$json.id}}",
      "vector": {{$json.embedding}},
      "payload": {
        "title": "{{$json.title}}",
        "url": "{{$json.url}}",
        "published_at": "{{$json.published_at}}"
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
