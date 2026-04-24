# AI 信息处理系统本地部署

当前目录按最新架构图对齐后，采用 `Obsidian 主库` 模式：

- `Obsidian` 是最终知识沉淀
- `n8n + AI Info Processor` 是处理编排层
- `Memos / im2memo / memo auto` 是存储增强支路，不是主库
- `Qdrant` 为三级降噪提供向量检索
- `RSSHub / YouTube XML / 播客 RSS / WeChat to RSS` 是输入层
- `ManicTime / 每日复盘 / 群聊总结` 是反馈回路，读取已有内容后再回写到 `Obsidian`

## 主干与回路

主干：

`信息采集 -> 处理系统 -> 存储与增强 -> Obsidian`

回路：

`ManicTime / 每日复盘 / 群聊总结 -> Obsidian`

这里不要把 `回顾分析层` 误解为主干里的下一站。它不是串行步骤，而是围绕 `Obsidian` 的分析反馈层。

## 目录说明

- `compose.yaml`: 本地 Docker 编排文件
- `.env`: 当前可直接启动的本地默认配置
- `.env.example`: 供你后续重置或参考的环境变量模板
- `data/`: 所有本地持久化数据目录
- `n8n/WORKFLOW_NOTES.md`: n8n 接入要点和请求样例
- `vault/`: 默认的 Obsidian Vault 挂载目录

## 当前已落地的模块

- `RSSHub`
- `AI Info Processor` 的基础编排容器 `n8n`
- `Qdrant`
- `Memos`
- `Video Transcript API`（已内嵌到 `services/VideoTranscriptAPI`，按需用 profile 启动）
- `Obsidian Vault` 本地目录挂载到 `n8n:/vault`

## 仍待补齐的模块

- `rss2im`
- `通用手动提交（非媒体类）`
- `memo auto`
- `Every Day Analysis`
- `微信群总结`
- `订阅管理 Web 端`

## 直接启动核心服务

在当前目录执行：

```powershell
docker compose up -d memos n8n qdrant redis rsshub
```

启动后访问：

- Memos: [http://localhost:5230](http://localhost:5230)
- n8n: [http://localhost:5678](http://localhost:5678)
- Qdrant: [http://localhost:6333/dashboard](http://localhost:6333/dashboard)
- RSSHub: [http://localhost:1200](http://localhost:1200)

### RSSHub 两种启动模式

- 默认模式：`docker compose up -d rsshub`，使用 `.env` 里的 `RSSHUB_IMAGE`，默认值是 `diygod/rsshub:latest`
- 本地源码模式：`docker compose -f compose.yaml -f compose.rsshub-local.yaml up -d --build rsshub`
- 本地源码目录：`../services/RSSHub`
- 需要让仓库里的自定义路由或补丁真正生效时，再切到本地源码模式

`n8n` 容器内会额外挂载一个 `/vault` 目录，对应本地 `vault/`，后续工作流直接往这里写 Markdown。

当前主干只把 `qdrant` 作为 n8n 的直接依赖。`memos` 会继续部署，但不再作为主干编排器的启动前置条件。

## Obsidian 主库约定

- 默认 Vault 路径：`./vault`
- 容器内挂载路径：`/vault`
- 信息流收件箱：`/vault/00_Inbox/AI_Information_Processor`
- Daily Notes：`/vault/10_Daily`

如果你已有自己的 Obsidian Vault，把 `.env` 里的 `OBSIDIAN_VAULT_PATH` 改成现有 Vault 的绝对路径即可。

## 当前已实现的工作流

已在仓库里生成这些工作流模板：

- `deploy/n8n/workflows/01_rss_to_obsidian_raw.json`
- `deploy/n8n/workflows/05_common_vault_writer.json`
- `deploy/n8n/workflows/06_manual_media_submit.json`

当前主干做的是：

- 读取 `.env` 中的 `RSS_SOURCE_URLS_JSON`
- 拉取 RSS 条目
- 清洗正文和元数据
- 文本项直接进入共享主链 `00 -> 01a -> 03 -> 02 -> 04a -> 05`
- 播客 / 音频项先走 `04` transcript adapter，再进入共享主链 `00 -> 01a -> 03 -> 02 -> 04a -> 05`
- `03` 只做 Qdrant search / dedupe 判定并返回 deferred upsert payload
- 最后统一交给 `05_common_vault_writer` 生成 Markdown + frontmatter，先写入 Obsidian Inbox，再执行 Qdrant upsert

如果 `RSS_SOURCE_URLS_JSON` 为空，工作流会回退到一个默认的 `42章经` 播客 RSS 做演示。

`05_common_vault_writer.json` 是共享 Vault 写入子流程。`01` 和 `06` 现在都统一调用它；`04_video_transcript_ingest` 继续保持 adapter-only，只返回可交给 `00` 的 transcript ingress payload，不直接写 Vault。

`06_manual_media_submit.json` 是本地手动媒体入口，只接 `YouTube / 播客 / 其他音视频 URL`，然后先走 `04` transcript adapter，再显式进入共享主链 `00 -> 01a -> 03 -> 02 -> 04a -> 05`；它不处理文章正文或通用手动笔记。默认本地 webhook 为：

```text
POST http://localhost:5678/webhook/aip/local/manual-media-submit
```

如果你是用仓库里的 JSON 直接同步到 live SQLite，再重启 `n8n`，实际可调用的 webhook 路径要以 `deploy/data/n8n/database.sqlite` 里的 `webhook_entity.webhookPath` 为准。

## 飞书机器人单独启用

先在 `.env` 中补齐这 3 个值：

- `IM2MEMO_MEMOS_TOKEN`
- `FEISHU_APP_ID`
- `FEISHU_APP_SECRET`

然后执行：

```powershell
docker compose --profile feishu up -d im2memo
```

如果拉取 `im2memo` 时看到 `denied`，说明当前公开 GHCR 镜像不可直接拉取。这时保留现有环境变量不动，后续改成你自己构建出来的本地镜像标签，再覆盖 `.env` 里的 `IM2MEMO_IMAGE` 即可。

## Video Transcript API 以可选 profile 接入

更新：当前生效的接入方式如下。

- 源码已经内嵌到 `services/VideoTranscriptAPI`
- 配置目录使用 `services/VideoTranscriptAPI/config`
- 运行数据使用 `deploy/data/video-transcript-api`
- `docker compose --profile transcript up -d video-transcript-api` 会直接 build 仓内源码
- `n8n` 容器内访问地址默认写成 `http://video-transcript-api:8000`
- 本地浏览器访问地址仍然是 `http://localhost:8000`
- `VideoTranscriptAPI` 仍然通过 HTTP 作为独立适配层接入主干，不把它的业务逻辑重写进 `n8n` code node

这个服务仍然应作为独立仓维护，只通过 HTTP 接进当前主干，不要把它的业务逻辑重写进 n8n code node。

如果你已经在独立仓里构建或拉取了镜像：

1. 在 `.env` 里覆盖 `VIDEO_TRANSCRIPT_IMAGE`
2. 把 `VIDEO_TRANSCRIPT_BASE_URL` 指向该服务在 Docker 网络中的实际地址
3. 再执行：

```powershell
docker compose --profile transcript up -d video-transcript-api
```

注意：

- 当前仓库只负责 profile 骨架，不内嵌该独立服务的专用配置文件。
- 时区要和本仓库的 `TZ` 保持一致。
- n8n 容器内访问该服务时，必须使用容器地址，不要写 `localhost`。

## 需要动态渲染路由时再启用 browserless

有些 RSSHub 路由依赖浏览器渲染，这时把 `.env` 里的 `RSSHUB_PUPPETEER_WS_ENDPOINT` 改成：

```text
ws://browserless:3000
```

然后执行：

```powershell
docker compose --profile headless up -d browserless rsshub
```

当前已经验证：

- `小宇宙播客` 路由可直接使用
- `B站 UP 主动态` 路由可用，例如 `http://rsshub:1200/bilibili/user/dynamic/946974`
- `B站 UP 主视频列表` 路由在当前 RSSHub 版本下会命中 B 站 `412 Precondition Failed`，暂时不要把它当主力源

## 现在就需要你补的内容

- `LLM_PROVIDER` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_API_KEY`: 用于 `02_enrich_with_llm` 的摘要和打分；切 provider 前先看 `deploy/LLM_PROVIDER_PLAYBOOK.md`
- `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL`: 用于向量去重
  `EMBEDDING_MODEL` 和 `QDRANT_VECTOR_SIZE` 要成对调整，避免 collection 维度错配
- `EMBEDDING_INPUT_MAX_CHARS`: 控制 `01a_rule_prefilter` 生成的 `event_fingerprint_text` 上限，默认 `6000`；不再表示“直接截断正文前 6000 字符”
- `QDRANT_DIFF_THRESHOLD` / `QDRANT_SILENT_THRESHOLD`: 控制 `full_push -> diff_push -> silent` 的分界值，默认分别为 `0.85 / 0.97`
- `VIDEO_TRANSCRIPT_BASE_URL` / `VIDEO_TRANSCRIPT_API_KEY`: 用于音视频转文本
- `FEISHU_WEBHOOK_URL`: 用于 n8n 最终推送飞书

## LLM Provider 切换

如果以后要把 `deepseek` 换成别的 OpenAI-compatible provider，不要再从 workflow 和 transcript 代码反推。直接看：

- `deploy/LLM_PROVIDER_PLAYBOOK.md`

这份手册已经把下面几个问题集中写清楚：

- 主链 `02_enrich_with_llm` 和 `VideoTranscriptAPI` 各自改哪里
- 为什么两边的 `base_url` 语义不一样
- embedding 为什么是另一条线
- 新 provider 的标准变更顺序和验证顺序

## 关键约定

- 在 n8n 容器内部访问其他服务时，优先使用容器名，而不是 `localhost`
- RSSHub 地址用 `http://rsshub:1200`
- Qdrant 地址用 `http://qdrant:6333`
- Memos 地址用 `http://memos:5230`
- Obsidian Vault 地址用 `/vault`

## 建议顺序

1. 先初始化 Obsidian Vault 和 Memos 管理员账号。
2. 先做第一条主干：`RSS/YouTube/播客 -> AI 打分 -> Markdown 写入 Obsidian`。
3. 再补 `飞书/企业微信推送`。
4. 当前 repo 已收口成一条共享主链 `00 -> 01a -> 03 -> 02 -> 04a -> 05`；`01` 直接喂这条主链，`06` 先经过 `04` transcript adapter 再接入。`03` 负责 search/decide，`05` 负责 write-then-upsert，避免索引先于主库提交。
5. 再接入 `im2memo -> Memos -> memo auto` 这条增强支路。
6. 最后补 `每日复盘` 和 `订阅管理 Web 端` 等外围能力。
## 同步工作流到运行态

仓库里的 `deploy/n8n/workflows/*.json` 是版本控制下的主定义，`deploy/data/n8n/database.sqlite` 只是运行态缓存。
在导入、更新或串联工作流后，使用下面的命令把仓库版本同步到当前 n8n 主库：

```powershell
python deploy/n8n/scripts/publish_runtime.py
```

`publish_runtime.py` 现在是对外唯一发布入口。它会依次执行 `sync_workflows.py -> restart n8n -> check_runtime_alignment.py`，并把整次过程追加到仓库根目录 `DEBUG_LOG.md`。

如果只想发布某几条工作流，可以重复传 `--workflow-id`：

```powershell
python deploy/n8n/scripts/publish_runtime.py `
  --workflow-id D3a7Kp9Lm4Qx2Rst `
  --workflow-id 828e50ae98c24f31
```

如果需要把验证也串进同一次发布，可额外开启：

```powershell
python deploy/n8n/scripts/publish_runtime.py --run-smoke-qdrant
python deploy/n8n/scripts/publish_runtime.py --run-verify-transcript
```

`sync_workflows.py` 仍然保留，但它现在的定位是唯一的 SQLite 同步步骤，不再作为日常发布入口。

这个发布链路会：
- 先对当前活动 SQLite 库做一次备份
- 用 repo JSON 更新 `workflow_entity`
- 确保当前 `versionId` 在 `workflow_history` 中存在
- 对 `active: true` 的工作流补齐 `activeVersionId`
- 重启 `n8n`，刷新 webhook 等 runtime 衍生态
- 用 `check_runtime_alignment.py` 回读 live SQLite，确认 repo JSON 和 runtime 没有再次分裂

这一步是 `01 -> 02 -> 03` 链路稳定运行的前提，因为 `Execute Workflow` 调子工作流时不会只看 `active` 标志，还会检查当前激活版本是否真的存在于版本历史中。

## 契约校验

`NormalizedTextObject` 现在不再只靠文档和 Code Node 约定。仓库根目录新增了：

- `contracts/normalized_text_object.schema.json`
- `contracts/examples/rss.normalized.json`
- `contracts/examples/transcript.normalized.json`
- `contracts/examples/manual.normalized.json`
- `contracts/llm_score.schema.json`
- `contracts/dedupe_decision.schema.json`
- `contracts/action_policy_decision.schema.json`
- `contracts/writer_result.schema.json`
- `contracts/validate_contract.py`

其中 `*.normalized.json` 只表示 Stage 0 / ingress 基线对象；LLM 打分、去重决策、动作决策、写入结果应分别走自己的 contract，而不是继续塞回 `NormalizedTextObject`。

运行方式：

```powershell
python contracts/validate_contract.py
python deploy/n8n/scripts/validate_workflow_boundaries.py
```

这层契约的 canonical 字段已经收口为 `obsidianInboxDir / content_text / content_html / dedupe_action`。像 `obsidian_inbox_dir / raw_text / raw_html / transcript_text / calibrated_transcript / action` 这类字段只允许停留在入口适配阶段，不能泄漏到 `00` 之后的主干对象里。

硬规则如下：

- 只有 ingress adapter 和 `00_common_normalize_text_object` 可以接触历史字段
- `00` 之后，任何 workflow 都不允许继续新增或依赖 `raw_text / raw_html / transcript_text / calibrated_transcript / obsidian_inbox_dir / action`
- `01_rss_to_obsidian_raw` 的 transcript 分支必须先回到 `00 Common Normalize Text Object`，不能再从 `04` 直接跳到 `05`
- `05_common_vault_writer` 仍保留 `obsidian_inbox_dir` fallback，但它只是兼容层；如果同时收到 `obsidianInboxDir` 和 `obsidian_inbox_dir` 且两者不一致，会直接报错，要求先经过 `00` 规范化

发布后建议再跑一次：

```powershell
python deploy/n8n/scripts/smoke_qdrant_gate.py
```

这个 smoke 脚本会：
- 直接检查 `EMBEDDING_*` 是否已配置
- 核对 `QDRANT_COLLECTION` 是否存在，以及实际维度是否等于 `QDRANT_VECTOR_SIZE`
- 用合成向量验证 `full_push`、`diff_push`、`silent` 三种动作，以及“同一 `item_id` 内容更新”不会被误吞

根目录 `DEBUG_LOG.md` 是总调试日志。后续 `publish / sync / smoke / verify / alignment check` 都会默认往这里追加。

仓库根目录已经提供 `.pre-commit-config.yaml`，把这两层守门接到了本地提交前：

```powershell
python -m pip install --user pre-commit
pre-commit install
pre-commit run --all-files
```

- `AIP contract guard` 会在改动 `contracts/` 或 `deploy/n8n/workflows/` 时运行 `python contracts/validate_contract.py`
- `AIP contract guard` 还会继续运行 `python deploy/n8n/scripts/validate_workflow_boundaries.py`，检查历史字段边界和共享主链连接关系
- `AIP qdrant smoke guard` 会在改动 workflow/runtime 相关文件时运行 `python deploy/n8n/scripts/smoke_qdrant_gate.py --no-debug-log`
- 如需紧急跳过本地 smoke，可临时设置 `AIP_SKIP_SMOKE=1`，但这只应该用于与 runtime 无关的例外场景
## Transcript Debug First

如果是 transcript / `04_video_transcript_ingest` / `VideoTranscriptAPI` 排障，先读 `deploy/TRANSCRIPT_RUNTIME_INVARIANTS.md`，不要直接开始猜服务边界。

- `CapsWriter` 是宿主机本地服务，`VideoTranscriptAPI` 访问它使用 `ws://host.docker.internal:6016`
- `FunASR` 是 Docker 内服务，`VideoTranscriptAPI` 访问它使用 `ws://funasr-spk-server:8767`

先区分这两个运行边界，再继续排障。
