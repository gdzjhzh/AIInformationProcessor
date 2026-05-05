import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .config import Settings


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _format_datetime(value: str | None) -> str:
    parsed = _parse_datetime(value)
    if parsed is None:
        return value or ""
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone().strftime("%Y-%m-%d %H:%M %Z")


def _minutes_since(value: str | None) -> int | None:
    parsed = _parse_datetime(value)
    if parsed is None:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    delta = datetime.now(timezone.utc) - parsed.astimezone(timezone.utc)
    return max(int(delta.total_seconds() // 60), 0)


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _to_float_or_none(value: Any) -> float | None:
    try:
        numeric_value = float(value)
    except (TypeError, ValueError):
        return None
    return numeric_value


def _as_string(value: Any) -> str:
    return str(value or "").strip()


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [_as_string(item) for item in value if _as_string(item)]


def _as_object(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _find_latest_poll_run_file(poll_runs_dir: Path) -> Path | None:
    if not poll_runs_dir.exists():
        return None
    candidates = poll_runs_dir.rglob("*_01_rss_to_obsidian_raw.json")
    return max(candidates, key=lambda item: item.stat().st_mtime, default=None)


def _status_label(value: str) -> str:
    return {
        "success": "成功",
        "error": "失败",
        "pending": "等待中",
        "not_requested": "未请求",
        "not_checked": "未检查",
        "unknown": "未知",
    }.get(value or "unknown", value or "未知")


def _audit_status_label(value: str) -> str:
    return {
        "written": "已写入",
        "scored": "已评分",
        "skipped": "未写入",
        "not_scored": "未评分",
        "failed": "失败",
        "seen": "已看到",
    }.get(value or "not_scored", value or "未评分")


def _audit_reason_label(value: str) -> str:
    return {
        "vault_written": "已写入 Obsidian",
        "silent_dedupe": "去重跳过",
        "source_last_seen_gate": "来源未变化",
        "llm_not_requested": "未进入 LLM",
        "score_not_available": "无评分",
        "action_policy_skipped": "策略未写入",
        "scored_without_vault_write_record": "已评分但未写入",
        "qdrant_skipped": "未提交向量",
        "rss_read_error": "RSS 拉取失败",
        "transcript_ingest_error": "转写失败",
        "normalize_text_object_error": "标准化失败",
        "vault_write_error": "写入失败",
        "error": "处理失败",
    }.get(value or "score_not_available", value or "未知原因")


def _primary_score(item: dict[str, Any]) -> int | None:
    keep_score = _to_float_or_none(item.get("keep_score"))
    if keep_score is not None:
        return round(keep_score)

    ai_score = _as_object(item.get("ai_score"))
    keep_score = _to_float_or_none(ai_score.get("keep_score"))
    if keep_score is not None:
        return round(keep_score)

    normalized_score = _to_float_or_none(item.get("score"))
    score_scale = _to_float_or_none(item.get("score_scale")) or 100
    if normalized_score is None:
        return None
    if 0 <= normalized_score <= 1:
        return round(normalized_score * score_scale)
    return round(normalized_score)


def _normalize_item(source: dict[str, Any], item: dict[str, Any], index: int) -> dict[str, Any]:
    ai_score = _as_object(item.get("ai_score"))
    score_dimensions = _as_object(item.get("score_dimensions"))
    audit_status = _as_string(item.get("audit_status")) or "not_scored"
    audit_reason = _as_string(item.get("audit_reason")) or "score_not_available"
    original_url = _as_string(item.get("url"))
    primary_score = _primary_score(item)

    return {
        "index": index,
        "source_name": _as_string(source.get("source_name")) or "未命名订阅源",
        "source_type": _as_string(source.get("source_type")) or "unknown",
        "feed_url": _as_string(source.get("feed_url")),
        "title": _as_string(item.get("title")) or "untitled",
        "original_url": original_url,
        "published_at": _as_string(item.get("published_at")),
        "published_at_label": _format_datetime(_as_string(item.get("published_at"))),
        "item_id": _as_string(item.get("item_id")),
        "original_id": _as_string(item.get("original_id")),
        "author": _as_string(item.get("author")),
        "audit_status": audit_status,
        "audit_status_label": _audit_status_label(audit_status),
        "audit_reason": audit_reason,
        "audit_reason_label": _audit_reason_label(audit_reason),
        "audit_detail": _as_string(item.get("audit_detail")),
        "dedupe_action": _as_string(item.get("dedupe_action")),
        "notification_mode": _as_string(item.get("notification_mode")),
        "vault_write_status": _as_string(item.get("vault_write_status")),
        "vault_path": _as_string(item.get("vault_path")),
        "qdrant_operation": _as_string(item.get("qdrant_operation")),
        "primary_score": primary_score,
        "score": _to_float_or_none(item.get("score")),
        "score_scale": _to_int(item.get("score_scale") or 100) or 100,
        "keep_score": _to_int(item.get("keep_score") or ai_score.get("keep_score")),
        "notify_score": _to_int(item.get("notify_score") or ai_score.get("notify_score")),
        "reference_score": _to_int(
            item.get("reference_score") or ai_score.get("reference_score")
        ),
        "action_score": _to_int(item.get("action_score") or ai_score.get("action_score")),
        "confidence": _to_float_or_none(item.get("confidence") or ai_score.get("confidence")),
        "decision_hint": _as_string(item.get("decision_hint") or ai_score.get("decision_hint")),
        "ai_score": ai_score,
        "score_dimensions": score_dimensions,
        "category": _as_string(item.get("category")),
        "tags": _as_string_list(item.get("tags")),
        "summary": _as_string(item.get("summary")),
        "llm_reason": _as_string(item.get("llm_reason")),
        "event_relation": _as_string(item.get("event_relation")),
        "delta_importance": _to_int(item.get("delta_importance")),
        "matched_score": _to_float_or_none(item.get("matched_score")),
        "matched_title": _as_string(item.get("matched_title")),
        "can_open_original": bool(original_url),
        "has_score": primary_score is not None,
        "is_written": audit_status == "written",
    }


def _normalize_source(source: dict[str, Any]) -> dict[str, Any]:
    raw_items = [item for item in source.get("items", []) if isinstance(item, dict)]
    items = [_normalize_item(source, item, index + 1) for index, item in enumerate(raw_items)]
    rss_status = _as_string(source.get("rss_status")) or "unknown"
    transcript_status = _as_string(source.get("transcript_status")) or "unknown"

    return {
        "source_name": _as_string(source.get("source_name")) or "未命名订阅源",
        "source_type": _as_string(source.get("source_type")) or "unknown",
        "feed_url": _as_string(source.get("feed_url")),
        "rss_status": rss_status,
        "rss_status_label": _status_label(rss_status),
        "rss_error": _as_string(source.get("rss_error")),
        "transcript_status": transcript_status,
        "transcript_status_label": _status_label(transcript_status),
        "transcript_error": _as_string(source.get("transcript_error")),
        "source_gate_status": _as_string(source.get("source_gate_status")) or "not_checked",
        "is_new_since_last_poll": bool(source.get("is_new_since_last_poll")),
        "item_count": _to_int(source.get("item_count")),
        "new_item_count": _to_int(source.get("new_item_count")),
        "wrote_count": _to_int(source.get("wrote_count")),
        "qdrant_commit_count": _to_int(source.get("qdrant_commit_count")),
        "dedupe_actions": _as_string_list(source.get("dedupe_actions")),
        "vault_write_statuses": _as_string_list(source.get("vault_write_statuses")),
        "wrote_paths": _as_string_list(source.get("wrote_paths")),
        "sample_titles": _as_string_list(source.get("sample_titles")),
        "new_titles": _as_string_list(source.get("new_titles")),
        "current_latest_title": _as_string(source.get("current_latest_title")),
        "current_latest_link": _as_string(source.get("current_latest_link")),
        "items": items,
        "audit_item_count": len(items),
        "scored_item_count": sum(1 for item in items if item["has_score"]),
        "written_item_count": sum(1 for item in items if item["is_written"]),
        "failed_item_count": sum(1 for item in items if item["audit_status"] == "failed"),
    }


def get_latest_rss_poll_audit(settings: Settings) -> dict[str, Any]:
    latest_file = _find_latest_poll_run_file(settings.poll_runs_dir)
    if latest_file is None:
        return {
            "ok": False,
            "error": "poll_runs summary not found",
            "latest_file": "",
            "poll": {},
            "sources": [],
            "items": [],
            "schema_has_item_details": False,
        }

    try:
        payload = json.loads(latest_file.read_text(encoding="utf-8"))
    except Exception as exc:
        return {
            "ok": False,
            "error": f"failed to parse poll_runs summary: {exc}",
            "latest_file": str(latest_file),
            "poll": {},
            "sources": [],
            "items": [],
            "schema_has_item_details": False,
        }

    raw_sources = [source for source in payload.get("sources", []) if isinstance(source, dict)]
    sources = [_normalize_source(source) for source in raw_sources]
    flat_items = [item for source in sources for item in source["items"]]
    run_finished_at = _as_string(payload.get("run_finished_at"))

    return {
        "ok": True,
        "error": "",
        "latest_file": str(latest_file),
        "poll": {
            "execution_id": _as_string(payload.get("execution_id")),
            "workflow": _as_string(payload.get("workflow")),
            "workflow_id": _as_string(payload.get("workflow_id")),
            "run_started_at": _as_string(payload.get("run_started_at")),
            "run_started_at_label": _format_datetime(_as_string(payload.get("run_started_at"))),
            "run_finished_at": run_finished_at,
            "run_finished_at_label": _format_datetime(run_finished_at),
            "age_minutes": _minutes_since(run_finished_at),
            "source_count": _to_int(payload.get("source_count")),
            "success_source_count": _to_int(payload.get("success_source_count")),
            "failed_source_count": _to_int(payload.get("failed_source_count")),
            "new_source_count": _to_int(payload.get("new_source_count")),
            "transcript_failed_source_count": _to_int(
                payload.get("transcript_failed_source_count")
            ),
            "items_seen": _to_int(payload.get("items_seen")),
            "items_selected_for_processing": _to_int(
                payload.get("items_selected_for_processing")
            ),
            "items_written": _to_int(payload.get("items_written")),
            "poll_runs_version": _to_int(payload.get("poll_runs_version")),
        },
        "sources": sources,
        "items": flat_items,
        "item_count": len(flat_items),
        "scored_item_count": sum(1 for item in flat_items if item["has_score"]),
        "written_item_count": sum(1 for item in flat_items if item["is_written"]),
        "failed_item_count": sum(1 for item in flat_items if item["audit_status"] == "failed"),
        "schema_has_item_details": any(source["audit_item_count"] > 0 for source in sources),
    }
