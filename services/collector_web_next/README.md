# Collector Web Next

Next.js read-only frontend experiment for `collector_web`.

This app is intentionally separate from `services/collector_web`. It renders a modern React/Tailwind interface and reads existing FastAPI endpoints, but it does not submit media, rerun RSS, switch models, write `deploy/.env`, or restart containers.

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

By default, the frontend reads the current Docker Compose host port used by this repo:

```text
http://127.0.0.1:18300
```

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
