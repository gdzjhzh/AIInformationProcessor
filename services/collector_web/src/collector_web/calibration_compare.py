import json
import urllib.error
import urllib.request
from typing import Any

from .config import Settings


class CalibrationCompareError(RuntimeError):
    pass


def submit_calibration_compare(settings: Settings, url: str) -> dict[str, Any]:
    return _request_json(
        settings,
        settings.calibration_compare_api_base_url,
        method="POST",
        payload={"url": url},
    )


def get_calibration_compare_job(settings: Settings, job_id: str) -> dict[str, Any]:
    return _request_json(
        settings,
        f"{settings.calibration_compare_api_base_url}/{job_id}",
        method="GET",
    )


def publicize_calibration_compare_payload(
    settings: Settings,
    payload: dict[str, Any],
) -> dict[str, Any]:
    public_payload = dict(payload)
    job = dict(public_payload.get("job") or {})
    if job:
        job["directory_url"] = _public_url(settings, job.get("directory_url", ""))
        links = []
        for link in job.get("file_links") or []:
            item = dict(link)
            item["url"] = _public_url(settings, item.get("url", ""))
            links.append(item)
        job["file_links"] = links
        public_payload["job"] = job
    return public_payload


def _request_json(
    settings: Settings,
    url: str,
    *,
    method: str,
    payload: dict[str, Any] | None = None,
) -> dict[str, Any]:
    headers = {"Accept": "application/json"}
    data = None
    if payload is not None:
        headers["Content-Type"] = "application/json"
        data = json.dumps(payload).encode("utf-8")
    if settings.calibration_compare_api_key:
        headers["Authorization"] = f"Bearer {settings.calibration_compare_api_key}"

    request = urllib.request.Request(url, data=data, headers=headers, method=method)
    try:
        with urllib.request.urlopen(
            request,
            timeout=settings.calibration_compare_timeout_seconds,
        ) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        detail = _extract_error_detail(body) or body
        raise CalibrationCompareError(
            f"calibration compare API returned HTTP {exc.code}: {detail}"
        ) from exc
    except Exception as exc:  # pragma: no cover - runtime network failures
        raise CalibrationCompareError(f"calibration compare API request failed: {exc}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise CalibrationCompareError(
            f"calibration compare API returned non-JSON body: {body}"
        ) from exc

    if not isinstance(parsed, dict):
        raise CalibrationCompareError("calibration compare API returned non-object JSON")
    return parsed


def _extract_error_detail(body: str) -> str:
    try:
        parsed = json.loads(body)
    except json.JSONDecodeError:
        return ""
    detail = parsed.get("detail") if isinstance(parsed, dict) else None
    return str(detail) if detail else ""


def _public_url(settings: Settings, url: str) -> str:
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if not url.startswith("/"):
        url = f"/{url}"
    return f"{settings.calibration_compare_public_base_url}{url}"
