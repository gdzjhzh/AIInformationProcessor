import json
from datetime import datetime, timezone
from typing import Any

from .config import Settings
from .db import connect, utc_now
from .url_tools import normalize_url_for_match

PLATFORM_LABELS = {
    "bilibili": "B站",
    "xiaoyuzhou": "小宇宙",
    "youtube": "YouTube",
    "rss": "RSS",
}

MANUAL_SUBMISSION_STATUS_LABELS = {
    "queued": "已排队",
    "running": "处理中",
    "completed": "已完成",
    "needs_confirmation": "发现重复",
    "cancelled": "已取消",
    "error": "处理失败",
}

MANUAL_SUBMISSION_STATUS_TONES = {
    "queued": "muted",
    "running": "accent",
    "completed": "success",
    "needs_confirmation": "warning",
    "cancelled": "muted",
    "error": "error",
}

ACTIVE_MANUAL_SUBMISSION_STATUSES = {"queued", "running"}
PRECHECK_ELIGIBLE_STATUSES = {"queued", "running", "completed", "needs_confirmation"}


def _loads_json(raw: str | None, fallback: Any) -> Any:
    if not raw:
        return fallback
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return fallback


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _duration_seconds(started_at: str | None, finished_at: str | None) -> int | None:
    started = _parse_datetime(started_at)
    if started is None:
        return None

    finished = _parse_datetime(finished_at) or datetime.now(timezone.utc)
    seconds = int((finished - started).total_seconds())
    return max(seconds, 0)


def _duration_label(seconds: int | None) -> str:
    if seconds is None:
        return ""
    if seconds < 60:
        return f"{seconds} 秒"
    minutes, remain_seconds = divmod(seconds, 60)
    if minutes < 60:
        return f"{minutes} 分 {remain_seconds} 秒"
    hours, remain_minutes = divmod(minutes, 60)
    return f"{hours} 小时 {remain_minutes} 分"


def _normalize_manual_submission_row(row: Any) -> dict[str, Any]:
    payload = dict(row)
    request_payload = _loads_json(payload.pop("request_payload_json", None), {})
    response_payload = _loads_json(payload.pop("response_json", None), {})
    qdrant_delete_detail = _loads_json(payload.pop("qdrant_delete_detail", None), None)

    if not isinstance(request_payload, dict):
        request_payload = {}
    if not isinstance(response_payload, dict):
        response_payload = {}

    raw_status = str(payload.get("status", "")).strip() or "queued"
    stage = str(payload.get("stage", "")).strip()
    status = "cancelled" if stage == "cancelled" else raw_status
    dedupe_action = str(response_payload.get("dedupe_action", "")).strip()
    vault_write_status = str(response_payload.get("vault_write_status", "")).strip()
    duration_seconds = _duration_seconds(payload.get("started_at"), payload.get("finished_at"))

    submission = {
        **payload,
        "raw_status": raw_status,
        "status": status,
        "request_payload": request_payload,
        "response_payload": response_payload,
        "qdrant_delete_detail": qdrant_delete_detail,
        "status_label": MANUAL_SUBMISSION_STATUS_LABELS.get(status, status),
        "status_tone": MANUAL_SUBMISSION_STATUS_TONES.get(status, "muted"),
        "is_active": raw_status in ACTIVE_MANUAL_SUBMISSION_STATUSES and stage != "cancelled",
        "duration_seconds": duration_seconds,
        "duration_label": _duration_label(duration_seconds),
        "title": str(response_payload.get("title", "")).strip(),
        "item_id": str(response_payload.get("item_id", "")).strip(),
        "canonical_url": str(response_payload.get("canonical_url", "")).strip(),
        "dedupe_action": dedupe_action,
        "vault_write_status": vault_write_status,
        "vault_path": str(response_payload.get("vault_path", "")).strip(),
        "summary": str(response_payload.get("summary", "")).strip(),
        "source_name": str(response_payload.get("source_name", "")).strip(),
        "source_type": str(response_payload.get("source_type", "")).strip(),
        "media_type": str(response_payload.get("media_type", "")).strip(),
        "qdrant_operation": str(response_payload.get("qdrant_operation", "")).strip(),
        "workflow_label": str(response_payload.get("workflow_label", "")).strip(),
        "cancellation_note": str(payload.get("error", "")).strip() if stage == "cancelled" else "",
    }
    submission["can_cancel"] = raw_status in ACTIVE_MANUAL_SUBMISSION_STATUSES and stage != "cancelled"
    submission["cancel_action_label"] = (
        "取消提交"
        if raw_status == "queued" and stage != "cancelled"
        else "停止跟踪"
        if raw_status == "running" and stage != "cancelled"
        else ""
    )
    submission["cancel_action_hint"] = (
        "如果请求还没发出去，会直接取消。"
        if raw_status == "queued" and stage != "cancelled"
        else "这不会强制中断已经发给 n8n 的处理，只会停止当前记录继续等待结果。"
        if raw_status == "running" and stage != "cancelled"
        else ""
    )
    submission["can_delete_vector_and_rerun"] = bool(
        submission["item_id"]
        and dedupe_action == "silent"
        and vault_write_status == "skipped"
        and not qdrant_delete_detail
    )
    return submission


def _manual_submission_status_from_result(payload: dict[str, Any]) -> str:
    error = str(payload.get("error", "")).strip()
    if error or payload.get("ok") is False:
        return "error"

    dedupe_action = str(payload.get("dedupe_action", "")).strip()
    vault_write_status = str(payload.get("vault_write_status", "")).strip()
    if dedupe_action == "silent" and vault_write_status == "skipped":
        return "needs_confirmation"

    return "completed"


def create_manual_submission(
    settings: Settings,
    request_payload: dict[str, Any],
    *,
    rerun_of_submission_id: int | None = None,
    qdrant_delete_detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = utc_now()
    request_url = str(request_payload.get("url", "")).strip()

    with connect(settings.db_path) as conn:
        cursor = conn.execute(
            """
            INSERT INTO manual_submissions (
                request_url,
                request_payload_json,
                status,
                stage,
                error,
                response_json,
                rerun_of_submission_id,
                qdrant_delete_detail,
                created_at,
                started_at,
                finished_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                request_url,
                json.dumps(request_payload, ensure_ascii=False, sort_keys=True),
                "queued",
                "collector_web_queue",
                None,
                None,
                rerun_of_submission_id,
                json.dumps(qdrant_delete_detail, ensure_ascii=False, sort_keys=True)
                if qdrant_delete_detail is not None
                else None,
                now,
                None,
                None,
                now,
            ),
        )
        submission_id = int(cursor.lastrowid)

    return get_manual_submission(settings, submission_id)


def mark_manual_submission_running(settings: Settings, submission_id: int) -> bool:
    now = utc_now()
    with connect(settings.db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE manual_submissions
            SET status = ?,
                stage = ?,
                started_at = COALESCE(started_at, ?),
                updated_at = ?,
                error = NULL
            WHERE id = ?
              AND status = ?
              AND stage != 'cancelled'
            """,
            ("running", "06_manual_media_submit", now, now, submission_id, "queued"),
        )
    return bool(cursor.rowcount)


def complete_manual_submission(
    settings: Settings,
    submission_id: int,
    result: dict[str, Any],
) -> dict[str, Any]:
    now = utc_now()
    status = _manual_submission_status_from_result(result)
    stage = str(result.get("stage", "")).strip() or "manual_media_submit"
    error = str(result.get("error", "")).strip() or None

    with connect(settings.db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE manual_submissions
            SET status = ?,
                stage = ?,
                error = ?,
                response_json = ?,
                finished_at = ?,
                updated_at = ?
            WHERE id = ?
              AND stage != 'cancelled'
            """,
            (
                status,
                stage,
                error,
                json.dumps(result, ensure_ascii=False, sort_keys=True),
                now,
                now,
                submission_id,
            ),
        )
        if cursor.rowcount == 0:
            return get_manual_submission(settings, submission_id)

    return get_manual_submission(settings, submission_id)


def mark_manual_submission_dispatched(
    settings: Settings,
    submission_id: int,
    dispatch_result: dict[str, Any],
) -> dict[str, Any]:
    now = utc_now()
    with connect(settings.db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE manual_submissions
            SET status = ?,
                stage = ?,
                response_json = ?,
                updated_at = ?
            WHERE id = ?
              AND status = ?
              AND stage != 'cancelled'
            """,
            (
                "running",
                "06_manual_media_submit_dispatched",
                json.dumps(dispatch_result, ensure_ascii=False, sort_keys=True),
                now,
                submission_id,
                "running",
            ),
        )
        if cursor.rowcount == 0:
            return get_manual_submission(settings, submission_id)

    return get_manual_submission(settings, submission_id)


def fail_manual_submission(
    settings: Settings,
    submission_id: int,
    error: str,
    *,
    stage: str = "06_manual_media_submit",
) -> dict[str, Any]:
    now = utc_now()
    with connect(settings.db_path) as conn:
        cursor = conn.execute(
            """
            UPDATE manual_submissions
            SET status = ?,
                stage = ?,
                error = ?,
                finished_at = ?,
                updated_at = ?
            WHERE id = ?
              AND stage != 'cancelled'
            """,
            ("error", stage, error.strip(), now, now, submission_id),
        )
        if cursor.rowcount == 0:
            return get_manual_submission(settings, submission_id)

    return get_manual_submission(settings, submission_id)


def cancel_manual_submission(
    settings: Settings,
    submission_id: int,
) -> tuple[dict[str, Any] | None, str]:
    now = utc_now()
    cancel_mode = ""

    with connect(settings.db_path) as conn:
        row = conn.execute(
            """
            SELECT
                id,
                status,
                stage
            FROM manual_submissions
            WHERE id = ?
            LIMIT 1
            """,
            (submission_id,),
        ).fetchone()

        if row is None:
            return None, ""

        current_status = str(row["status"] or "").strip() or "queued"
        current_stage = str(row["stage"] or "").strip()
        if current_stage == "cancelled":
            cancel_mode = "already_cancelled"
        elif current_status == "queued":
            cursor = conn.execute(
                """
                UPDATE manual_submissions
                SET status = ?,
                    stage = ?,
                    error = ?,
                    finished_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND status = ?
                  AND stage != 'cancelled'
                """,
                (
                    "error",
                    "cancelled",
                    "Cancelled before webhook dispatch by user.",
                    now,
                    now,
                    submission_id,
                    "queued",
                ),
            )
            if cursor.rowcount > 0:
                cancel_mode = "cancelled_before_dispatch"
            else:
                row = conn.execute(
                    "SELECT status, stage FROM manual_submissions WHERE id = ? LIMIT 1",
                    (submission_id,),
                ).fetchone()
                if row is None:
                    return None, ""
                current_status = str(row["status"] or "").strip() or "queued"
                current_stage = str(row["stage"] or "").strip()
                if current_stage == "cancelled":
                    cancel_mode = "already_cancelled"

        if not cancel_mode and current_status == "running":
            cursor = conn.execute(
                """
                UPDATE manual_submissions
                SET status = ?,
                    stage = ?,
                    error = ?,
                    finished_at = ?,
                    updated_at = ?
                WHERE id = ?
                  AND status = ?
                  AND stage != 'cancelled'
                """,
                (
                    "error",
                    "cancelled",
                    "Stopped local tracking while the webhook request was already running. The remote workflow may still finish.",
                    now,
                    now,
                    submission_id,
                    "running",
                ),
            )
            if cursor.rowcount > 0:
                cancel_mode = "detached_running_request"

        if not cancel_mode:
            cancel_mode = "not_cancellable"

    return get_manual_submission(settings, submission_id), cancel_mode


def record_qdrant_delete_detail(
    settings: Settings,
    submission_id: int,
    detail: dict[str, Any],
) -> dict[str, Any]:
    now = utc_now()
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            UPDATE manual_submissions
            SET qdrant_delete_detail = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                json.dumps(detail, ensure_ascii=False, sort_keys=True),
                now,
                submission_id,
            ),
        )

    return get_manual_submission(settings, submission_id)


def get_manual_submission(settings: Settings, submission_id: int) -> dict[str, Any] | None:
    with connect(settings.db_path) as conn:
        row = conn.execute(
            """
            SELECT
                id,
                request_url,
                request_payload_json,
                status,
                stage,
                error,
                response_json,
                rerun_of_submission_id,
                qdrant_delete_detail,
                created_at,
                started_at,
                finished_at,
                updated_at
            FROM manual_submissions
            WHERE id = ?
            LIMIT 1
            """,
            (submission_id,),
        ).fetchone()

    if row is None:
        return None
    return _normalize_manual_submission_row(row)


def list_recent_manual_submissions(
    settings: Settings,
    *,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    final_limit = limit or settings.manual_submission_history_limit
    with connect(settings.db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                request_url,
                request_payload_json,
                status,
                stage,
                error,
                response_json,
                rerun_of_submission_id,
                qdrant_delete_detail,
                created_at,
                started_at,
                finished_at,
                updated_at
            FROM manual_submissions
            ORDER BY created_at DESC, id DESC
            LIMIT ?
            """,
            (final_limit,),
        ).fetchall()

    return [_normalize_manual_submission_row(row) for row in rows]


def find_latest_manual_submission_match(
    settings: Settings,
    *,
    request_url: str,
    normalized_url: str,
    resolved_url: str,
    canonical_url: str,
) -> tuple[dict[str, Any] | None, str]:
    candidate_urls = {
        "request_url": normalize_url_for_match(request_url),
        "normalized_url": normalize_url_for_match(normalized_url),
        "resolved_url": normalize_url_for_match(resolved_url),
        "canonical_url": normalize_url_for_match(canonical_url),
    }

    exact_request_url = candidate_urls["request_url"] or candidate_urls["normalized_url"]
    if exact_request_url:
        exact_match = _find_manual_submission_match_by_urls(
            settings,
            {"request_url": exact_request_url},
        )
        if exact_match is not None:
            matched_submission, _ = exact_match
            return matched_submission, "request_url"

    secondary_urls = {
        key: value
        for key, value in candidate_urls.items()
        if key in {"resolved_url", "canonical_url"} and value and value != exact_request_url
    }
    secondary_match = _find_manual_submission_match_by_urls(settings, secondary_urls)
    if secondary_match is None:
        return None, ""

    matched_submission, match_reason = secondary_match
    return matched_submission, match_reason


def _find_manual_submission_match_by_urls(
    settings: Settings,
    candidate_urls: dict[str, str],
) -> tuple[dict[str, Any], str] | None:
    if not candidate_urls:
        return None

    with connect(settings.db_path) as conn:
        rows = conn.execute(
            """
            SELECT
                id,
                request_url,
                request_payload_json,
                status,
                stage,
                error,
                response_json,
                rerun_of_submission_id,
                qdrant_delete_detail,
                created_at,
                started_at,
                finished_at,
                updated_at
            FROM manual_submissions
            ORDER BY created_at DESC, id DESC
            """
        ).fetchall()

    normalized_targets = {
        reason: normalize_url_for_match(url)
        for reason, url in candidate_urls.items()
        if normalize_url_for_match(url)
    }
    if not normalized_targets:
        return None

    for row in rows:
        submission = _normalize_manual_submission_row(row)
        if submission["status"] not in PRECHECK_ELIGIBLE_STATUSES:
            continue

        request_url = normalize_url_for_match(submission["request_url"])
        canonical_url = normalize_url_for_match(submission["canonical_url"])

        for reason, target_url in normalized_targets.items():
            if reason == "request_url" and target_url == request_url:
                return submission, reason
            if reason != "request_url" and (
                target_url == request_url or (canonical_url and target_url == canonical_url)
            ):
                return submission, reason

    return None


def get_dashboard_data(settings: Settings) -> dict[str, Any]:
    with connect(settings.db_path) as conn:
        summary = conn.execute(
            """
            SELECT
                COUNT(*) AS collection_count,
                COALESCE((
                    SELECT COUNT(*)
                    FROM subscriptions
                    WHERE status != 'archived'
                ), 0) AS subscription_count,
                COALESCE((
                    SELECT COUNT(*)
                    FROM subscriptions
                    WHERE status = 'active'
                ), 0) AS active_subscription_count,
                COALESCE((
                    SELECT COUNT(DISTINCT platform)
                    FROM subscriptions
                    WHERE status != 'archived'
                ), 0) AS platform_count
            FROM collections
            WHERE status != 'archived'
            """
        ).fetchone()

        collection_rows = conn.execute(
            """
            SELECT
                c.id,
                c.name,
                c.slug,
                c.description,
                c.status,
                c.sort_order,
                c.created_at,
                c.updated_at,
                COUNT(s.id) AS subscription_count,
                COALESCE(SUM(CASE WHEN s.status = 'active' THEN 1 ELSE 0 END), 0)
                    AS active_subscription_count
            FROM collections AS c
            LEFT JOIN subscriptions AS s
                ON s.collection_id = c.id
                AND s.status != 'archived'
            WHERE c.status != 'archived'
            GROUP BY c.id
            ORDER BY c.sort_order ASC, c.id ASC
            """
        ).fetchall()

        collections: list[dict[str, Any]] = []
        for row in collection_rows:
            subscriptions = conn.execute(
                """
                SELECT
                    id,
                    display_name,
                    platform,
                    source_type,
                    source_url,
                    resolved_url,
                    ingest_url,
                    status,
                    updated_at
                FROM subscriptions
                WHERE collection_id = ?
                  AND status != 'archived'
                ORDER BY
                    CASE status
                        WHEN 'active' THEN 0
                        WHEN 'disabled' THEN 1
                        ELSE 2
                    END,
                    updated_at DESC,
                    id DESC
                LIMIT 20
                """,
                (row["id"],),
            ).fetchall()

            collections.append(
                {
                    "id": row["id"],
                    "name": row["name"],
                    "slug": row["slug"],
                    "description": row["description"],
                    "status": row["status"],
                    "subscription_count": row["subscription_count"],
                    "active_subscription_count": row["active_subscription_count"],
                    "updated_at": row["updated_at"],
                    "subscriptions": [dict(subscription) for subscription in subscriptions],
                }
            )

        platform_rows = conn.execute(
            """
            SELECT
                s.id,
                s.display_name,
                s.platform,
                s.source_type,
                s.source_url,
                s.resolved_url,
                s.ingest_url,
                s.status,
                s.updated_at,
                c.name AS collection_name
            FROM subscriptions AS s
            JOIN collections AS c
              ON c.id = s.collection_id
            WHERE s.status != 'archived'
              AND c.status != 'archived'
            ORDER BY
                s.platform ASC,
                CASE s.status
                    WHEN 'active' THEN 0
                    WHEN 'disabled' THEN 1
                    ELSE 2
                END,
                s.updated_at DESC,
                s.id DESC
            """
        ).fetchall()

    platform_groups_map: dict[str, dict[str, Any]] = {}
    for row in platform_rows:
        platform = row["platform"]
        group = platform_groups_map.setdefault(
            platform,
            {
                "platform": platform,
                "label": PLATFORM_LABELS.get(platform, platform),
                "subscription_count": 0,
                "active_subscription_count": 0,
                "subscriptions": [],
            },
        )
        group["subscription_count"] += 1
        if row["status"] == "active":
            group["active_subscription_count"] += 1
        subscription = dict(row)
        subscription["platform_label"] = PLATFORM_LABELS.get(platform, platform)
        group["subscriptions"].append(subscription)

    platform_groups = sorted(
        platform_groups_map.values(),
        key=lambda item: item["label"],
    )

    recent_manual_submissions = list_recent_manual_submissions(
        settings,
        limit=settings.manual_submission_history_limit,
    )
    active_manual_submission_count = sum(
        1 for item in recent_manual_submissions if item["is_active"]
    )

    return {
        "summary": {
            "collection_count": summary["collection_count"],
            "subscription_count": summary["subscription_count"],
            "active_subscription_count": summary["active_subscription_count"],
            "platform_count": summary["platform_count"],
        },
        "collections": collections,
        "platform_groups": platform_groups,
        "manual_submissions": recent_manual_submissions,
        "manual_submission_summary": {
            "recent_count": len(recent_manual_submissions),
            "active_count": active_manual_submission_count,
        },
    }
