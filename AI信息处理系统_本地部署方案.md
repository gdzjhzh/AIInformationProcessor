# AI 信息处理系统：Windows 本地完整部署方案

> 基于 Docker 容器化技术，Local First 理念，适配无公网服务器的普通用户。
>
> 执行层面请以 [AI信息处理系统_架构校正版.md](C:\code\AIInformationProcessor\AI信息处理系统_架构校正版.md) 为准。当前仓库已经从 `Memos 中心化` 校正为 `Obsidian 主库` 架构，本文件保留作为原始方案参考。

---

## 整体架构概览

```
信息采集层（RSS源生成）
    ↓
处理系统层（AI打分 + 三级降噪去重）
    ↓
存储与增强层（Memos + im2memo飞书机器人 + memo auto）
    ↓
知识总基地（Obsidian 本地同步）
```

回顾分析层不是上面这条主干流水线中的串行下一站，而是读取 `Obsidian` 中已经沉淀的内容，再结合 `ManicTime` 等行为记录生成复盘结果，最后回写到 `Obsidian` 的反馈回路。更准确的理解是：

```text
主干：
信息采集层
    ↓
处理系统层
    ↓
存储与增强层
    ↓
知识总基地（Obsidian）

回路：
回顾分析层（ManicTime + 每日复盘）
    ↓
输出复盘内容到 Obsidian
```

所有服务运行在本地 Docker 容器中，数据完全存储在本机硬盘，关机期间系统暂停，开机后自动补跑积压内容。

---

## 第一步：准备工作

### 1.1 安装 Docker Desktop

前往 [https://www.docker.com/products/docker-desktop](https://www.docker.com/products/docker-desktop) 下载 Windows 版本并安装。安装完成后启动 Docker Desktop，确保右下角图标显示为绿色运行状态。

### 1.2 准备 API Key 和账号

在开始部署前，提前准备好以下内容：

- **大模型 API Key**：推荐使用 DeepSeek（价格最低，处理几十篇文章每天约几毛钱）。前往 [https://platform.deepseek.com](https://platform.deepssek.com) 注册并获取 API Key。
- **飞书机器人 Webhook**：在飞书群里添加「自定义机器人」，拿到 Webhook 地址（用于最终推送内容）。
- **飞书开放平台凭证**：前往 [https://open.feishu.cn](https://open.feishu.cn) 创建应用，获取 App ID 和 App Secret（用于 im2memo 飞书机器人接入）。

---

## 第二步：部署核心服务（Docker Compose）

在本地新建一个文件夹，例如 `D:\pkms-local`，在其中创建 `docker-compose.yml` 文件，内容如下：

```yaml
version: '3.8'

services:

  # 碎片笔记存储中心
  memos:
    image: neosmemo/memos:stable
    container_name: memos
    ports:
      - "5230:5230"
    volumes:
      - memos_data:/var/opt/memos
    restart: unless-stopped

  # 自动化工作流大脑
  n8n:
    image: docker.n8n.io/n8nio/n8n
    container_name: n8n
    ports:
      - "5678:5678"
    volumes:
      - n8n_data:/home/node/.n8n
    restart: unless-stopped

  # ⭐ 向量数据库（用于三级降噪去重，原方案遗漏）
  qdrant:
    image: qdrant/qdrant
    container_name: qdrant
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage
    restart: unless-stopped

  # RSS 源生成（B站、小宇宙等封闭平台）
  rsshub:
    image: diygod/rsshub
    container_name: rsshub
    ports:
      - "1200:1200"
    restart: unless-stopped

volumes:
  memos_data:
  n8n_data:
  qdrant_data:
```

> **为什么加 Qdrant？** 原方案漏掉了向量数据库。Embedding 计算完的向量必须持久化存储，否则重启后全部丢失，三级降噪就完全失效。Qdrant 专门解决这个问题，且支持近似最近邻搜索（ANN），即使历史笔记积累到 10 万条，查询速度依然和 100 条时一样快。

在 `D:\pkms-local` 文件夹中打开 PowerShell 或终端，运行：

```bash
docker compose up -d
```

启动完成后，通过浏览器访问：

- Memos：[http://localhost:5230](http://localhost:5230)（初始化账号）
- n8n：[http://localhost:5678](http://localhost:5678)（自动化工作流控制台）
- Qdrant：[http://localhost:6333/dashboard](http://localhost:6333/dashboard)（向量数据库）
- RSSHub：[http://localhost:1200](http://localhost:1200)（RSS 源生成）

---

## 第三步：配置信息采集层

### 3.1 常规 RSS 源（直接可用）

以下平台原生支持 RSS，在 n8n 里直接填入地址即可：

- **YouTube 频道**：格式为 `https://www.youtube.com/feeds/videos.xml?channel_id=频道ID`，无需第三方服务，最稳定。
- **播客（小宇宙 / Apple Podcast）**：泛用型播客本身就是 RSS 协议，直接复制订阅链接。
- **科技博客 / 新闻网站**：少数派、36氪、Hacker News 等直接搜索添加。

### 3.2 RSSHub 转换封闭平台

本地 RSSHub 启动后，参照官方路由文档（[https://docs.rsshub.app](https://docs.rsshub.app)）生成各平台的 RSS 地址。在 n8n 中使用时，地址格式为：

```
http://host.docker.internal:1200/bilibili/user/video/用户ID
http://host.docker.internal:1200/ximalaya/album/专辑ID
```

### 3.3 微信公众号（⚠️ 高风险，请认真评估）

**原方案建议使用 `ttttmr/wechat2rss` 镜像，但有重要风险需要说明：**

该方案需要将你的微信账号登录至容器内，本质上是用真实账号模拟爬取行为。微信对此类自动化操作有封号机制，且该镜像维护状态不稳定，随时可能因微信更新而失效。

**建议的应对策略：**

- 如果公众号对你不是核心信息源，暂时跳过这一步，先把其他信息源跑通。
- 如果公众号非常重要，使用专门注册的小号而非主账号来登录，降低封号影响。
- 持续关注该镜像的 GitHub Issues，做好随时切换方案的准备。

---

## 第四步：在 n8n 中配置三级降噪处理层

打开 [http://localhost:5678](http://localhost:5678)，创建新的 Workflow，这是整套系统的「大脑」。

### 4.1 工作流节点设计

```
定时触发（每2小时）
    ↓
RSS Read 节点（拉取各信息源新文章）
    ↓
Code 节点（调用 Embedding API，将文章转成向量）
    ↓
HTTP Request 节点（查询 Qdrant，找最相似的历史向量）
    ↓
Code 节点（判断相似度，执行三级降噪逻辑）
    ↓
    ├── < 0.85：全新事件 → AI打分+摘要 → 推送飞书
    ├── 0.85~0.97：增量更新 → 提取差异摘要 → 推送飞书
    └── > 0.97：完全重复 → 静默丢弃
    ↓
HTTP Request 节点（将新向量存入 Qdrant）
    ↓
HTTP Request 节点（将内容存入 Memos）
```

### 4.2 三级降噪的 JavaScript 逻辑（Code 节点）

```javascript
// 计算余弦相似度
function cosineSimilarity(vecA, vecB) {
  const dot = vecA.reduce((sum, a, i) => sum + a * vecB[i], 0);
  const normA = Math.sqrt(vecA.reduce((sum, a) => sum + a * a, 0));
  const normB = Math.sqrt(vecB.reduce((sum, b) => sum + b * b, 0));
  return dot / (normA * normB);
}

const newVector = $input.item.json.embedding;
const mostSimilar = $input.item.json.qdrant_result; // 从 Qdrant 查到的最近邻

if (!mostSimilar || mostSimilar.score < 0.85) {
  // 全新事件，完整推送
  return [{ json: { action: 'full_push', content: $input.item.json.content } }];
} else if (mostSimilar.score < 0.97) {
  // 增量更新，只推差异
  return [{ json: { action: 'diff_push', content: $input.item.json.content } }];
} else {
  // 完全重复，静默丢弃
  return [{ json: { action: 'silent' } }];
}
```

> **为什么不能只用 n8n 内存做相似度计算？** 随着历史内容积累，如果在 Code 节点里把所有向量都加载进内存比较，几个月后可能积累上万条记录，每次都全量比较会越来越慢。Qdrant 的 ANN 搜索专门解决这个性能问题，始终保持毫秒级响应。

### 4.3 AI 打分提示词（LLM 节点）

在触发全新推送时，调用 DeepSeek API 对文章进行结构化分析：

```
请对以下文章进行结构化分析，严格按 JSON 格式返回：
{
  "score": 0-3的整数（0=不值得看，1=一般，2=值得看，3=非常有价值）,
  "category": "文章分类（科技/商业/AI/效率工具等）",
  "summary": "核心观点，100字以内",
  "key_points": ["要点1", "要点2", "要点3"],
  "hidden_info": "隐藏信息或值得关注的细节（没有则留空）"
}

打分标准：
- 加分项：有深度分析、有数据支撑、有一手信息、访谈/对谈类内容
- 减分项：标题党、纯广告、纯转发、与上周已看内容高度重复

文章内容：
{{文章正文}}
```

---

## 第五步：部署飞书机器人（im2memo）

> **原方案推荐的 Memogram 仅支持 Telegram，不支持飞书。** 针对飞书用户，需使用原作者开源的 im2memo。

### 5.1 部署 im2memo

im2memo 开源地址：[https://github.com/zj1123581321/Im2Memo](https://github.com/zj1123581321/Im2Memo)

将以下内容追加到第二步的 `docker-compose.yml` 中：

```yaml
  im2memo:
    image: ghcr.io/zj1123581321/im2memo:latest
    container_name: im2memo
    ports:
      - "3000:3000"
    environment:
      - MEMOS_URL=http://memos:5230
      - MEMOS_TOKEN=你在Memos后台生成的API_Token
      - FEISHU_APP_ID=你的飞书App_ID
      - FEISHU_APP_SECRET=你的飞书App_Secret
    restart: unless-stopped
```

### 5.2 配置飞书机器人

1. 前往飞书开放平台（[https://open.feishu.cn](https://open.feishu.cn)）创建企业自建应用。
2. 开启「接收消息」权限。
3. 配置事件订阅，将 Webhook 地址指向：`http://你的内网IP:3000/feishu`。
4. 将机器人添加到你常用的飞书群或与自己的对话中。

### 5.3 使用方式

在飞书中把任意内容转发给机器人，即自动保存到 Memos。

转发后紧接着发送 `// 你的想法`，这条评论会自动合并到刚才那条笔记里，而不是创建新条目——这是纯收藏工具没有的核心功能。

---

## 第六步：配置笔记自动增强（memo auto）

每条新笔记存入 Memos 后，n8n 通过 Memos 的 Webhook 触发，自动对笔记进行增强处理。

在 n8n 中创建第二条 Workflow：

```
Memos Webhook 触发（新笔记创建）
    ↓
判断内容类型
    ├── 含 URL → 抓取网页全文 → AI 生成摘要 → 回填笔记
    ├── 含图片 → OCR 文字识别 → AI 理解图片内容 → 回填笔记
    └── 纯文本 → 直接进入下一步
    ↓
AI 自动打标签（调用标签注册表保持一致性）
    ↓
AI 多角度评论
    ├── 事实核查：数据是否准确？
    ├── 发散联想：这个观点联想到什么？
    └── 反方视角：站在反对立场，有什么漏洞？
    ↓
查询 Qdrant，找出相似历史笔记
    ↓
将相关笔记链接追加到当前笔记
```

---

## 第七步：Obsidian 本地沉淀

1. 前往 [https://obsidian.md](https://obsidian.md) 下载并安装 Obsidian。
2. 创建一个本地 Vault（知识库文件夹）。
3. 在插件市场搜索并安装 `obsidian-memos-sync`。
4. 在插件设置中填入：
   - API URL：`http://localhost:5230`
   - API Token：Memos 后台生成的 Token
5. 插件每天自动将 Memos 中的内容增量同步到当天的 Daily Note 中。

---

## 第八步：ManicTime 每日复盘

1. 前往 [https://www.manictime.com](https://www.manictime.com) 下载并安装 ManicTime。
2. 安装后无需任何配置，它会在后台静默记录所有应用使用时间和浏览网页记录。
3. 每晚复盘时，结合 ManicTime 的活动图表和当天同步到 Obsidian 的笔记内容，通过语音输入总结今天的工作与思考。

**为什么用语音输入？** 语音输入速度比打字快约 10 倍，更重要的是语音输入时思维是流动的，很多打字时不会写下来的想法，说着说着就自然冒出来了。

推荐工具：豆包输入法（目前超长音频识别准确率最高）。

---

## 完整 docker-compose.yml（汇总版）

```yaml
version: '3.8'

services:

  memos:
    image: neosmemo/memos:stable
    container_name: memos
    ports:
      - "5230:5230"
    volumes:
      - memos_data:/var/opt/memos
    restart: unless-stopped

  n8n:
    image: docker.n8n.io/n8nio/n8n
    container_name: n8n
    ports:
      - "5678:5678"
    volumes:
      - n8n_data:/home/node/.n8n
    restart: unless-stopped

  qdrant:
    image: qdrant/qdrant
    container_name: qdrant
    ports:
      - "6333:6333"
    volumes:
      - qdrant_data:/qdrant/storage
    restart: unless-stopped

  rsshub:
    image: diygod/rsshub
    container_name: rsshub
    ports:
      - "1200:1200"
    restart: unless-stopped

  im2memo:
    image: ghcr.io/zj1123581321/im2memo:latest
    container_name: im2memo
    ports:
      - "3000:3000"
    environment:
      - MEMOS_URL=http://memos:5230
      - MEMOS_TOKEN=替换为你的Token
      - FEISHU_APP_ID=替换为你的AppID
      - FEISHU_APP_SECRET=替换为你的AppSecret
    depends_on:
      - memos
    restart: unless-stopped

volumes:
  memos_data:
  n8n_data:
  qdrant_data:
```

---

## 问题修正汇总

| 原方案问题 | 修正方案 |
|---|---|
| docker-compose 缺少向量数据库，三级降噪无法持久化 | 新增 Qdrant 容器，向量数据持久存储到本地 |
| n8n 内存做相似度计算，长期使用会越来越慢 | 所有向量查询走 Qdrant ANN 搜索，性能恒定 |
| 推荐 Memogram 作为 im2memo 替代，不支持飞书 | 改用原作者开源的 im2memo，原生支持飞书 |
| Wechat2RSS 风险未充分说明 | 补充封号风险说明和降低风险的操作建议 |

---

## 建议的上手顺序

1. 先跑通 `docker compose up -d`，确认四个服务都能访问
2. 在 n8n 里搭第一条流水线：订阅 2-3 个 RSS 源 → 推送到飞书（暂不做 Embedding 去重）
3. 确认飞书能收到推送后，接入 im2memo 飞书机器人
4. 稳定运行一周后，再加入 Qdrant 向量去重
5. 最后配置 Obsidian 同步和 ManicTime 复盘

> 不要一次把所有东西全部上线。先跑通主干，再逐步加功能，遇到问题更容易定位。
