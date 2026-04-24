# LLM Provider Playbook

这份文档是 `AIInformationProcessor` 的大模型接入手册，目标是把“以后切换任意 LLM provider 时该改哪里、怎么验证、哪些地方不要混掉”一次写清楚，避免每次都重新读 workflow 和服务代码。

## 先记住 3 个面

当前仓库里，LLM 不是一个统一入口，而是 3 个相邻但独立的面：

| 面 | 作用 | 真相源 | 运行入口 | 备注 |
| --- | --- | --- | --- | --- |
| Enrichment LLM | `02_enrich_with_llm` 做打分、摘要、分类、标签 | `deploy/.env` | `deploy/compose.yaml` -> `n8n` env -> `deploy/n8n/workflows/02_enrich_with_llm.json` | 这是 Obsidian 主链上的评分/摘要模型 |
| Embedding model | `03_qdrant_gate` 做向量检索、近似去重 | `deploy/.env` | `deploy/compose.yaml` -> `n8n` env | 这不是聊天大模型，切换 LLM provider 时通常不用动 |
| Transcript LLM | `VideoTranscriptAPI` 做 transcript 校对和摘要 | `services/VideoTranscriptAPI/config/config.jsonc` | `video-transcript-api` 容器挂载配置后直接读取 | 这是独立服务，不吃 `deploy/.env` 里的 `LLM_*` |

以后只要先判断“你要切的是哪一个面”，基本就不会再从代码反推半天。

## 最容易踩坑的边界

### 1. `02_enrich_with_llm` 和 `VideoTranscriptAPI` 的 `base_url` 语义不一样

- `deploy/.env` 里的 `LLM_BASE_URL` 要填 provider 根路径
  例子：`https://api.deepseek.com/v1`、`https://ark.cn-beijing.volces.com/api/v3`
- 原因：`02_enrich_with_llm` 会自己拼 `${LLM_BASE_URL}/chat/completions`
- `services/VideoTranscriptAPI/config/config.jsonc` 里的 `llm.base_url` 要填完整聊天端点
  例子：`https://api.deepseek.com/chat/completions`、`https://ark.cn-beijing.volces.com/api/v3/chat/completions`
- 原因：`VideoTranscriptAPI` 代码是直接 `POST base_url`

这两个地方如果按同一种理解去填，通常会直接报 404 或 provider 兼容错误。

### 2. Embedding 和聊天 LLM 是两条线

- `LLM_*` 负责 `02_enrich_with_llm`
- `EMBEDDING_*` 负责 `03_qdrant_gate`
- 改聊天模型，不代表 embedding 也会一起切
- 改 embedding 时，要同时检查 `QDRANT_VECTOR_SIZE`

### 3. Transcript 服务有自己的 LLM 配置

`VideoTranscriptAPI` 不读取 `deploy/.env` 里的 `LLM_BASE_URL / LLM_MODEL / LLM_API_KEY`。  
它只读取：

- `services/VideoTranscriptAPI/config/config.jsonc`
  - `llm.api_key`
  - `llm.base_url`
  - `llm.calibrate_model`
  - `llm.summary_model`
  - `llm.json_output.mode_by_model`

## 推荐抽象法

不要把“切 provider”理解成到处搜 `deepseek` 再逐个替换。  
更稳的抽象方式是固定成下面这个清单：

### A. 先选接入面

1. 只切主链打分/摘要：改 `deploy/.env`
2. 只切 transcript 校对/摘要：改 `services/VideoTranscriptAPI/config/config.jsonc`
3. 两边都切：两个地方都改
4. 只切 embedding：改 `EMBEDDING_*`，不要碰 transcript 配置

### B. 对每个接入面都只关心 5 个值

| 字段 | 含义 | 例子 |
| --- | --- | --- |
| `provider` | 人类可读的 provider 标签，用于审计/日志/排查 | `deepseek` / `openai` / `openai-compatible` / `doubao-ark` |
| `base_url` | API 根路径或完整端点，取决于接入面 | 见上面的边界说明 |
| `api_key` | 鉴权密钥 | `sk-...` |
| `model` | 聊天模型名或 endpoint id | `deepseek-chat` / `gpt-4.1-mini` / `ep-xxxx` |
| `json_mode` | 结构化输出模式 | `json_object` / `json_schema` |

以后新增 provider 时，先把这 5 个值填出来，再做落地。

### C. 把“模型兼容性”收口到 `json_output.mode_by_model`

主链 `02_enrich_with_llm` 当前固定请求：

```json
{
  "response_format": {
    "type": "json_object"
  }
}
```

所以它对 provider 的要求相对简单，只要能兼容 OpenAI Chat Completions + `json_object` 即可。

`VideoTranscriptAPI` 则多了一层按模型名匹配输出模式：

- 有些模型适合 `json_object`
- 有些模型可以吃 `json_schema`
- 如果你使用的是 provider endpoint id，例如 `ep-*`
- 或者模型名不再带 `deepseek` / `qwen` / `glm`
- 那就要补 `llm.json_output.mode_by_model`

建议规则：

- 先保守：新 provider 先走 `json_object`
- 等确认稳定后，再评估要不要切到 `json_schema`

## 标准变更步骤

### 场景 1：只切 `02_enrich_with_llm`

改 `deploy/.env`：

```env
LLM_PROVIDER=doubao-ark
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_API_KEY=your-api-key
LLM_MODEL=ep-xxxxxxxxxxxxxxxx
```

然后重启 `n8n`：

```powershell
docker compose -f deploy/compose.yaml up -d --no-deps n8n
```

如果你同时改了 workflow JSON，再发布 runtime：

```powershell
python deploy/n8n/scripts/publish_runtime.py --workflow-id 828e50ae98c24f31
```

### 场景 2：只切 `VideoTranscriptAPI`

改 `services/VideoTranscriptAPI/config/config.jsonc`：

```json
"llm": {
  "api_key": "your-api-key",
  "base_url": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
  "calibrate_model": "ep-xxxxxxxxxxxxxxxx",
  "summary_model": "ep-xxxxxxxxxxxxxxxx",
  "json_output": {
    "mode_by_model": {
      "deepseek*": "json_object",
      "ep-*": "json_object",
      "*": "json_schema"
    },
    "max_retries": 2,
    "enable_fallback": true
  }
}
```

然后重启 transcript 服务：

```powershell
docker compose -f deploy/compose.yaml up -d --no-deps video-transcript-api
```

### 场景 3：两边都切

按上面两段一起改，然后分别重启：

```powershell
docker compose -f deploy/compose.yaml up -d --no-deps n8n
docker compose -f deploy/compose.yaml up -d --no-deps video-transcript-api
```

## 推荐验证顺序

不要只看“服务启动了没”，要按链路验证。

### A. 主链 `02_enrich_with_llm`

看这几个点：

1. `deploy/.env` 是否已经改到目标 provider
2. `deploy/compose.yaml` 是否把 `LLM_*` 传进了 `n8n`
3. `deploy/n8n/workflows/02_enrich_with_llm.json` 是否仍然按 Chat Completions 构造请求
4. 如果 workflow JSON 有变更，是否已经执行过 `publish_runtime.py`
5. live runtime 是否对齐 `deploy/data/n8n/database.sqlite`

### B. Transcript LLM

看这几个点：

1. `services/VideoTranscriptAPI/config/config.jsonc` 是否是目标 provider
2. `deploy/compose.yaml` 是否仍然把 `../services/VideoTranscriptAPI/config` 挂到容器
3. 新模型名是否匹配 `json_output.mode_by_model`
4. `/health` 是否健康
5. 实际 transcript 调用是否能返回合法 JSON

## Provider 适配模板

### 1. DeepSeek

主链：

```env
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-chat
```

Transcript：

```json
"base_url": "https://api.deepseek.com/chat/completions",
"calibrate_model": "deepseek-chat",
"summary_model": "deepseek-chat"
```

### 2. 豆包 / 火山方舟

主链：

```env
LLM_PROVIDER=doubao-ark
LLM_BASE_URL=https://ark.cn-beijing.volces.com/api/v3
LLM_MODEL=ep-xxxxxxxxxxxxxxxx
```

Transcript：

```json
"base_url": "https://ark.cn-beijing.volces.com/api/v3/chat/completions",
"calibrate_model": "ep-xxxxxxxxxxxxxxxx",
"summary_model": "ep-xxxxxxxxxxxxxxxx"
```

额外注意：

- transcript 侧建议给 `ep-*` 配 `json_object`
- 生产环境优先使用 endpoint id，而不是随手写一个模型别名

### 3. OpenAI-compatible 自建或代理服务

主链：

```env
LLM_PROVIDER=openai-compatible
LLM_BASE_URL=https://your-provider.example.com/v1
LLM_MODEL=your-model-name
```

Transcript：

```json
"base_url": "https://your-provider.example.com/v1/chat/completions",
"calibrate_model": "your-model-name",
"summary_model": "your-model-name"
```

额外注意：

- 先确认返回结构里是否有 `choices[0].message.content`
- 当前仓库没有切到 `Responses API`

## 不建议现在抽象成代码的部分

短期内不建议把所有 provider 再包一层“统一 LLM SDK”，原因很简单：

- 主链和 transcript 服务已经是两个运行边界
- 一个在 n8n workflow 里，一个在独立 Python 服务里
- 现在真正缺的是接入手册和清晰边界，不是再加一层运行时抽象

所以当前更合适的做法是：

1. 固定配置入口
2. 固定变更步骤
3. 固定验证顺序
4. 把 provider 差异收口到文档和 `mode_by_model`

这样成本最低，也最不容易引入新故障。

## 以后新增 provider 时，只做这 7 件事

1. 先决定改主链、transcript，还是两边都改
2. 填 `provider / base_url / api_key / model / json_mode`
3. 确认 `base_url` 是“根路径”还是“完整端点”
4. 如有需要，补 `json_output.mode_by_model`
5. 重启对应服务
6. 如改了 workflow JSON，用 `publish_runtime.py` 发布
7. 用真实链路做一次最小验证，不要只看容器是否启动

## 对应文件索引

- 主链 LLM 环境变量模板：`deploy/.env.example`
- 主链容器注入：`deploy/compose.yaml`
- 主链 workflow：`deploy/n8n/workflows/02_enrich_with_llm.json`
- Transcript 示例配置：`services/VideoTranscriptAPI/config/config.example.jsonc`
- Transcript live 配置：`services/VideoTranscriptAPI/config/config.jsonc`
- Transcript LLM 实现：`services/VideoTranscriptAPI/src/video_transcript_api/llm/llm.py`

