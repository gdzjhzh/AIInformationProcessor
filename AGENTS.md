# Repository Guidance

请优先使用中文沟通；终端命令、路径、环境变量名称保留英文。

## New Session Handoff

如果是新的会话，且任务涉及 `01_rss_to_obsidian_raw`、`04_video_transcript_ingest`、`06_manual_media_submit`、`VideoTranscriptAPI`、`CapsWriter`、`FunASR` 或 transcript 调试，请先读这几个文件，再开始排障：

1. `deploy/TRANSCRIPT_RUNTIME_INVARIANTS.md`
2. `services/VideoTranscriptAPI/AGENTS.md`
3. `services/VideoTranscriptAPI/config/config.jsonc`
4. `DEBUG_LOG.md`

不要在没读完这几处之前，重新花时间猜测 transcript runtime 的服务边界。

如果任务涉及 `01_rss_to_obsidian_raw` 的轮询产出、订阅源是否真的抓到内容、某一轮为什么没写文件，先看：

5. `deploy/data/n8n/storage/poll_runs/`

这里会按 `YYYY/MM/` 落每轮轮询的 JSON 摘要。排障时优先看最新一份，确认：
- 本轮检查了哪些订阅源
- 哪些源 `success`
- 哪些源 `error`
- 每个源看到多少条 item
- 最终写入了哪些 `vault_path`

这个目录属于 runtime 排障证据，不属于 Obsidian 知识库内容。

濡傛灉浠诲姟娑夊強鍒囨崲 `LLM_*` provider銆佹帴鍏ユ柊鐨勫ぇ妯″瀷 API銆佸垽鏂?`02_enrich_with_llm` 鍜?`VideoTranscriptAPI` 鍚勮鏀瑰摢閲屻€佹垨鑰呮帓鏌ヤ负浠€涔堟崲 provider 鍚庢姤鍏煎鎬ч敊璇紝鍏堢湅锛?
6. `deploy/LLM_PROVIDER_PLAYBOOK.md`

涓嶈鍏堝幓 workflow JSON 鍜?transcript 浠ｇ爜閲岄噸鏂板弽鎺?`base_url`銆乣model`銆乣json_output` 鐨勮涔夈€傚厛鎸夎繖浠芥墜鍐岀‘璁ゆ槸涓婚摼 LLM銆乪mbedding锛岃繕鏄?transcript LLM锛屽啀鍐冲畾鏀瑰姩闈㈠拰楠岃瘉椤哄簭銆?
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

## Speaker Recognition Default Policy

- 不要把 `use_speaker_recognition` 的默认行为写死成“小宇宙特例”。
- `01_rss_to_obsidian_raw` 和 `06_manual_media_submit` 入口层必须保留三态语义：
  - 显式 `true`
  - 显式 `false`
  - 未设置 / `null`
- 默认推断只放在 `04_video_transcript_ingest`，不要在各入口各自重新推理一套。
- `04_video_transcript_ingest` 的推断应当是通用 media 规则，而不是平台硬编码：
  - 优先尊重显式 `true / false`
  - 仅在未设置时，根据 `source_type`、`media_type`、URL、标题、来源名、描述、feed URL 等线索统一推断
  - 对 `podcast / podcast_rss`、音频内容、以及标题/描述含 `播客 / 对谈 / 访谈 / podcast / interview` 等对话型线索的内容，可默认打开 speaker recognition
- 后续如果新增别的 media ingress，也复用这套 contract：入口保留三态，`04` 统一决定默认值。

## n8n Runtime Reminder

- `deploy/n8n/workflows/*.json` 是定义真相源。
- `deploy/data/n8n/database.sqlite` 是 runtime 缓存。
- 对外唯一发布入口是 `python deploy/n8n/scripts/publish_runtime.py`。
- 调试或验证前，先确认 repo JSON 和 runtime SQLite 已对齐。
- 不要默认 `n8n-nodes-base.executeCommand` 在当前 live runtime 可用。本机这套 n8n 在 workflow activation 阶段会把它识别成 unknown node type；即使容器里能看到 node 源码，也必须先做 live 验证，再决定能不能把它接进共享 workflow。

## Feishu Notification Test Reminder

- 测试飞书群机器人消息卡片时，不要在 Windows PowerShell 里把含中文的 JS 通过 stdin 管道传给 `docker compose exec ... node -`；这条路径会把中文变成 `?`，导致飞书收到问号乱码。
- 手动测试请使用 `python deploy/n8n/scripts/send_feishu_card_test.py`。脚本会从当前环境或 ignored 的 `deploy/.env` 读取 `FEISHU_WEBHOOK_URL`，用 UTF-8 JSON 发送消息卡片，并且不会打印 webhook。

## Git Publish Default

- 本仓库以后如果完成了实际文件修改，默认在验证通过后执行 `git commit` 并 `git push`。
- 提交信息使用中文清楚说明本次改动；可以保留 `feat:` / `fix:` 等前缀，但有效描述必须是中文。
- 提交前必须先检查 `git status --short --branch`、本次 diff 和 staged diff，只 stage 当前任务相关文件。
- 不要把无关运行时文件、缓存、日志、`deploy/tmp/` 或用户未要求提交的改动一起打进 commit。
- 如果验证失败、改动未完成，或工作区里存在无法安全区分的改动，不要自动提交；先说明阻塞点和保留的文件。
