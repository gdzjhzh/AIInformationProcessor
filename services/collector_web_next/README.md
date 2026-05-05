# Collector Web Next

Next.js read-only frontend experiment for `collector_web`.

This app is intentionally separate from `services/collector_web`. It renders a modern React/Tailwind interface and reads existing FastAPI endpoints, but it does not submit media, rerun RSS, switch models, write `deploy/.env`, or restart containers.

## Development

Start the existing FastAPI service if you want live data:

```powershell
docker compose -f deploy/compose.yaml up -d collector-web
```

Then start this Next.js frontend:

```powershell
cd services/collector_web_next
npm run dev
```

Open:

```text
http://127.0.0.1:3000
```

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
