import json
import sqlite3
import time
import uuid
from dataclasses import dataclass
from typing import Any
from urllib import error, parse, request

from .config import Settings
from .db import connect, utc_now


class FeishuAppError(RuntimeError):
    pass


@dataclass
class _TokenCache:
    app_id: str = ""
    token: str = ""
    expires_at: float = 0


_TOKEN_CACHE = _TokenCache()


def _safe_string(value: Any) -> str:
    if value is None:
        return ""
    return str(value).strip()


def _truncate(value: Any, max_length: int = 500) -> str:
    text = " ".join(_safe_string(value).split())
    if len(text) <= max_length:
        return text
    return text[: max(0, max_length - 3)].strip() + "..."


def _first_non_empty(*values: Any) -> str:
    for value in values:
        text = _safe_string(value)
        if text:
            return text
    return ""


def _normalize_list(value: Any, *, max_items: int = 4, max_length: int = 220) -> list[str]:
    if isinstance(value, list):
        raw_items = value
    elif isinstance(value, str):
        raw_items = value.replace("\r", "\n").split("\n")
    else:
        raw_items = []

    normalized = []
    for item in raw_items:
        if len(normalized) >= max_items:
            break
        if isinstance(item, dict):
            text = _first_non_empty(
                item.get("heading"),
                item.get("title"),
                item.get("summary"),
                item.get("text"),
            )
            bullets = item.get("bullets") or item.get("points")
            if isinstance(bullets, list):
                bullet_text = "; ".join(_truncate(entry, 90) for entry in bullets if _safe_string(entry))
                text = ": ".join(part for part in [text, bullet_text] if part)
        else:
            text = _safe_string(item)
        text = _truncate(text, max_length)
        if text:
            normalized.append(text)
    return normalized


def _score_line(payload: dict[str, Any]) -> str:
    score = payload.get("ai_score") if isinstance(payload.get("ai_score"), dict) else {}

    def to_int(value: Any) -> str:
        try:
            return str(round(float(value)))
        except (TypeError, ValueError):
            return "-"

    keep_score = score.get("keep_score", payload.get("score"))
    notify_score = score.get("notify_score")
    reference_score = score.get("reference_score")
    action_score = score.get("action_score")
    return (
        f"Keep {to_int(keep_score)} / Notify {to_int(notify_score)} / "
        f"Reference {to_int(reference_score)} / Action {to_int(action_score)}"
    )


def _source_line(payload: dict[str, Any]) -> str:
    return " / ".join(
        part
        for part in [
            _safe_string(payload.get("source_type") or payload.get("media_type")),
            _safe_string(
                payload.get("source_display_name")
                or payload.get("source_name")
                or payload.get("author")
            ),
        ]
        if part
    )


def _button_open_url(label: str, url: str) -> dict[str, Any]:
    return {
        "tag": "button",
        "text": {"tag": "plain_text", "content": label},
        "type": "default",
        "width": "default",
        "size": "medium",
        "behaviors": [
            {
                "type": "open_url",
                "default_url": url,
                "pc_url": url,
                "ios_url": url,
                "android_url": url,
            }
        ],
    }


def build_compact_card(notification_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    title = _truncate(payload.get("title") or "Untitled", 120)
    quick_take = _truncate(
        _first_non_empty(payload.get("note_quick_take"), payload.get("quick_take"), payload.get("summary")),
        180,
    )
    source_line = _source_line(payload)
    canonical_url = _safe_string(payload.get("canonical_url"))
    lines = [
        f"**{title}**",
        f"**一句话判断**\n{quick_take}" if quick_take else "",
        f"**来源**: {source_line}" if source_line else "",
        f"**评分**: {_score_line(payload)}",
    ]
    actions = [
        {
            "tag": "button",
            "text": {"tag": "plain_text", "content": "展开完整卡片"},
            "type": "primary_filled",
            "width": "default",
            "size": "medium",
            "value": {
                "action": "show_full",
                "notification_id": notification_id,
            },
        }
    ]
    if canonical_url.startswith(("http://", "https://")):
        actions.append(_button_open_url("查看原文", canonical_url))

    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "wide_screen_mode": True,
            "summary": {"content": _truncate(f"AI推荐: {quick_take or title}", 120)},
        },
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "AI 推荐"},
            "padding": "12px 12px 12px 12px",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": [
                {
                    "tag": "markdown",
                    "element_id": "compact_summary",
                    "content": "\n\n".join(line for line in lines if line),
                    "text_align": "left",
                },
                {
                    "tag": "column_set",
                    "flex_mode": "none",
                    "background_style": "default",
                    "columns": [
                        {
                            "tag": "column",
                            "width": "weighted",
                            "weight": 1,
                            "elements": [action],
                        }
                        for action in actions
                    ],
                },
            ],
        },
    }


def build_full_card(payload: dict[str, Any]) -> dict[str, Any]:
    title = _truncate(payload.get("title") or "Untitled", 140)
    summary = _truncate(
        _first_non_empty(payload.get("summary"), payload.get("upstream_summary"), payload.get("note_quick_take")),
        1000,
    )
    why_useful = _truncate(
        _first_non_empty(payload.get("note_why_useful"), payload.get("why_useful"), payload.get("reason")),
        700,
    )
    presentation = payload.get("presentation") if isinstance(payload.get("presentation"), dict) else {}
    key_points = _normalize_list(
        payload.get("note_key_points") or payload.get("key_points") or presentation.get("key_points"),
        max_items=5,
        max_length=220,
    )
    canonical_url = _safe_string(payload.get("canonical_url"))
    vault_path = _safe_string(payload.get("vault_path") or payload.get("relativeFilePath"))
    source_line = _source_line(payload)
    key_point_text = "\n".join(f"- {point}" for point in key_points)
    lines = [
        f"**{title}**",
        f"**来源**: {source_line}" if source_line else "",
        f"**时间**: {_truncate(payload.get('published_at'), 80)}" if _safe_string(payload.get("published_at")) else "",
        f"**评分**: {_score_line(payload)}",
        f"**摘要**\n{summary}" if summary else "",
        f"**关键观点**\n{key_point_text}" if key_point_text else "",
        f"**为什么值得看**\n{why_useful}" if why_useful else "",
        f"**Obsidian**: {vault_path}" if vault_path else "",
    ]
    elements: list[dict[str, Any]] = [
        {
            "tag": "markdown",
            "element_id": "full_summary",
            "content": "\n\n".join(line for line in lines if line),
            "text_align": "left",
        }
    ]
    if canonical_url.startswith(("http://", "https://")):
        elements.append(_button_open_url("查看原文", canonical_url))

    return {
        "schema": "2.0",
        "config": {
            "update_multi": True,
            "wide_screen_mode": True,
            "summary": {"content": _truncate(f"完整摘要: {title}", 120)},
        },
        "header": {
            "template": "blue",
            "title": {"tag": "plain_text", "content": "AI 信息摘要"},
            "padding": "12px 12px 12px 12px",
        },
        "body": {
            "direction": "vertical",
            "padding": "12px 12px 12px 12px",
            "elements": elements,
        },
    }


def _post_json(
    settings: Settings,
    path: str,
    payload: dict[str, Any],
    *,
    bearer_token: str | None = None,
) -> dict[str, Any]:
    url = settings.feishu_api_base_url.rstrip("/") + path
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    headers = {"Content-Type": "application/json; charset=utf-8"}
    if bearer_token:
        headers["Authorization"] = f"Bearer {bearer_token}"
    req = request.Request(url, data=body, headers=headers, method="POST")
    try:
        with request.urlopen(req, timeout=settings.feishu_request_timeout_seconds) as response:
            raw_body = response.read().decode("utf-8", errors="replace")
    except error.HTTPError as exc:
        raw_body = exc.read().decode("utf-8", errors="replace")
        raise FeishuAppError(f"Feishu API returned HTTP {exc.code}: {_truncate(raw_body, 300)}") from exc
    except error.URLError as exc:
        raise FeishuAppError(f"Feishu API request failed: {exc.reason}") from exc

    try:
        parsed = json.loads(raw_body)
    except json.JSONDecodeError as exc:
        raise FeishuAppError(f"Feishu API returned non-JSON response: {_truncate(raw_body, 300)}") from exc
    if not isinstance(parsed, dict):
        raise FeishuAppError("Feishu API returned a non-object JSON response")
    code = parsed.get("code", parsed.get("StatusCode", 0))
    if code not in (0, None):
        message = parsed.get("msg", parsed.get("StatusMessage", "unknown error"))
        raise FeishuAppError(f"Feishu API error {code}: {_truncate(message, 300)}")
    return parsed


def _require_app_settings(settings: Settings) -> None:
    missing = [
        name
        for name, value in [
            ("FEISHU_APP_ID", settings.feishu_app_id),
            ("FEISHU_APP_SECRET", settings.feishu_app_secret),
            ("FEISHU_TARGET_CHAT_ID", settings.feishu_target_chat_id),
        ]
        if not value
    ]
    if missing:
        raise FeishuAppError("Missing Feishu app configuration: " + ", ".join(missing))


def get_tenant_access_token(settings: Settings) -> str:
    _require_app_settings(settings)
    now = time.time()
    if (
        _TOKEN_CACHE.app_id == settings.feishu_app_id
        and _TOKEN_CACHE.token
        and _TOKEN_CACHE.expires_at > now + 60
    ):
        return _TOKEN_CACHE.token

    response = _post_json(
        settings,
        "/open-apis/auth/v3/tenant_access_token/internal",
        {
            "app_id": settings.feishu_app_id,
            "app_secret": settings.feishu_app_secret,
        },
    )
    token = _safe_string(response.get("tenant_access_token"))
    if not token:
        raise FeishuAppError("Feishu token response did not include tenant_access_token")
    expire = int(response.get("expire", 7200) or 7200)
    _TOKEN_CACHE.app_id = settings.feishu_app_id
    _TOKEN_CACHE.token = token
    _TOKEN_CACHE.expires_at = now + max(60, expire)
    return token


def send_card_message(
    settings: Settings,
    *,
    chat_id: str,
    card: dict[str, Any],
    idempotency_key: str,
) -> dict[str, Any]:
    token = get_tenant_access_token(settings)
    query = parse.urlencode({"receive_id_type": "chat_id"})
    return _post_json(
        settings,
        f"/open-apis/im/v1/messages?{query}",
        {
            "receive_id": chat_id,
            "msg_type": "interactive",
            "content": json.dumps(card, ensure_ascii=False),
            "uuid": idempotency_key,
        },
        bearer_token=token,
    )


def _extract_message_id(response: dict[str, Any]) -> str:
    data = response.get("data") if isinstance(response.get("data"), dict) else {}
    return _safe_string(data.get("message_id") or data.get("message", {}).get("message_id"))


def _insert_notification(
    settings: Settings,
    notification_id: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    now = utc_now()
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            INSERT INTO feishu_app_notifications (
                notification_id,
                item_id,
                title,
                source_name,
                source_type,
                canonical_url,
                vault_path,
                payload_json,
                status,
                chat_id,
                created_at,
                updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                notification_id,
                _safe_string(payload.get("item_id") or payload.get("id")),
                _truncate(payload.get("title") or "Untitled", 300),
                _safe_string(payload.get("source_display_name") or payload.get("source_name") or payload.get("author")),
                _safe_string(payload.get("source_type") or payload.get("media_type")),
                _safe_string(payload.get("canonical_url")),
                _safe_string(payload.get("vault_path") or payload.get("relativeFilePath")),
                json.dumps(payload, ensure_ascii=False, sort_keys=True),
                "pending",
                settings.feishu_target_chat_id,
                now,
                now,
            ),
        )
    return get_notification(settings, notification_id) or {}


def _update_notification(
    settings: Settings,
    notification_id: str,
    *,
    status: str,
    request_payload: dict[str, Any] | None = None,
    response_payload: dict[str, Any] | None = None,
    message_id: str = "",
    error_message: str = "",
    expanded: bool = False,
) -> dict[str, Any]:
    now = utc_now()
    with connect(settings.db_path) as conn:
        conn.execute(
            """
            UPDATE feishu_app_notifications
            SET status = ?,
                message_id = COALESCE(NULLIF(?, ''), message_id),
                request_json = COALESCE(?, request_json),
                response_json = COALESCE(?, response_json),
                error = ?,
                sent_at = CASE WHEN ? = 'sent' AND sent_at IS NULL THEN ? ELSE sent_at END,
                expanded_at = CASE WHEN ? THEN ? ELSE expanded_at END,
                updated_at = ?
            WHERE notification_id = ?
            """,
            (
                status,
                message_id,
                json.dumps(request_payload, ensure_ascii=False, sort_keys=True)
                if request_payload is not None
                else None,
                json.dumps(response_payload, ensure_ascii=False, sort_keys=True)
                if response_payload is not None
                else None,
                error_message,
                status,
                now,
                1 if expanded else 0,
                now,
                now,
                notification_id,
            ),
        )
    return get_notification(settings, notification_id) or {}


def get_notification(settings: Settings, notification_id: str) -> dict[str, Any] | None:
    with connect(settings.db_path) as conn:
        row = conn.execute(
            """
            SELECT
                id,
                notification_id,
                item_id,
                title,
                source_name,
                source_type,
                canonical_url,
                vault_path,
                payload_json,
                status,
                chat_id,
                message_id,
                request_json,
                response_json,
                error,
                created_at,
                sent_at,
                expanded_at,
                updated_at
            FROM feishu_app_notifications
            WHERE notification_id = ?
            LIMIT 1
            """,
            (notification_id,),
        ).fetchone()
    if row is None:
        return None
    payload = dict(row)
    try:
        payload["notification_payload"] = json.loads(payload.pop("payload_json") or "{}")
    except json.JSONDecodeError:
        payload["notification_payload"] = {}
    for key in ("request_json", "response_json"):
        try:
            payload[key.replace("_json", "")] = json.loads(payload.pop(key) or "null")
        except json.JSONDecodeError:
            payload[key.replace("_json", "")] = None
    return payload


def send_compact_notification(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    _require_app_settings(settings)
    notification_id = _safe_string(payload.get("feishu_notification_id")) or uuid.uuid4().hex
    try:
        notification = _insert_notification(settings, notification_id, payload)
    except sqlite3.IntegrityError as exc:
        notification = get_notification(settings, notification_id)
        if notification is None:
            raise FeishuAppError(f"Feishu notification already exists: {notification_id}") from exc
        if notification.get("status") in {"sent", "expanded"}:
            return {
                "ok": True,
                "status": notification["status"],
                "delivery_mode": "feishu_app",
                "notification_id": notification_id,
                "message_id": notification.get("message_id", ""),
                "chat_id": notification.get("chat_id", ""),
                "title": notification.get("title", ""),
                "idempotent": True,
            }

    card = build_compact_card(notification_id, payload)
    request_payload = {
        "receive_id": settings.feishu_target_chat_id,
        "msg_type": "interactive",
        "content": card,
        "uuid": notification_id,
    }
    try:
        response = send_card_message(
            settings,
            chat_id=settings.feishu_target_chat_id,
            card=card,
            idempotency_key=notification_id,
        )
    except FeishuAppError as exc:
        _update_notification(
            settings,
            notification_id,
            status="failed",
            request_payload=request_payload,
            error_message=str(exc),
        )
        raise

    message_id = _extract_message_id(response)
    notification = _update_notification(
        settings,
        notification_id,
        status="sent",
        request_payload=request_payload,
        response_payload=response,
        message_id=message_id,
    )
    return {
        "ok": True,
        "status": "sent",
        "delivery_mode": "feishu_app",
        "notification_id": notification_id,
        "message_id": message_id,
        "chat_id": settings.feishu_target_chat_id,
        "title": notification.get("title", ""),
    }


def _extract_callback_action(payload: dict[str, Any]) -> dict[str, Any]:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    action = event.get("action") if isinstance(event.get("action"), dict) else {}
    value = action.get("value") if isinstance(action.get("value"), dict) else {}
    if value:
        return value
    return payload.get("action") if isinstance(payload.get("action"), dict) else {}


def _extract_callback_chat_id(payload: dict[str, Any], fallback: str) -> str:
    event = payload.get("event") if isinstance(payload.get("event"), dict) else {}
    candidates = [
        event.get("context", {}).get("open_chat_id") if isinstance(event.get("context"), dict) else "",
        event.get("open_chat_id"),
        event.get("chat_id"),
        event.get("message", {}).get("chat_id") if isinstance(event.get("message"), dict) else "",
        fallback,
    ]
    for candidate in candidates:
        text = _safe_string(candidate)
        if text:
            return text
    return fallback


def handle_card_action(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    if _safe_string(payload.get("challenge")):
        token = _safe_string(payload.get("token"))
        if settings.feishu_callback_verification_token and token != settings.feishu_callback_verification_token:
            raise FeishuAppError("Feishu callback verification token mismatch")
        return {"challenge": payload["challenge"]}

    action = _extract_callback_action(payload)
    action_name = _safe_string(action.get("action"))
    notification_id = _safe_string(action.get("notification_id"))
    if action_name != "show_full" or not notification_id:
        return {"toast": {"type": "info", "content": "这个按钮暂不需要处理"}}

    notification = get_notification(settings, notification_id)
    if notification is None:
        return {"toast": {"type": "warning", "content": "没有找到这条推荐的完整信息"}}

    full_card = build_full_card(notification.get("notification_payload") or {})
    chat_id = _extract_callback_chat_id(payload, _safe_string(notification.get("chat_id")) or settings.feishu_target_chat_id)
    response = send_card_message(
        settings,
        chat_id=chat_id,
        card=full_card,
        idempotency_key=f"{notification_id}-full",
    )
    _update_notification(
        settings,
        notification_id,
        status="expanded",
        response_payload={"expanded_response": response},
        expanded=True,
    )
    return {"toast": {"type": "success", "content": "完整卡片已发送"}}
