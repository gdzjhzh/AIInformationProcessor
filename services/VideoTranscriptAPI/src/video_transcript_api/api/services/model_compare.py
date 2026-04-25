from __future__ import annotations

import copy
import json
import os
import re
import threading
import uuid
from dataclasses import dataclass, replace
from datetime import datetime
from pathlib import Path
from typing import Any

from ..context import get_logger
from ...downloaders import create_downloader
from ...llm import LLMCoordinator
from ...transcriber import FunASRSpeakerClient

logger = get_logger()

DEFAULT_REQUIRED_MODEL_KEYS = ("deepseek", "doubao")
ENV_MODEL_PREFIXES = {
    "deepseek": "MODEL_COMPARE_DEEPSEEK",
    "doubao": "MODEL_COMPARE_DOUBAO",
}

_jobs: dict[str, dict[str, Any]] = {}
_jobs_lock = threading.RLock()


class ModelCompareConfigError(RuntimeError):
    pass


@dataclass(frozen=True)
class ModelCandidate:
    key: str
    label: str
    model: str
    base_url: str
    api_key: str
    reasoning_effort: str | None = None
    thinking_type: str | None = None
    max_retries: int | None = None
    retry_delay: int | None = None

    def public_dict(self) -> dict[str, str]:
        data = {
            "key": self.key,
            "label": self.label,
            "model": self.model,
        }
        if self.reasoning_effort:
            data["reasoning_effort"] = self.reasoning_effort
        if self.thinking_type:
            data["thinking_type"] = self.thinking_type
        return data


def submit_model_compare_job(
    url: str,
    config: dict[str, Any],
    *,
    enable_thinking: bool = False,
) -> dict[str, Any]:
    normalized_url = (url or "").strip()
    if not normalized_url:
        raise ValueError("url is required")

    candidates = get_required_model_candidates(config, enable_thinking=enable_thinking)
    job_id = uuid.uuid4().hex
    now = _now_iso()
    job = {
        "job_id": job_id,
        "url": normalized_url,
        "status": "queued",
        "status_label": "已排队",
        "stage": "queued",
        "message": "已创建校对对比任务",
        "created_at": now,
        "updated_at": now,
        "models": [candidate.public_dict() for candidate in candidates],
        "enable_thinking": enable_thinking,
        "output_dir": "",
        "directory_url": f"/model-compare/{job_id}",
        "file_links": [],
        "errors": [],
    }
    _set_job(job_id, job)

    worker = threading.Thread(
        target=_run_model_compare_job,
        args=(job_id, normalized_url, candidates, config, enable_thinking),
        daemon=True,
        name=f"model-compare-{job_id[:8]}",
    )
    worker.start()
    return get_model_compare_job(job_id) or job


def get_model_compare_job(job_id: str) -> dict[str, Any] | None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        return copy.deepcopy(job) if job else None


def get_required_model_candidates(
    config: dict[str, Any],
    *,
    enable_thinking: bool = False,
) -> list[ModelCandidate]:
    candidates = list_model_candidates(config)
    by_key = {candidate.key: candidate for candidate in candidates}
    required_keys = _required_model_keys()

    missing = [key for key in required_keys if key not in by_key]
    if missing:
        configured = ", ".join(sorted(by_key)) or "none"
        raise ModelCompareConfigError(
            "model compare requires configured models "
            f"{', '.join(required_keys)}; missing {', '.join(missing)}; "
            f"configured: {configured}"
        )

    return [_apply_request_thinking_mode(by_key[key], enable_thinking) for key in required_keys]


def list_model_candidates(config: dict[str, Any]) -> list[ModelCandidate]:
    candidates: list[ModelCandidate] = []
    seen: dict[str, int] = {}

    def add(candidate: ModelCandidate | None) -> None:
        if candidate is None:
            return
        existing_index = seen.get(candidate.key)
        if existing_index is None:
            seen[candidate.key] = len(candidates)
            candidates.append(candidate)
        else:
            candidates[existing_index] = candidate

    for candidate_config in (config.get("model_compare", {}) or {}).get("models", []):
        add(_candidate_from_config(candidate_config))

    add(_candidate_from_active_llm(config))

    for key, prefix in ENV_MODEL_PREFIXES.items():
        add(_candidate_from_env(key, prefix))

    return candidates


def _run_model_compare_job(
    job_id: str,
    url: str,
    candidates: list[ModelCandidate],
    config: dict[str, Any],
    enable_thinking: bool,
) -> None:
    output_dir: Path | None = None
    metadata: dict[str, Any] = {}
    files: list[dict[str, str]] = []
    errors: list[dict[str, str]] = []
    generated_at = _now_iso()

    try:
        _update_job(job_id, status="running", status_label="处理中", stage="metadata", message="正在解析小宇宙链接")
        downloader = create_downloader(url)
        video_info = downloader.get_video_info(url)
        metadata = _normalize_video_info(video_info, url)

        output_dir = _build_output_dir(config, metadata["title"], job_id)
        output_dir.mkdir(parents=True, exist_ok=True)
        _update_job(
            job_id,
            output_dir=str(output_dir),
            directory_url=f"/model-compare/{job_id}",
            title=metadata["title"],
            stage="download",
            message="正在下载音频",
        )

        download_url = video_info.get("download_url")
        filename = video_info.get("filename") or f"{metadata['platform']}_{metadata['media_id']}.m4a"
        if not download_url:
            raise RuntimeError("download_url not found from source page")

        local_file = downloader.download_file(download_url, filename)
        if not local_file:
            raise RuntimeError("audio download failed")

        _update_job(job_id, stage="transcribe", message="正在转录音频")
        funasr_result = FunASRSpeakerClient().transcribe_sync(local_file)
        transcript_text = (funasr_result.get("formatted_text") or "").strip()
        transcription_result = funasr_result.get("transcription_result") or {}
        if not transcript_text:
            raise RuntimeError("transcript is empty")

        original_filename = _dated_filename("original", "md")
        _write_markdown(
            output_dir / original_filename,
            title="原始转录",
            source_url=url,
            generated_at=generated_at,
            metadata=metadata,
            body=transcript_text,
        )
        files.append(_file_link(original_filename, "原始转录", "original"))

        transcript_json_filename = _dated_filename("transcript_funasr", "json")
        _write_json(output_dir / transcript_json_filename, transcription_result)
        files.append(_file_link(transcript_json_filename, "FunASR JSON", "transcript"))

        content_for_llm: Any = transcription_result if isinstance(transcription_result, dict) else transcript_text
        _update_job(job_id, stage="proofread", message="正在分别调用两个模型生成校对稿")

        for candidate in candidates:
            try:
                calibrated = _run_candidate_calibration(
                    candidate=candidate,
                    config=config,
                    cache_root=output_dir / ".llm_cache" / candidate.key,
                    content=content_for_llm,
                    transcript_text=transcript_text,
                    metadata=metadata,
                )
                filename = _dated_filename(candidate.key, "md")
                _write_markdown(
                    output_dir / filename,
                    title=f"{candidate.label} 校对稿",
                    source_url=url,
                    generated_at=generated_at,
                    metadata=metadata,
                    body=calibrated,
                    model=candidate.public_dict(),
                )
                files.append(_file_link(filename, f"{candidate.label} 校对稿", candidate.key))
            except Exception as exc:
                logger.exception("model compare candidate failed: %s", candidate.key)
                errors.append({"model": candidate.key, "message": str(exc)})
                filename = _dated_filename(f"{candidate.key}_ERROR", "md")
                _write_markdown(
                    output_dir / filename,
                    title=f"{candidate.label} 校对失败",
                    source_url=url,
                    generated_at=generated_at,
                    metadata=metadata,
                    body=f"{candidate.label} 生成失败：{exc}",
                    model=candidate.public_dict(),
                )
                files.append(_file_link(filename, f"{candidate.label} 错误记录", candidate.key))

        meta = {
            "job_id": job_id,
            "url": url,
            "generated_at": generated_at,
            "metadata": metadata,
            "enable_thinking": enable_thinking,
            "models": [candidate.public_dict() for candidate in candidates],
            "files": files,
            "errors": errors,
        }
        meta_filename = _dated_filename("meta", "json")
        _write_json(output_dir / meta_filename, meta)
        files.append(_file_link(meta_filename, "任务元数据", "meta"))

        if errors and len(errors) == len(candidates):
            status = "failed"
            status_label = "全部失败"
            message = "两个模型都没有成功生成校对稿"
        elif errors:
            status = "partial"
            status_label = "部分完成"
            message = "有模型生成失败，已保留成功文件和错误记录"
        else:
            status = "success"
            status_label = "已完成"
            message = "两个模型的校对稿已生成"

        _update_job(
            job_id,
            status=status,
            status_label=status_label,
            stage="done",
            message=message,
            file_links=files,
            errors=errors,
            updated_at=_now_iso(),
        )
    except Exception as exc:
        logger.exception("model compare job failed: %s", job_id)
        if output_dir:
            try:
                _write_json(
                    output_dir / _dated_filename("error", "json"),
                    {
                        "job_id": job_id,
                        "url": url,
                        "generated_at": generated_at,
                        "metadata": metadata,
                        "error": str(exc),
                    },
                )
            except Exception:
                logger.exception("failed to write model compare error metadata")
        _update_job(
            job_id,
            status="failed",
            status_label="失败",
            stage="failed",
            message=str(exc),
            errors=[*errors, {"model": "job", "message": str(exc)}],
            updated_at=_now_iso(),
        )


def _run_candidate_calibration(
    *,
    candidate: ModelCandidate,
    config: dict[str, Any],
    cache_root: Path,
    content: Any,
    transcript_text: str,
    metadata: dict[str, str],
) -> str:
    candidate_config = _build_candidate_config(config, candidate)
    cache_root.mkdir(parents=True, exist_ok=True)
    coordinator = LLMCoordinator(
        config_dict=candidate_config,
        cache_dir=str(cache_root),
    )
    result = coordinator.process(
        content=content if _has_dialog_segments(content) else transcript_text,
        title=metadata["title"],
        author=metadata["author"],
        description=metadata["description"],
        platform=f"model_compare_{candidate.key}",
        media_id=metadata["media_id"],
        skip_summary=True,
    )
    calibrated = (result.get("calibrated_text") or "").strip()
    if not calibrated:
        raise RuntimeError("model returned empty calibration")
    return calibrated


def _build_candidate_config(config: dict[str, Any], candidate: ModelCandidate) -> dict[str, Any]:
    candidate_config = copy.deepcopy(config)
    llm_config = copy.deepcopy(candidate_config.get("llm", {}))
    llm_config.update(
        {
            "api_key": candidate.api_key,
            "base_url": candidate.base_url,
            "calibrate_model": candidate.model,
            "summary_model": candidate.model,
            "key_info_model": candidate.model,
            "speaker_model": candidate.model,
            "enable_summary": False,
        }
    )
    reasoning_fields = (
        "calibrate_reasoning_effort",
        "summary_reasoning_effort",
        "key_info_reasoning_effort",
        "speaker_reasoning_effort",
    )
    if candidate.reasoning_effort is not None:
        llm_config["calibrate_reasoning_effort"] = candidate.reasoning_effort
        llm_config["summary_reasoning_effort"] = candidate.reasoning_effort
        llm_config["key_info_reasoning_effort"] = candidate.reasoning_effort
        llm_config["speaker_reasoning_effort"] = candidate.reasoning_effort
    else:
        for field in reasoning_fields:
            llm_config.pop(field, None)

    request_options = copy.deepcopy(llm_config.get("request_options", {}))
    if not isinstance(request_options, dict):
        request_options = {}
    if candidate.thinking_type is not None:
        request_options["thinking"] = {"type": candidate.thinking_type}
    else:
        request_options.pop("thinking", None)
    if request_options:
        llm_config["request_options"] = request_options
    else:
        llm_config.pop("request_options", None)
    if candidate.max_retries is not None:
        llm_config["max_retries"] = candidate.max_retries
    if candidate.retry_delay is not None:
        llm_config["retry_delay"] = candidate.retry_delay
    candidate_config["llm"] = llm_config
    return candidate_config


def _candidate_from_active_llm(config: dict[str, Any]) -> ModelCandidate | None:
    llm_config = config.get("llm", {}) or {}
    api_key = str(llm_config.get("api_key") or "").strip()
    base_url = str(llm_config.get("base_url") or "").strip()
    model = str(llm_config.get("calibrate_model") or "").strip()
    if not (_looks_configured(api_key) and _looks_configured(base_url) and _looks_configured(model)):
        return None

    key = _guess_model_key(model=model, base_url=base_url)
    request_options = llm_config.get("request_options", {}) or {}
    thinking = request_options.get("thinking") if isinstance(request_options, dict) else None
    thinking_type = thinking.get("type") if isinstance(thinking, dict) else None
    return ModelCandidate(
        key=key,
        label=_default_label(key),
        model=model,
        base_url=base_url,
        api_key=api_key,
        reasoning_effort=llm_config.get("calibrate_reasoning_effort"),
        thinking_type=thinking_type,
        max_retries=llm_config.get("max_retries"),
        retry_delay=llm_config.get("retry_delay"),
    )


def _candidate_from_config(candidate_config: dict[str, Any]) -> ModelCandidate | None:
    if not candidate_config or candidate_config.get("enabled", True) is False:
        return None
    key = str(candidate_config.get("key") or "").strip().lower()
    model = str(candidate_config.get("model") or "").strip()
    base_url = str(candidate_config.get("base_url") or "").strip()
    api_key = _resolve_api_key(
        candidate_config.get("api_key"),
        candidate_config.get("api_key_env"),
    )
    if not key or not (_looks_configured(api_key) and _looks_configured(base_url) and _looks_configured(model)):
        return None
    return ModelCandidate(
        key=key,
        label=str(candidate_config.get("label") or _default_label(key)).strip(),
        model=model,
        base_url=base_url,
        api_key=api_key,
        reasoning_effort=candidate_config.get("reasoning_effort"),
        thinking_type=candidate_config.get("thinking_type"),
        max_retries=candidate_config.get("max_retries"),
        retry_delay=candidate_config.get("retry_delay"),
    )


def _candidate_from_env(key: str, prefix: str) -> ModelCandidate | None:
    api_key = os.getenv(f"{prefix}_API_KEY", "").strip()
    base_url = os.getenv(f"{prefix}_BASE_URL", "").strip()
    model = os.getenv(f"{prefix}_MODEL", "").strip()
    if not (_looks_configured(api_key) and _looks_configured(base_url) and _looks_configured(model)):
        return None
    return ModelCandidate(
        key=key,
        label=os.getenv(f"{prefix}_LABEL", _default_label(key)).strip(),
        model=model,
        base_url=base_url,
        api_key=api_key,
        reasoning_effort=os.getenv(f"{prefix}_REASONING_EFFORT") or None,
        thinking_type=os.getenv(f"{prefix}_THINKING_TYPE") or None,
        max_retries=_optional_int(os.getenv(f"{prefix}_MAX_RETRIES")),
        retry_delay=_optional_int(os.getenv(f"{prefix}_RETRY_DELAY")),
    )


def _resolve_api_key(value: Any, env_name: Any) -> str:
    if env_name:
        return os.getenv(str(env_name), "").strip()
    if isinstance(value, str) and value.startswith("env:"):
        return os.getenv(value[4:], "").strip()
    return str(value or "").strip()


def _required_model_keys() -> tuple[str, ...]:
    raw = os.getenv("MODEL_COMPARE_MODEL_KEYS", "")
    keys = [item.strip().lower() for item in raw.split(",") if item.strip()]
    return tuple(keys) if keys else DEFAULT_REQUIRED_MODEL_KEYS


def _apply_request_thinking_mode(candidate: ModelCandidate, enable_thinking: bool) -> ModelCandidate:
    if enable_thinking:
        return replace(
            candidate,
            reasoning_effort=candidate.reasoning_effort or _thinking_effort_default(candidate.key),
            thinking_type=candidate.thinking_type or _thinking_type_default(candidate.key),
        )
    return replace(
        candidate,
        reasoning_effort=_non_thinking_effort_default(candidate.key),
        thinking_type=None,
    )


def _thinking_effort_default(key: str) -> str | None:
    return {
        "deepseek": "high",
        "doubao": "medium",
    }.get(key)


def _thinking_type_default(key: str) -> str | None:
    return {
        "deepseek": "enabled",
    }.get(key)


def _non_thinking_effort_default(key: str) -> str | None:
    return {
        "doubao": "minimal",
    }.get(key)


def _guess_model_key(*, model: str, base_url: str) -> str:
    haystack = f"{model} {base_url}".lower()
    if "deepseek" in haystack:
        return "deepseek"
    if "doubao" in haystack or "volces" in haystack or "ark.cn" in haystack or model.startswith("ep-"):
        return "doubao"
    return "active_llm"


def _default_label(key: str) -> str:
    return {
        "deepseek": "DeepSeek",
        "doubao": "豆包",
        "kimi": "Kimi",
    }.get(key, key)


def _looks_configured(value: str) -> bool:
    if not value:
        return False
    lowered = value.lower()
    return not (
        lowered.startswith("your-")
        or lowered.startswith("replace-")
        or "your-" in lowered
        or "replace-with" in lowered
    )


def _optional_int(value: str | None) -> int | None:
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _build_output_dir(config: dict[str, Any], title: str, job_id: str) -> Path:
    output_root = (
        os.getenv("MODEL_COMPARE_OUTPUT_DIR")
        or (config.get("storage", {}) or {}).get("model_compare_dir")
        or "./data/model_compare"
    )
    today = _today()
    slug = _safe_slug(title) or "xiaoyuzhou"
    return Path(output_root) / f"{today}_{slug}_{job_id[:8]}"


def _normalize_video_info(video_info: dict[str, Any], url: str) -> dict[str, str]:
    return {
        "title": str(video_info.get("video_title") or video_info.get("title") or "Untitled").strip(),
        "author": str(video_info.get("author") or "").strip(),
        "description": str(video_info.get("description") or "").strip(),
        "platform": str(video_info.get("platform") or "xiaoyuzhou").strip(),
        "media_id": str(video_info.get("video_id") or uuid.uuid5(uuid.NAMESPACE_URL, url).hex[:16]).strip(),
    }


def _has_dialog_segments(content: Any) -> bool:
    if isinstance(content, dict):
        return bool(content.get("segments"))
    if isinstance(content, list):
        return bool(content)
    return False


def _write_markdown(
    path: Path,
    *,
    title: str,
    source_url: str,
    generated_at: str,
    metadata: dict[str, str],
    body: str,
    model: dict[str, str] | None = None,
) -> None:
    model_lines = ""
    if model:
        model_lines = f"- Model: {model['label']} ({model['model']})\n"
    text = (
        f"# {title}\n\n"
        f"- Source: {source_url}\n"
        f"- Generated: {generated_at}\n"
        f"- Title: {metadata.get('title', '')}\n"
        f"- Author: {metadata.get('author', '')}\n"
        f"{model_lines}"
        "\n---\n\n"
        f"{body.strip()}\n"
    )
    path.write_text(text, encoding="utf-8")


def _write_json(path: Path, payload: Any) -> None:
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def _file_link(filename: str, label: str, model_key: str) -> dict[str, str]:
    return {
        "filename": filename,
        "label": label,
        "model_key": model_key,
        "url": "",
    }


def _dated_filename(name: str, ext: str) -> str:
    return f"{_today()}_{_safe_slug(name)}.{ext}"


def _safe_slug(value: str, max_length: int = 60) -> str:
    value = (value or "").strip().lower()
    value = re.sub(r"[\\/:*?\"<>|]+", "-", value)
    value = re.sub(r"\s+", "-", value)
    value = re.sub(r"-+", "-", value).strip("-._")
    if len(value) > max_length:
        value = value[:max_length].rstrip("-._")
    return value or "untitled"


def _today() -> str:
    return datetime.now().strftime("%Y-%m-%d")


def _now_iso() -> str:
    return datetime.now().astimezone().isoformat(timespec="seconds")


def _set_job(job_id: str, job: dict[str, Any]) -> None:
    with _jobs_lock:
        _jobs[job_id] = copy.deepcopy(job)


def _update_job(job_id: str, **updates: Any) -> None:
    with _jobs_lock:
        job = _jobs.get(job_id)
        if not job:
            return
        job.update(updates)
        job["updated_at"] = updates.get("updated_at") or _now_iso()
