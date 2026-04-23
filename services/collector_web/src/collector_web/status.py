import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from .config import Settings
from .db import connect, utc_now
from .qdrant import QdrantOperationError, get_collection_snapshot
from .repository import list_recent_manual_submissions

STATUS_LABELS = {
    "success": "正常",
    "muted": "未接入",
    "accent": "处理中",
    "action": "待处理",
    "warning": "需关注",
    "error": "异常",
}

STATUS_PRIORITY = {
    "success": 0,
    "muted": 1,
    "accent": 2,
    "action": 3,
    "warning": 4,
    "error": 5,
}


def _parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value)
    except ValueError:
        return None


def _format_datetime(value: str | None) -> str:
    if not value:
        return ""

    parsed = _parse_datetime(value)
    if parsed is None:
        return value

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


def _build_check(
    check_id: str,
    title: str,
    tone: str,
    summary: str,
    detail_lines: list[str],
    *,
    affects_overall: bool = True,
) -> dict[str, Any]:
    return {
        "id": check_id,
        "title": title,
        "status_tone": tone,
        "status_label": STATUS_LABELS.get(tone, tone),
        "summary": summary,
        "detail_lines": detail_lines,
        "affects_overall": affects_overall,
    }


def _build_collector_status(settings: Settings) -> dict[str, Any]:
    try:
        with connect(settings.db_path) as conn:
            collection_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM collections WHERE status != 'archived'"
                ).fetchone()[0]
            )
            subscription_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM subscriptions WHERE status != 'archived'"
                ).fetchone()[0]
            )
            active_subscription_count = int(
                conn.execute(
                    "SELECT COUNT(*) FROM subscriptions WHERE status = 'active'"
                ).fetchone()[0]
            )
            manual_submission_count = int(
                conn.execute("SELECT COUNT(*) FROM manual_submissions").fetchone()[0]
            )
    except Exception as exc:
        return _build_check(
            "collector_web",
            "Collector Web",
            "error",
            "本地数据库不可读，当前页面不能作为可靠控制台。",
            [
                f"数据库路径: {settings.db_path}",
                f"错误: {exc}",
            ],
        )

    return _build_check(
        "collector_web",
        "Collector Web",
        "success",
        "本地数据库可读，首页和手动提交页依赖的数据都能正常加载。",
        [
            f"数据库路径: {settings.db_path}",
            f"集合 {collection_count} 个，订阅 {subscription_count} 个，启用中 {active_subscription_count} 个",
            f"手动提交历史 {manual_submission_count} 条",
        ],
    )


def _find_latest_poll_run_file(poll_runs_dir: Path) -> Path | None:
    if not poll_runs_dir.exists():
        return None

    candidates = poll_runs_dir.rglob("*_01_rss_to_obsidian_raw.json")
    return max(candidates, key=lambda item: item.stat().st_mtime, default=None)


def _build_rss_poll_status(settings: Settings) -> tuple[dict[str, Any], dict[str, Any]]:
    latest_file = _find_latest_poll_run_file(settings.poll_runs_dir)
    if latest_file is None:
        tone = "warning" if settings.poll_runs_dir.exists() else "muted"
        summary = (
            "还没有发现 RSS 轮询摘要。"
            if settings.poll_runs_dir.exists()
            else "当前实例没有接入 RSS 轮询摘要目录。"
        )
        check = _build_check(
            "rss_poll",
            "RSS 主链",
            tone,
            summary,
            [
                f"poll_runs 目录: {settings.poll_runs_dir}",
            ],
        )
        return check, {
            "finished_at": "暂无",
            "items_written": 0,
        }

    try:
        payload = json.loads(latest_file.read_text(encoding="utf-8"))
    except Exception as exc:
        check = _build_check(
            "rss_poll",
            "RSS 主链",
            "error",
            "找到了最新轮询摘要，但当前无法读取或解析。",
            [
                f"摘要文件: {latest_file}",
                f"错误: {exc}",
            ],
        )
        return check, {
            "finished_at": "读取失败",
            "items_written": 0,
        }

    run_finished_at = str(payload.get("run_finished_at", "")).strip()
    source_count = int(payload.get("source_count", 0) or 0)
    success_source_count = int(payload.get("success_source_count", 0) or 0)
    failed_source_count = int(payload.get("failed_source_count", 0) or 0)
    items_seen = int(payload.get("items_seen", 0) or 0)
    items_written = int(payload.get("items_written", 0) or 0)
    age_minutes = _minutes_since(run_finished_at)

    failed_sources: list[str] = []
    wrote_paths: list[str] = []
    for source in payload.get("sources", []):
        if not isinstance(source, dict):
            continue
        source_name = str(source.get("source_name", "")).strip()
        feed_url = str(source.get("feed_url", "")).strip()
        rss_error = str(source.get("rss_error", "")).strip()
        if rss_error:
            failed_sources.append(source_name or feed_url or "未命名订阅源")

        source_paths = source.get("wrote_paths", [])
        if isinstance(source_paths, list):
            for item in source_paths:
                path = str(item).strip()
                if path:
                    wrote_paths.append(path)

    if failed_source_count > 0:
        tone = "warning"
        summary = f"最近一轮 RSS 轮询有 {failed_source_count} 个订阅源失败。"
    elif age_minutes is not None and age_minutes > settings.rss_poll_stale_minutes:
        tone = "warning"
        summary = "最近一轮 RSS 轮询时间偏旧，建议确认 n8n 定时链路是否还在跑。"
    else:
        tone = "success"
        summary = "最近一轮 RSS 轮询摘要可读，主链看起来仍在工作。"

    detail_lines = [
        f"最近一轮结束于: {_format_datetime(run_finished_at) or '未知'}",
        f"检查 {source_count} 个源，成功 {success_source_count} 个，失败 {failed_source_count} 个",
        f"本轮看到 {items_seen} 条 item，最终写入 {items_written} 条",
        f"摘要文件: {latest_file}",
    ]
    if age_minutes is not None:
        detail_lines.insert(1, f"距现在约 {age_minutes} 分钟")
    if failed_sources:
        detail_lines.append(f"失败源: {', '.join(failed_sources[:3])}")
    if wrote_paths:
        detail_lines.append(f"最近写入: {', '.join(wrote_paths[:2])}")

    return _build_check("rss_poll", "RSS 主链", tone, summary, detail_lines), {
        "finished_at": _format_datetime(run_finished_at) or "未知",
        "items_written": items_written,
    }


def _build_manual_submit_status(settings: Settings) -> tuple[dict[str, Any], dict[str, Any]]:
    recent_submissions = list_recent_manual_submissions(
        settings,
        limit=settings.manual_submission_history_limit,
    )
    active_count = sum(1 for item in recent_submissions if item["is_active"])
    latest_submission = recent_submissions[0] if recent_submissions else None

    parsed_webhook = urlparse(settings.manual_media_submit_url)
    webhook_target = (
        f"{parsed_webhook.scheme}://{parsed_webhook.netloc}"
        if parsed_webhook.scheme and parsed_webhook.netloc
        else settings.manual_media_submit_url
    )

    if latest_submission is None:
        tone = "muted"
        summary = "手动提交通道已经配置，但当前还没有历史记录。"
        detail_lines = [
            f"Webhook 目标: {webhook_target}",
            f"Webhook 路径: {parsed_webhook.path or '/'}",
            "最近手动提交: 暂无",
        ]
        affects_overall = False
    elif active_count > 0:
        tone = "accent"
        summary = f"当前有 {active_count} 条手动提交仍在处理中。"
        detail_lines = [
            f"最近提交 #{latest_submission['id']}: {latest_submission['status_label']}",
            f"时间: {_format_datetime(latest_submission['created_at'])}",
            f"URL: {latest_submission['request_url']}",
            f"Webhook 目标: {webhook_target}",
        ]
        affects_overall = False
    elif latest_submission["status"] == "needs_confirmation":
        tone = "action"
        summary = "最近一条手动提交需要人工确认，但这不表示提交通道本身异常。"
        detail_lines = [
            f"最近提交 #{latest_submission['id']}: {latest_submission['status_label']}",
            f"时间: {_format_datetime(latest_submission['created_at'])}",
            f"URL: {latest_submission['request_url']}",
            f"去重动作: {latest_submission['dedupe_action'] or 'silent'}",
        ]
        if latest_submission["item_id"]:
            detail_lines.append(f"item_id: {latest_submission['item_id']}")
        if latest_submission["can_delete_vector_and_rerun"]:
            detail_lines.append("下一步: 可直接去手动提交页执行“删除旧向量并重跑”")
        affects_overall = False
    elif latest_submission["status"] == "cancelled":
        tone = "muted"
        summary = "最近一条手动提交已经取消，当前没有待你处理的异常。"
        detail_lines = [
            f"最近提交 #{latest_submission['id']}: {latest_submission['status_label']}",
            f"时间: {_format_datetime(latest_submission['created_at'])}",
            f"URL: {latest_submission['request_url']}",
        ]
        if latest_submission["cancellation_note"]:
            detail_lines.append(f"说明: {latest_submission['cancellation_note']}")
        affects_overall = False
    elif latest_submission["status"] == "error":
        tone = "warning"
        summary = "最近一次手动提交失败，建议直接从这里回看错误信息。"
        detail_lines = [
            f"最近提交 #{latest_submission['id']}: {latest_submission['status_label']}",
            f"时间: {_format_datetime(latest_submission['created_at'])}",
            f"URL: {latest_submission['request_url']}",
            f"错误: {latest_submission['error'] or '未知错误'}",
        ]
        affects_overall = True
    else:
        tone = latest_submission["status_tone"]
        summary = "手动提交通道可用，可以从状态和历史里直接回看最近一次结果。"
        detail_lines = [
            f"最近提交 #{latest_submission['id']}: {latest_submission['status_label']}",
            f"时间: {_format_datetime(latest_submission['created_at'])}",
            f"URL: {latest_submission['request_url']}",
            f"Webhook 目标: {webhook_target}",
        ]
        if latest_submission["vault_path"]:
            detail_lines.append(f"最近写入路径: {latest_submission['vault_path']}")
        if latest_submission["dedupe_action"]:
            detail_lines.append(f"去重动作: {latest_submission['dedupe_action']}")
        affects_overall = False

    check = _build_check(
        "manual_submit",
        "手动提交通道",
        tone,
        summary,
        detail_lines,
        affects_overall=affects_overall,
    )
    return check, {
        "active_count": active_count,
        "recent_count": len(recent_submissions),
        "latest_status_label": latest_submission["status_label"] if latest_submission else "暂无",
        "latest_status_tone": latest_submission["status_tone"] if latest_submission else "muted",
        "latest_created_at": _format_datetime(latest_submission["created_at"]) if latest_submission else "暂无",
    }


def _build_qdrant_status(settings: Settings) -> dict[str, Any]:
    try:
        snapshot = get_collection_snapshot(settings)
    except QdrantOperationError as exc:
        return _build_check(
            "qdrant",
            "Qdrant",
            "error",
            "向量库不可达，手动删除旧向量和去重相关能力都会受影响。",
            [
                f"Qdrant: {settings.qdrant_base_url}",
                f"Collection: {settings.qdrant_collection}",
                f"错误: {exc}",
            ],
        )

    detail_lines = [
        f"Qdrant: {snapshot['qdrant_base_url']}",
        f"Collection: {snapshot['qdrant_collection']}",
        f"当前点数: {snapshot['points_count']}",
        f"状态: {snapshot['status']} / {snapshot['optimizer_status']}",
    ]
    if snapshot["vector_size"] is not None:
        detail_lines.append(f"向量维度: {snapshot['vector_size']}")
    if snapshot["distance"]:
        detail_lines.append(f"距离函数: {snapshot['distance']}")

    return _build_check(
        "qdrant",
        "Qdrant",
        "success",
        "向量库和目标 collection 可达，去重链路的基础依赖在线。",
        detail_lines,
    )


def _build_overall_status(checks: list[dict[str, Any]]) -> dict[str, str]:
    overall_checks = [check for check in checks if check.get("affects_overall", True)]
    overall_tone = max(
        (check["status_tone"] for check in overall_checks),
        key=lambda item: STATUS_PRIORITY.get(item, -1),
        default="muted",
    )
    issues = [
        check["title"]
        for check in overall_checks
        if STATUS_PRIORITY.get(check["status_tone"], 0) >= 3
    ]

    if overall_tone == "error":
        summary = f"关键链路存在异常，优先看: {', '.join(issues[:2])}"
        label = "异常"
    elif overall_tone == "warning":
        summary = f"系统可以看到状态，但有链路需要留意: {', '.join(issues[:2])}"
        label = "需关注"
    elif overall_tone == "accent":
        summary = "当前有任务正在处理中，整体链路看起来仍然可用。"
        label = "处理中"
    elif overall_tone == "success":
        summary = "数据库、RSS 主链和向量库都能给出有效状态。"
        label = "运行正常"
    else:
        summary = "基础配置已经加载，但还缺少足够的运行证据。"
        label = "待补充"

    return {
        "status_tone": overall_tone,
        "status_label": label,
        "summary": summary,
    }


def get_service_status(settings: Settings) -> dict[str, Any]:
    collector_check = _build_collector_status(settings)
    rss_poll_check, rss_poll_summary = _build_rss_poll_status(settings)
    manual_submit_check, manual_submit_summary = _build_manual_submit_status(settings)
    qdrant_check = _build_qdrant_status(settings)

    checks = [
        collector_check,
        rss_poll_check,
        manual_submit_check,
        qdrant_check,
    ]

    config_items = [
        {
            "label": "Collector Web 数据库",
            "value": str(settings.db_path),
        },
        {
            "label": "手动提交 webhook",
            "value": settings.manual_media_submit_url,
        },
        {
            "label": "Qdrant base URL",
            "value": settings.qdrant_base_url,
        },
        {
            "label": "Qdrant collection",
            "value": settings.qdrant_collection,
        },
        {
            "label": "RSS 轮询摘要目录",
            "value": str(settings.poll_runs_dir),
        },
    ]

    return {
        "generated_at": utc_now(),
        "overall": _build_overall_status(checks),
        "checks": checks,
        "metrics": {
            "rss_poll_finished_at": rss_poll_summary["finished_at"],
            "rss_poll_items_written": rss_poll_summary["items_written"],
            "manual_submit_recent_count": manual_submit_summary["recent_count"],
            "manual_submit_active_count": manual_submit_summary["active_count"],
            "manual_submit_latest_status_label": manual_submit_summary["latest_status_label"],
            "manual_submit_latest_status_tone": manual_submit_summary["latest_status_tone"],
            "manual_submit_latest_created_at": manual_submit_summary["latest_created_at"],
        },
        "config_items": config_items,
        "links": {
            "health_json": "/health",
            "status_api": "/api/status",
            "manual_submit": "/manual-media-submit",
        },
    }
