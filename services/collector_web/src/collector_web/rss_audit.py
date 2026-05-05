import json
import re
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

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


class _SummaryTextExtractor(HTMLParser):
    _BLOCK_TAGS = {
        "blockquote",
        "br",
        "div",
        "li",
        "ol",
        "p",
        "pre",
        "section",
        "tr",
        "ul",
    }

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag.lower() in self._BLOCK_TAGS:
            self._append_separator()

    def handle_endtag(self, tag: str) -> None:
        if tag.lower() in self._BLOCK_TAGS:
            self._append_separator()

    def handle_data(self, data: str) -> None:
        if data:
            self._parts.append(data)

    def text(self) -> str:
        return " ".join("".join(self._parts).split())

    def _append_separator(self) -> None:
        if self._parts and not self._parts[-1].endswith(" "):
            self._parts.append(" ")


def _summary_preview(value: Any, max_length: int = 320) -> str:
    raw_summary = _as_string(value)
    if not raw_summary:
        return ""

    if "<" in raw_summary and ">" in raw_summary:
        parser = _SummaryTextExtractor()
        try:
            parser.feed(raw_summary)
            parser.close()
            text = parser.text()
        except Exception:
            text = re.sub(r"<[^>]+>", " ", raw_summary)
    else:
        text = raw_summary

    text = " ".join(unescape(text).split())
    if len(text) <= max_length:
        return text
    return f"{text[:max_length].rstrip()}..."


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


def _source_gate_status_label(value: str) -> str:
    return {
        "changed": "有新内容",
        "unchanged": "来源未变化",
        "empty": "本轮为空",
        "rss_error": "RSS 失败",
        "not_checked": "未检查",
    }.get(value or "not_checked", value or "未知")


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


def _skip_layer_label(value: str) -> str:
    return {
        "source_last_seen_gate": "来源门禁",
        "qdrant_gate": "去重门禁",
        "action_policy": "策略层",
        "vault_writer": "写入层",
        "qdrant_commit": "向量提交",
        "llm_scoring": "LLM 评分",
        "pre_llm": "LLM 前",
        "rss_read": "RSS 拉取",
        "transcript_ingest": "转写入口",
        "normalize_text_object": "文本标准化",
        "error": "错误处理",
    }.get(value or "", value or "未知层级")


def _infer_skip_layer(audit_reason: str, audit_status: str, has_score: bool) -> str:
    if audit_reason == "source_last_seen_gate":
        return "source_last_seen_gate"
    if audit_reason in {"silent_dedupe", "llm_not_requested"}:
        return "qdrant_gate"
    if audit_reason == "action_policy_skipped":
        return "action_policy"
    if audit_reason in {"vault_written", "vault_write_error"}:
        return "vault_writer"
    if audit_reason == "qdrant_skipped":
        return "qdrant_commit"
    if audit_reason.endswith("_error"):
        return audit_reason.removesuffix("_error") or "error"
    if has_score:
        return "llm_scoring"
    if audit_status in {"not_scored", "seen"}:
        return "pre_llm"
    return ""


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


_AUDIT_STATUS_RANK = {
    "failed": 60,
    "written": 50,
    "scored": 40,
    "skipped": 30,
    "not_scored": 20,
    "seen": 10,
    "": 0,
}


def _normalize_url_key(value: str) -> str:
    text = _as_string(value)
    if not text:
        return ""
    try:
        parsed = urlsplit(text)
    except ValueError:
        return text.rstrip("/").lower()
    if not parsed.scheme or not parsed.netloc:
        return text.rstrip("/").lower()
    path = parsed.path.rstrip("/") or "/"
    return urlunsplit(
        (parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, "")
    )


def _item_identity_key(item: dict[str, Any]) -> str:
    original_id = _as_string(item.get("original_id") or item.get("guid"))
    audit_key = _as_string(item.get("audit_key"))
    original_id_url = original_id if original_id.startswith(("http://", "https://")) else ""
    audit_key_url = audit_key if audit_key.startswith(("http://", "https://")) else ""
    url = _normalize_url_key(
        _as_string(item.get("url"))
        or _as_string(item.get("canonical_url"))
        or _as_string(item.get("link"))
        or _as_string(item.get("original_url"))
        or original_id_url
        or audit_key_url
    )
    if url:
        return f"url:{url}"

    item_id = _as_string(item.get("item_id") or item.get("itemId") or item.get("id"))
    if item_id:
        return f"id:{item_id}"

    if original_id:
        return f"original:{original_id}"

    title = _as_string(item.get("title")).lower()
    published_at = _as_string(
        item.get("published_at") or item.get("publishedAt") or item.get("pubDate")
    )
    if title and published_at:
        return f"title:{title}|published:{published_at}"
    return ""


def _item_rank(item: dict[str, Any]) -> tuple[int, int, int, int]:
    audit_status = _as_string(item.get("audit_status"))
    return (
        _AUDIT_STATUS_RANK.get(audit_status, 0),
        1 if _primary_score(item) is not None else 0,
        1 if _as_string(item.get("vault_path")) else 0,
        1 if _as_string(item.get("audit_detail")) else 0,
    )


def _is_blank(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _merge_duplicate_raw_items(
    left: dict[str, Any], right: dict[str, Any]
) -> dict[str, Any]:
    primary, fallback = (
        (right, left) if _item_rank(right) >= _item_rank(left) else (left, right)
    )
    merged = {**fallback, **primary}
    for key, value in fallback.items():
        if _is_blank(merged.get(key)) and not _is_blank(value):
            merged[key] = value
    return merged


def _dedupe_raw_items(raw_items: list[dict[str, Any]]) -> list[dict[str, Any]]:
    deduped_items: list[dict[str, Any]] = []
    index_by_key: dict[str, int] = {}
    for item in raw_items:
        key = _item_identity_key(item)
        if key and key in index_by_key:
            index = index_by_key[key]
            deduped_items[index] = _merge_duplicate_raw_items(
                deduped_items[index], item
            )
            continue
        if key:
            index_by_key[key] = len(deduped_items)
        deduped_items.append(item)
    return deduped_items


def _normalize_item(source: dict[str, Any], item: dict[str, Any], index: int) -> dict[str, Any]:
    ai_score = _as_object(item.get("ai_score"))
    score_dimensions = _as_object(item.get("score_dimensions"))
    audit_status = _as_string(item.get("audit_status")) or "not_scored"
    audit_reason = _as_string(item.get("audit_reason")) or "score_not_available"
    original_url = _as_string(item.get("url"))
    primary_score = _primary_score(item)
    has_score = primary_score is not None
    llm_ran = item.get("llm_ran")
    if not isinstance(llm_ran, bool):
        llm_ran = has_score
    skip_layer = _as_string(item.get("skip_layer")) or _infer_skip_layer(
        audit_reason, audit_status, has_score
    )
    source_gate_status = (
        _as_string(item.get("source_gate_status"))
        or _as_string(source.get("source_gate_status"))
        or "not_checked"
    )
    summary = _as_string(item.get("summary"))

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
        "source_gate_status": source_gate_status,
        "source_gate_status_label": _source_gate_status_label(source_gate_status),
        "llm_ran": llm_ran,
        "llm_status_label": "LLM 已跑" if llm_ran else "LLM 未跑",
        "skip_layer": skip_layer,
        "skip_layer_label": _skip_layer_label(skip_layer),
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
        "summary": summary,
        "summary_preview": _summary_preview(summary),
        "llm_reason": _as_string(item.get("llm_reason")),
        "event_relation": _as_string(item.get("event_relation")),
        "delta_importance": _to_int(item.get("delta_importance")),
        "matched_score": _to_float_or_none(item.get("matched_score")),
        "matched_title": _as_string(item.get("matched_title")),
        "can_open_original": bool(original_url),
        "has_score": has_score,
        "is_written": audit_status == "written",
    }


def _normalize_source(source: dict[str, Any]) -> dict[str, Any]:
    raw_items = [item for item in source.get("items", []) if isinstance(item, dict)]
    deduped_raw_items = _dedupe_raw_items(raw_items)
    items = [
        _normalize_item(source, item, index + 1)
        for index, item in enumerate(deduped_raw_items)
    ]
    rss_status = _as_string(source.get("rss_status")) or "unknown"
    transcript_status = _as_string(source.get("transcript_status")) or "unknown"

    source_gate_status = _as_string(source.get("source_gate_status")) or "not_checked"

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
        "source_gate_status": source_gate_status,
        "source_gate_status_label": _source_gate_status_label(source_gate_status),
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
