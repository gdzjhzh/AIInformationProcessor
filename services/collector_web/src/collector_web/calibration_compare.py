import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path, PurePosixPath
from typing import Any

from .config import Settings


class CalibrationCompareError(RuntimeError):
    pass


def submit_calibration_compare(
    settings: Settings,
    url: str,
    *,
    enable_thinking: bool = False,
) -> dict[str, Any]:
    return _request_json(
        settings,
        settings.calibration_compare_api_base_url,
        method="POST",
        payload={"url": url, "enable_thinking": enable_thinking},
    )


def get_calibration_compare_job(settings: Settings, job_id: str) -> dict[str, Any]:
    return _request_json(
        settings,
        f"{settings.calibration_compare_api_base_url}/{job_id}",
        method="GET",
    )


def open_calibration_compare_directory(settings: Settings, job_id: str) -> dict[str, Any]:
    payload = get_calibration_compare_job(settings, job_id)
    job = payload.get("job") if isinstance(payload, dict) else None
    if not isinstance(job, dict):
        raise CalibrationCompareError("calibration compare API did not return a job")

    directory = _resolve_local_output_dir(settings, str(job.get("output_dir") or ""))
    _open_directory(directory)
    return {
        "ok": True,
        "job_id": job.get("job_id") or job_id,
        "path": str(directory),
    }


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


def _resolve_local_output_dir(settings: Settings, output_dir: str) -> Path:
    raw_output_dir = output_dir.strip()
    if not raw_output_dir:
        raise CalibrationCompareError("model compare output directory is not ready yet")

    local_root = settings.calibration_compare_local_output_dir.resolve()
    direct_path = Path(raw_output_dir)
    if direct_path.exists():
        candidate = direct_path.resolve()
    else:
        relative_path = _container_relative_path(
            raw_output_dir,
            settings.calibration_compare_container_output_dir,
        )
        if relative_path is None:
            raise CalibrationCompareError(
                f"cannot map model compare output directory to a local path: {raw_output_dir}"
            )
        candidate = (local_root / relative_path).resolve()

    try:
        candidate.relative_to(local_root)
    except ValueError as exc:
        raise CalibrationCompareError(
            f"refusing to open directory outside model compare output root: {candidate}"
        ) from exc

    if not candidate.exists():
        raise CalibrationCompareError(f"model compare output directory does not exist: {candidate}")
    if not candidate.is_dir():
        raise CalibrationCompareError(f"model compare output path is not a directory: {candidate}")
    return candidate


def _container_relative_path(output_dir: str, container_root: Path) -> Path | None:
    normalized_output = output_dir.replace("\\", "/")
    normalized_root = str(container_root).replace("\\", "/")
    try:
        relative = PurePosixPath(normalized_output).relative_to(PurePosixPath(normalized_root))
    except ValueError:
        return None
    return Path(*relative.parts)


def _open_directory(path: Path) -> None:
    if os.name == "nt":
        os.startfile(str(path))  # type: ignore[attr-defined]
        return

    opener = "open" if sys.platform == "darwin" else "xdg-open"
    try:
        subprocess.Popen(
            [opener, str(path)],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
    except FileNotFoundError as exc:
        raise CalibrationCompareError(f"local directory opener is not available: {opener}") from exc


def _public_url(settings: Settings, url: str) -> str:
    if not url:
        return ""
    if url.startswith("http://") or url.startswith("https://"):
        return url
    if not url.startswith("/"):
        url = f"/{url}"
    return f"{settings.calibration_compare_public_base_url}{url}"
