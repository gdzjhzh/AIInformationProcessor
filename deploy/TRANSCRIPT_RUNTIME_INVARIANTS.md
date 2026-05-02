# Transcript Runtime Invariants

这份说明是给新的会话和新的排障轮次用的。先读它，再开始猜原因。

## Core Boundary

- `CapsWriter` 是宿主机本地服务，不在 Docker 里。
- `VideoTranscriptAPI` 访问 `CapsWriter` 使用 `ws://host.docker.internal:6016`。
- `FunASR` 是 Docker 内服务。
- `VideoTranscriptAPI` 访问 `FunASR` 使用 `ws://funasr-spk-server:8767`。

不要把这两个服务当成同一层。`CapsWriter` 失败，不代表 Docker 里的 `FunASR` 有问题；`FunASR` 容器没起来，也不代表宿主机 `CapsWriter` 丢了。

## Why This Matters

之前排障里已经因为这个边界混淆浪费过时间。新的会话如果忽略这件事，很容易重复犯这几种错误：

- 把 `CapsWriter` 误认为 Docker 服务，然后去查错误的容器
- 把 `FunASR` 误认为宿主机本地端口，然后在 Windows 上找不存在的本地进程
- 在 `04_video_transcript_ingest` 或 n8n workflow 上绕圈，实际上问题在 transcript backend 的运行边界

## Current Repo Contract

以仓库当前配置为准：

- `services/VideoTranscriptAPI/config/config.jsonc`
  - `capswriter.server_url = ws://host.docker.internal:6016`
  - `funasr_spk_server.server_url = ws://funasr-spk-server:8767`

额外说明：

- `CapsWriter` 当前服务端要求 WebSocket subprotocol `binary`
- 仓库里的 `VideoTranscriptAPI` client 和 `/health` 检查已经按这个要求接好了

## Speaker Recognition Default Contract

- 不要把 `use_speaker_recognition` 的默认值写死成“小宇宙专用开关”。
- `01_rss_to_obsidian_raw` 和 `06_manual_media_submit` 这些 ingress 只负责保留输入语义，不负责决定默认值：
  - 显式 `true` 原样透传
  - 显式 `false` 原样透传
  - 未设置时继续保持 `null` / 未设置
- 统一默认推断只放在 `04_video_transcript_ingest`：
  - 先尊重显式 `true / false`
  - 仅在未设置时，再根据 `source_type`、`media_type`、URL、标题、来源名、描述、feed URL 等线索做通用推断
  - 这套推断是 generic media contract，不是平台硬编码；目标是覆盖 future podcast / audio / conversation-style sources，而不只是小宇宙
- 后续如果新增别的 media ingress，也沿用这套 contract：入口保留三态，`04` 统一决定默认 speaker recognition。

## Semantic Boundary

- `VideoTranscriptAPI` 不是 canonical enrichment 或 action policy 层。
- 服务内部的 `summary / cache / LLM` 结果，如果存在，只能映射到 `upstream_summary` 或 `transcript_service_meta`。
- canonical `summary / score / ai_score / score_dimensions / category / tags / should_write_to_vault / should_notify / notification_mode / should_upsert_qdrant` 只能由共享主链 `02_enrich_with_llm` 和 `04a_action_policy` 产生。
- `04_video_transcript_ingest` 继续保持 adapter-only；它可以返回 transcript service 的辅助上下文，但不能直接产出 canonical enrichment 或写入/通知决策。

建议适配形态：

```yaml
upstream_summary: "transcript service summary, optional"
transcript_service_meta:
  backend: "VideoTranscriptAPI"
  asr_provider: "FunASR"
  duration_seconds: 1234
  language: "zh"
  transcript_quality: "medium"
  cache_hit: true
  service_summary_present: true
```

## First Debug Order

如果 transcript 主链失败，先按下面顺序检查，不要跳步：

1. 检查宿主机本地 `6016` 是否有人监听
2. 检查 `video-transcript-api` 配置是否仍指向 `ws://host.docker.internal:6016`
3. 检查 `funasr-spk-server` 容器是否真的起来，且 Docker 网络内 `8767` 可达
4. 再看 `video-transcript-api` 的 `/health`
5. 最后才回到 n8n 的 `04_video_transcript_ingest`

## Practical Checks

宿主机本地 `CapsWriter`：

```powershell
Get-NetTCPConnection -LocalPort 6016 -State Listen
```

Docker 内 `FunASR`：

```powershell
docker ps --format "table {{.Names}}\t{{.Status}}\t{{.Ports}}"
docker logs signal-to-obsidian-funasr-spk-server-1 --tail 200
```

`VideoTranscriptAPI` 健康检查：

```powershell
docker exec signal-to-obsidian-video-transcript-api-1 python -c "import urllib.request; print(urllib.request.urlopen('http://127.0.0.1:8000/health', timeout=10).read().decode())"
```

## Related Files

- `AGENTS.md`
- `services/VideoTranscriptAPI/AGENTS.md`
- `services/VideoTranscriptAPI/config/config.jsonc`
- `DEBUG_LOG.md`
