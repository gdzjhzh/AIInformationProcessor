from __future__ import annotations

from typing import Any

from .config import Settings
from .repository import find_latest_manual_submission_match
from .url_tools import canonicalize_manual_media_url


def precheck_manual_media_submission(
    settings: Settings,
    url: str,
) -> dict[str, Any]:
    normalized = canonicalize_manual_media_url(
        url,
        timeout_seconds=settings.manual_media_precheck_timeout_seconds,
    )

    matched_submission, match_reason = find_latest_manual_submission_match(
        settings,
        request_url=url,
        normalized_url=normalized["normalized_url"],
        resolved_url=normalized["resolved_url"],
        canonical_url=normalized["canonical_url"],
    )

    duplicate_found = matched_submission is not None
    return {
        "ok": True,
        "duplicate_found": duplicate_found,
        "normalized_url": normalized["normalized_url"],
        "resolved_url": normalized["resolved_url"],
        "canonical_url": normalized["canonical_url"],
        "match_reason": match_reason,
        "summary": _build_precheck_summary(matched_submission, match_reason),
        "matched_submission": matched_submission,
    }


def _build_precheck_summary(
    matched_submission: dict[str, Any] | None,
    match_reason: str,
) -> str:
    if matched_submission is None:
        return "未发现同链接历史记录，可以直接开始处理。"

    if matched_submission["is_active"]:
        return "这条链接已经有一条处理中记录，建议先查看现有状态。"

    reason_label = {
        "request_url": "原始链接",
        "resolved_url": "解析后的链接",
        "canonical_url": "规范链接",
    }.get(match_reason, "历史记录")

    return f"命中了同一{reason_label}的历史提交，继续处理大概率会再次触发重复判定。"
