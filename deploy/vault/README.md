# Obsidian Vault Scaffold

这个目录是默认的 Obsidian Vault 挂载点。

目录约定：

- `00_Inbox/AI_Information_Processor`: 信息流收件箱
- `10_Daily`: Daily Notes
- `20_Sources`: 来源归档
- `30_Reviews`: 每日复盘与总结

## 主干写入约定

当前主干默认先写入：

- `00_Inbox/AI_Information_Processor`

这里是统一对象进入 Vault 的第一落点。后续 AI enrich、去重和回顾流程都应更新同一条对象，而不是重新生成第二份笔记。

## 文件命名

默认命名规则：

`{date}_{source_type}_{item_id[:10]}_{slug}.md`

示例：

`2026-04-17_rss_6d6e2f96ab_openai-model-update.md`

说明：

- `item_id` 是稳定幂等主键，不应被抓取时间戳替代。
- `slug` 只负责可读性，不能承担唯一性。
- 同一条内容重复抓取时，优先更新同一路径。

## Frontmatter 基线

```yaml
---
title: 标题
item_id: 6d6e2f96ab2c
source_type: rss
source_name: OpenAI YouTube
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
---
```

约束：

- `published_at` 和 `ingested_at` 一律使用带时区的 ISO 8601。
- `status` 表示对象阶段，不表示具体来源。
- `dedupe_action` 由主干判定器写入，供后续通知和回顾复用。

## 时区

- Vault 写入、Daily 路由和复盘统计使用同一 `TZ`。
- 若外部服务产生了其他时区的时间戳，进入主干时需要规范化。

如果你已经有自己的 Vault，可以把 `.env` 里的 `OBSIDIAN_VAULT_PATH` 改成现有目录，然后保留这里的结构约定即可。
