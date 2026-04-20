# Repository Guidance

请优先使用中文沟通；终端命令、路径、环境变量名称保留英文。

## New Session Handoff

如果是新的会话，且任务涉及 `01_rss_to_obsidian_raw`、`04_video_transcript_ingest`、`06_manual_media_submit`、`VideoTranscriptAPI`、`CapsWriter`、`FunASR` 或 transcript 调试，请先读这几个文件，再开始排障：

1. `deploy/TRANSCRIPT_RUNTIME_INVARIANTS.md`
2. `services/VideoTranscriptAPI/AGENTS.md`
3. `services/VideoTranscriptAPI/config/config.jsonc`
4. `DEBUG_LOG.md`

不要在没读完这几处之前，重新花时间猜测 transcript runtime 的服务边界。

## Transcript Runtime Boundary

- `CapsWriter` 是宿主机本地服务，不在 Docker 里。
- `VideoTranscriptAPI` 访问 `CapsWriter` 的地址是 `ws://host.docker.internal:6016`。
- `FunASR` 是 Docker 内服务，不是宿主机本地服务。
- `VideoTranscriptAPI` 访问 `FunASR` 的地址是 `ws://funasr-spk-server:8767`。
- 这两个服务不要混为一谈；排障时应分别验证宿主机本地监听和 Docker 内服务健康，而不是假设它们在同一个运行边界。

## Transcript First Checks

如果 transcript 链路失败，先按这个顺序检查：

1. 宿主机本地 `CapsWriter` 是否真的在监听 `6016`
2. `video-transcript-api` 容器内配置是否仍然是 `ws://host.docker.internal:6016`
3. `funasr-spk-server` 容器是否真的启动并在 Docker 网络内可达 `8767`
4. `video-transcript-api` 的 `/health` 是哪一项失败，而不是直接把 `04` 或 n8n workflow 当成根因

## n8n Runtime Reminder

- `deploy/n8n/workflows/*.json` 是定义真相源。
- `deploy/data/n8n/database.sqlite` 是 runtime 缓存。
- 对外唯一发布入口是 `python deploy/n8n/scripts/publish_runtime.py`。
- 调试或验证前，先确认 repo JSON 和 runtime SQLite 已对齐。
- 不要默认 `n8n-nodes-base.executeCommand` 在当前 live runtime 可用。本机这套 n8n 在 workflow activation 阶段会把它识别成 unknown node type；即使容器里能看到 node 源码，也必须先做 live 验证，再决定能不能把它接进共享 workflow。
