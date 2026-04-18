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
- `Obsidian Vault` 本地目录挂载到 `n8n:/vault`

## 仍待补齐的模块

- `Video Transcript API`
- `rss2im`
- `手动提交`
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

`n8n` 容器内会额外挂载一个 `/vault` 目录，对应本地 `vault/`，后续工作流直接往这里写 Markdown。

当前主干只把 `qdrant` 作为 n8n 的直接依赖。`memos` 会继续部署，但不再作为主干编排器的启动前置条件。

## Obsidian 主库约定

- 默认 Vault 路径：`./vault`
- 容器内挂载路径：`/vault`
- 信息流收件箱：`/vault/00_Inbox/AI_Information_Processor`
- Daily Notes：`/vault/10_Daily`

如果你已有自己的 Obsidian Vault，把 `.env` 里的 `OBSIDIAN_VAULT_PATH` 改成现有 Vault 的绝对路径即可。

## 第一条已实现的工作流

已在仓库里生成首条工作流模板：

- `deploy/n8n/workflows/01_rss_to_obsidian_raw.json`

这条工作流做的是：

- 读取 `.env` 中的 `RSS_SOURCE_URLS_JSON`
- 拉取 RSS 条目
- 清洗正文和元数据
- 生成 Markdown + frontmatter
- 写入 Obsidian Inbox

如果 `RSS_SOURCE_URLS_JSON` 为空，工作流会回退到一个默认的 `42章经` 播客 RSS 做演示。

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

- `LLM_API_KEY`: 用于摘要和打分
- `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL`: 用于向量去重
  `EMBEDDING_MODEL` 和 `QDRANT_VECTOR_SIZE` 要成对调整，避免 collection 维度错配
- `VIDEO_TRANSCRIPT_BASE_URL` / `VIDEO_TRANSCRIPT_API_KEY`: 用于音视频转文本
- `FEISHU_WEBHOOK_URL`: 用于 n8n 最终推送飞书

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
4. 确认主干稳定后，再接入 `Embedding + Qdrant` 做三级降噪。
5. 再接入 `im2memo -> Memos -> memo auto` 这条增强支路。
6. 最后补 `Video Transcript API`、`手动提交`、`每日复盘` 和 `订阅管理 Web 端`。
## 同步工作流到运行态

仓库里的 `deploy/n8n/workflows/*.json` 是版本控制下的主定义，`deploy/data/n8n/database.sqlite` 只是运行态缓存。
在导入、更新或串联工作流后，使用下面的命令把仓库版本同步到当前 n8n 主库：

```powershell
python deploy/n8n/scripts/sync_workflows.py
```

如果只想同步某几条工作流，可以重复传 `--workflow-id`：

```powershell
python deploy/n8n/scripts/sync_workflows.py `
  --workflow-id D3a7Kp9Lm4Qx2Rst `
  --workflow-id 828e50ae98c24f31
```

这个脚本会：
- 先对当前活动 SQLite 库做一次备份
- 用 repo JSON 更新 `workflow_entity`
- 确保当前 `versionId` 在 `workflow_history` 中存在
- 对 `active: true` 的工作流补齐 `activeVersionId`

这一步是 `01 -> 02` 链路稳定运行的前提，因为 `Execute Workflow` 调子工作流时不会只看 `active` 标志，还会检查当前激活版本是否真的存在于版本历史中。
