# n8n 接入要点

当前仓库按 `Obsidian 主库` 模式执行，先做最小可用链路，再逐步补通知、去重和增强支路。

## Workflow 1: RSS / YouTube / 播客 -> Obsidian Raw Inbox

仓库内现成模板：

- `deploy/n8n/workflows/01_rss_to_obsidian_raw.json`

这是已经落地的第一条主干，不依赖 LLM。

## Workflow 1A: RSS / YouTube / 播客 -> AI 打分 -> Obsidian

这是第一优先级主干的下一步增强版。

推荐节点顺序：

1. `Schedule Trigger`
2. `RSS Feed Read`
3. `HTTP Request` 或 `Code` 节点清洗正文
4. `HTTP Request` 调用 LLM
5. `Code` 节点解析结构化 JSON
6. `Code` 节点生成 Markdown 和 frontmatter
7. `Write Binary File` 或等效方式写入 `/vault/{{$env.OBSIDIAN_INBOX_DIR}}`

## Workflow 2: RSS / YouTube / 播客 -> Embedding -> Qdrant 去重

这是第二优先级，用于三级降噪。

推荐节点顺序：

1. `Schedule Trigger`
2. `RSS Feed Read`
3. `HTTP Request` 调用 Embedding 接口
4. `HTTP Request` 查询 Qdrant 最近邻
5. `Code` 节点判断动作
6. `IF` 节点分流
7. `HTTP Request` 写入 Qdrant
8. `HTTP Request` 推送飞书或企业微信

## Workflow 3: im2memo / Memos -> memo auto -> Obsidian

这是存储增强支路，不是主干。

推荐节点顺序：

1. `Webhook` 或 `Memos` 事件触发
2. `Code` 节点判断 URL / 图片 / 纯文本
3. `HTTP Request` 调用 LLM 生成标签、评论和补充摘要
4. `HTTP Request` 查询 Qdrant 相似历史内容
5. `Code` 节点生成增强版 Markdown
6. 写入 `/vault`

## Workflow 4: Video Transcript API -> Obsidian

这是多媒体入口。

推荐节点顺序：

1. `Webhook` 或轮询视频来源
2. `HTTP Request` 调用转录服务
3. `HTTP Request` 调用 LLM 生成摘要
4. `Code` 节点生成 Markdown
5. 写入 `/vault`

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

## Obsidian 文件约定

- 主库路径：`/vault`
- 收件箱目录：`/vault/{{$env.OBSIDIAN_INBOX_DIR}}`
- Daily Notes 目录：`/vault/{{$env.OBSIDIAN_DAILY_DIR}}`

建议文件名：

`YYYY-MM-DD_HH-mm-ss_slug.md`

建议 frontmatter：

```yaml
---
title: 标题
source: 来源名称
source_url: 原文链接
published_at: 2026-04-17T09:00:00-04:00
score: 0
category: AI
tags:
  - inbox
  - ai-information-processor
dedupe_action: full_push
---
```
