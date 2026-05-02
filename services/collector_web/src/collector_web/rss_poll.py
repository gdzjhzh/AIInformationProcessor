import json
import urllib.error
import urllib.request
from typing import Any

from .config import Settings


class RssPollRerunError(RuntimeError):
    pass


def trigger_rss_poll_rerun(settings: Settings) -> dict[str, Any]:
    request = urllib.request.Request(
        settings.rss_poll_rerun_url,
        data=json.dumps({"source": "collector_web"}).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=settings.rss_poll_rerun_timeout_seconds,
        ) as response:
            status_code = response.status
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RssPollRerunError(
            f"RSS poll rerun webhook returned HTTP {exc.code}: {body}"
        ) from exc
    except Exception as exc:  # pragma: no cover - network/runtime failures
        raise RssPollRerunError(f"RSS poll rerun webhook request failed: {exc}") from exc

    parsed: dict[str, Any] = {}
    if body.strip():
        try:
            candidate = json.loads(body)
        except json.JSONDecodeError:
            candidate = {"body": body}
        if isinstance(candidate, dict):
            parsed = candidate
        else:
            parsed = {"body": candidate}

    return {
        "ok": True,
        "accepted": parsed.get("accepted", True),
        "status_code": status_code,
        "webhook_url": settings.rss_poll_rerun_url,
        "response": parsed,
    }
