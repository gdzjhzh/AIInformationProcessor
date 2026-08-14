# Collector Web Next

Next.js **只读实验面板**，不是日常写操作入口。

它单独渲染现有 FastAPI 的只读数据：不提交媒体、不重跑 RSS、不切模型、不写 `deploy/.env`、不重启容器。日常提交、重跑和模型切换仍走 `collector-web` 的 Jinja 控制台。本机浏览器看 FastAPI 用 `http://127.0.0.1:18300`；容器内地址是 `http://collector-web:8300`。

## Development

Start the existing FastAPI service if you want live data:

```powershell
docker compose -f deploy/compose.yaml up -d collector-web
```

For local development, start this Next.js frontend:

```powershell
cd services/collector_web_next
npm run dev
```

Open:

```text
http://127.0.0.1:3000
```

## Docker Compose

The production-style Compose service runs beside the existing FastAPI service:

```powershell
docker compose -f deploy/compose.yaml up -d --build collector-web-next
```

Open:

```text
http://127.0.0.1:18310
```

Inside Docker, `collector-web-next` reads the existing FastAPI service through:

```text
COLLECTOR_WEB_API_BASE_URL=http://collector-web:8300
```

This keeps `collector-web-next` read-only while `collector-web` remains the API/control-plane service. The intended migration path is to move UI surface area into `collector-web-next` first, then retire or narrow the old Jinja UI once the Next app covers the operational workflows.

By default, the frontend reads the FastAPI host port used by this repo:

```text
http://127.0.0.1:18300
```

容器内 Next 读 `http://collector-web:8300`。本机 `npm run dev` 默认打宿主机映射口 `18300`。

Override it with:

```powershell
$env:COLLECTOR_WEB_API_BASE_URL="http://127.0.0.1:18300"
npm run dev
```

## Routes

- `/` dashboard overview
- `/status` service status read-only view
- `/rss-poll` RSS poll audit read-only view
- `/manual-submit` manual submission read-only view
