# n8n 接入要点

当前仓库按 `Obsidian 主库` 模式执行。n8n 只负责编排，不要把业务判断继续堆进没有测试边界的 Code Node。

仓库里的 `deploy/n8n/workflows/*.json` 是定义真相源。`deploy/data/n8n/database.sqlite` 只是 runtime 缓存。对外唯一发布入口是 `python deploy/n8n/scripts/publish_runtime.py`。

## 主干原则

- 入口适配器只负责把外部内容转换成 `NormalizedTextObject`
- Obsidian 写入只保留一套 frontmatter 和命名规则
- `AI enrich`、`Qdrant gate`、`Vault writer` 必须能被多个入口复用
- `Memos` 是支路，不是 n8n 主干运行依赖
- 通知与写库解耦：写库失败不应假装已通知，通知失败不应回滚已写入的 Vault

## 共享主链

```text
00 -> 01a -> 03 -> [silent 则跳过 LLM] -> 02 -> 04a -> 05 -> 09 -> 03b
```

- `01_rss_to_obsidian_raw` 直接喂这条主链；媒体项先走 `04` 再回 `00`
- `06_manual_media_submit` 先走 `04`，再进入同一条主链
- `04_video_transcript_ingest` 只做 transcript adapter，不写 Vault
- `03` 只做 search / decide，返回 deferred upsert payload
- `05` 先写 Obsidian
- `03b` 只在 `vault_write_status=written` 时 upsert Qdrant

## 契约

`NormalizedTextObject` 的 canonical 字段是 `obsidianInboxDir / content_text / content_html / dedupe_action`。

`raw_text / raw_html / transcript_text / calibrated_transcript / obsidian_inbox_dir / action` 只允许停留在入口适配和 `00`。`00` 之后禁止继续依赖这些历史字段。

说话人识别保持三态：显式 `true` / 显式 `false` / 未设置。默认推断只放在 `04`。

校验：

```powershell
python contracts/validate_contract.py
python deploy/n8n/scripts/validate_workflow_boundaries.py
python deploy/n8n/scripts/validate_regression_matrix.py
```

## 发布

```powershell
python deploy/n8n/scripts/publish_runtime.py
```

调试前先确认 repo JSON 和 runtime SQLite 已对齐。不要默认 `n8n-nodes-base.executeCommand` 在当前 live runtime 可用。
