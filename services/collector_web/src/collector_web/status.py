import json
import sqlite3
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse

from .config import Settings
from .db import connect, utc_now
from .mainline_llm import get_mainline_llm_status
from .poll_run_files import find_latest_poll_run_file
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

RSS_WORKFLOW_ID = "D3a7Kp9Lm4Qx2Rst"


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


def _to_int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def _as_string_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(item).strip() for item in value if str(item).strip()]


def _source_status_label(value: str) -> str:
    return {
        "success": "正常",
        "error": "失败",
        "pending": "等待中",
        "not_requested": "未请求",
    }.get(value, value or "未知")


def _explain_poll_source(source: dict[str, Any]) -> tuple[str, str]:
    rss_error = str(source.get("rss_error", "")).strip()
    transcript_error = str(source.get("transcript_error", "")).strip()
    item_count = _to_int(source.get("item_count"))
    new_item_count = _to_int(source.get("new_item_count"))
    wrote_count = _to_int(source.get("wrote_count"))
    gate_status = str(source.get("source_gate_status", "")).strip()
    is_new_since_last_poll = bool(source.get("is_new_since_last_poll"))
    dedupe_actions = _as_string_list(source.get("dedupe_actions"))
    vault_write_statuses = _as_string_list(source.get("vault_write_statuses"))

    if rss_error:
        return "error", f"RSS 拉取失败: {rss_error}"
    if transcript_error:
        return "error", f"转写失败: {transcript_error}"
    if wrote_count > 0:
        return "success", f"已写入 {wrote_count} 条，Qdrant 提交 {_to_int(source.get('qdrant_commit_count'))} 条。"
    if "silent" in dedupe_actions:
        return "muted", "下游判定为 silent 去重，未写入 Obsidian。"
    if vault_write_statuses and not any(status == "written" for status in vault_write_statuses):
        return "muted", f"Vault writer 返回 {', '.join(vault_write_statuses[:3])}，未产生新笔记。"
    if new_item_count > 0:
        return (
            "warning",
            "本源有新 item 进入处理，但本轮摘要没有记录最终写入原因；需要看 audit 或下一版 poll_runs 的下游决策字段。",
        )
    if item_count == 0:
        return "muted", "RSS 请求成功，但本轮没有返回 item。"
    if gate_status == "unchanged" or not is_new_since_last_poll:
        return "muted", "source_last_seen 判断最新内容未变化，所以没有进入下游处理。"
    return "muted", "本轮没有产生新的 Obsidian 写入。"


def _build_poll_source_rows(payload: dict[str, Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for source in payload.get("sources", []):
        if not isinstance(source, dict):
            continue
        tone, explanation = _explain_poll_source(source)
        rows.append(
            {
                "source_name": str(source.get("source_name", "")).strip() or "未命名订阅源",
                "source_type": str(source.get("source_type", "")).strip() or "unknown",
                "feed_url": str(source.get("feed_url", "")).strip(),
                "rss_status": str(source.get("rss_status", "")).strip() or "unknown",
                "rss_status_label": _source_status_label(str(source.get("rss_status", "")).strip()),
                "transcript_status": str(source.get("transcript_status", "")).strip() or "unknown",
                "transcript_status_label": _source_status_label(
                    str(source.get("transcript_status", "")).strip()
                ),
                "source_gate_status": str(source.get("source_gate_status", "")).strip() or "not_checked",
                "item_count": _to_int(source.get("item_count")),
                "new_item_count": _to_int(source.get("new_item_count")),
                "wrote_count": _to_int(source.get("wrote_count")),
                "qdrant_commit_count": _to_int(source.get("qdrant_commit_count")),
                "is_new_since_last_poll": bool(source.get("is_new_since_last_poll")),
                "current_latest_title": str(source.get("current_latest_title", "")).strip(),
                "sample_titles": _as_string_list(source.get("sample_titles"))[:3],
                "new_titles": _as_string_list(source.get("new_titles"))[:3],
                "wrote_paths": _as_string_list(source.get("wrote_paths"))[:3],
                "dedupe_actions": _as_string_list(source.get("dedupe_actions"))[:3],
                "vault_write_statuses": _as_string_list(source.get("vault_write_statuses"))[:3],
                "tone": tone,
                "explanation": explanation,
            }
        )
    return rows


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


def _execution_status_label(value: str) -> str:
    return {
        "success": "成功",
        "running": "运行中",
        "error": "失败",
        "crashed": "崩溃",
        "waiting": "等待中",
        "new": "待启动",
    }.get(value, value or "未知")


def _compact_text(value: Any, *, limit: int = 220) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: limit - 3].rstrip()}..."


def _decode_n8n_serialized_payload(raw: str) -> Any:
    values = json.loads(raw)
    if not isinstance(values, list):
        return values

    resolving: set[int] = set()
    cache: dict[int, Any] = {}

    def revive_ref(index: int) -> Any:
        if index in cache:
            return cache[index]
        if index in resolving:
            return None
        resolving.add(index)
        value = values[index]
        if isinstance(value, dict):
            decoded: dict[str, Any] = {}
            cache[index] = decoded
            decoded.update({key: revive(item) for key, item in value.items()})
        elif isinstance(value, list):
            decoded_list: list[Any] = []
            cache[index] = decoded_list
            decoded_list.extend(revive(item) for item in value)
            decoded = decoded_list
        else:
            decoded = value
            cache[index] = decoded
        resolving.remove(index)
        return decoded

    def revive(value: Any) -> Any:
        if isinstance(value, str) and value.isdigit():
            index = int(value)
            if 0 <= index < len(values):
                return revive_ref(index)
        if isinstance(value, dict):
            return {key: revive(item) for key, item in value.items()}
        if isinstance(value, list):
            return [revive(item) for item in value]
        return value

    return revive_ref(0)


def _extract_execution_error(conn: sqlite3.Connection, execution_id: int) -> tuple[str, str]:
    row = conn.execute(
        "SELECT data FROM execution_data WHERE executionId = ? LIMIT 1",
        (execution_id,),
    ).fetchone()
    if row is None:
        return "", ""

    try:
        payload = _decode_n8n_serialized_payload(str(row["data"]))
    except Exception:
        return "", ""

    result_data = payload.get("resultData", {}) if isinstance(payload, dict) else {}
    last_node = _compact_text(result_data.get("lastNodeExecuted"), limit=80)
    error = result_data.get("error")
    if isinstance(error, dict):
        description = _compact_text(error.get("description"))
        message = _compact_text(error.get("message"))
        name = _compact_text(error.get("name"), limit=80)
        error_text = description or message or name
        if description and message and message not in description:
            error_text = f"{description}；{message}"
        return last_node, error_text

    if error:
        return last_node, _compact_text(error)

    run_data = result_data.get("runData", {})
    if isinstance(run_data, dict):
        for node_name, runs in run_data.items():
            if not isinstance(runs, list):
                continue
            for run in runs:
                if not isinstance(run, dict) or not run.get("error"):
                    continue
                node_error = run["error"]
                if isinstance(node_error, dict):
                    return (
                        _compact_text(node_name, limit=80),
                        _compact_text(
                            node_error.get("description")
                            or node_error.get("message")
                            or node_error.get("name")
                        ),
                    )
                return _compact_text(node_name, limit=80), _compact_text(node_error)

    return last_node, ""


def _build_execution_line(label: str, execution: dict[str, Any]) -> str:
    started_at = _format_datetime(str(execution.get("startedAt") or execution.get("createdAt") or ""))
    stopped_at = _format_datetime(str(execution.get("stoppedAt") or ""))
    status = str(execution.get("status", "")).strip()
    line = (
        f"{label}: {started_at or '未知时间'} 已触发，"
        f"状态: {_execution_status_label(status)}（execution {execution.get('id')}）"
    )
    if stopped_at:
        line += f"，结束于 {stopped_at}"
    return line


def _build_rss_execution_status(settings: Settings) -> dict[str, Any]:
    db_path = settings.n8n_database_path
    if not db_path.exists():
        return {
            "detail_lines": [
                f"调度执行记录: 未接入 n8n 数据库，只能显示 poll_runs 摘要（期望路径: {db_path}）",
            ],
            "recent_executions": [],
        }

    db_uri = f"file:{db_path.as_posix()}?mode=ro"
    try:
        with sqlite3.connect(db_uri, uri=True) as conn:
            conn.row_factory = sqlite3.Row
            rows = [
                dict(row)
                for row in conn.execute(
                    """
                    SELECT id, workflowId, finished, mode, startedAt, stoppedAt, status, createdAt
                    FROM execution_entity
                    WHERE workflowId = ?
                    ORDER BY id DESC
                    LIMIT 4
                    """,
                    (RSS_WORKFLOW_ID,),
                ).fetchall()
            ]
            for execution in rows:
                if str(execution.get("status", "")).strip() in {"success", "running"}:
                    continue
                node_name, error_text = _extract_execution_error(conn, int(execution["id"]))
                execution["error_node"] = node_name
                execution["error_text"] = error_text
    except Exception as exc:
        return {
            "detail_lines": [
                f"调度执行记录: n8n 数据库可见，但读取失败（{exc}）",
            ],
            "recent_executions": [],
        }

    if not rows:
        return {
            "detail_lines": ["调度执行记录: n8n 数据库可读，但没有找到 RSS 主链执行记录。"],
            "recent_executions": [],
        }

    detail_lines = [_build_execution_line("最近调度执行", rows[0])]
    if len(rows) > 1:
        detail_lines.append(_build_execution_line("上一轮调度执行", rows[1]))

    latest_problem = next(
        (
            execution
            for execution in rows[:3]
            if str(execution.get("status", "")).strip() not in {"success", "running"}
        ),
        None,
    )
    if latest_problem:
        error_node = str(latest_problem.get("error_node") or "").strip()
        error_text = str(latest_problem.get("error_text") or "").strip()
        if error_node or error_text:
            detail = "；".join(item for item in [error_node, error_text] if item)
            detail_lines.append(f"最近失败位置: {detail}")

    return {
        "detail_lines": detail_lines,
        "recent_executions": rows,
    }


def _build_rss_poll_status(settings: Settings) -> tuple[dict[str, Any], dict[str, Any]]:
    latest_file = find_latest_poll_run_file(settings.poll_runs_dir)
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
            "latest_file": "",
            "source_rows": [],
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
            "latest_file": str(latest_file),
            "source_rows": [],
        }

    run_finished_at = str(payload.get("run_finished_at", "")).strip()
    source_count = int(payload.get("source_count", 0) or 0)
    success_source_count = int(payload.get("success_source_count", 0) or 0)
    failed_source_count = int(payload.get("failed_source_count", 0) or 0)
    transcript_failed_source_count = int(
        payload.get("transcript_failed_source_count", 0) or 0
    )
    items_seen = int(payload.get("items_seen", 0) or 0)
    items_written = int(payload.get("items_written", 0) or 0)
    age_minutes = _minutes_since(run_finished_at)
    source_rows = _build_poll_source_rows(payload)
    execution_status = _build_rss_execution_status(settings)

    failed_sources: list[str] = []
    transcript_failed_sources: list[str] = []
    wrote_paths: list[str] = []
    for source in payload.get("sources", []):
        if not isinstance(source, dict):
            continue
        source_name = str(source.get("source_name", "")).strip()
        feed_url = str(source.get("feed_url", "")).strip()
        rss_error = str(source.get("rss_error", "")).strip()
        transcript_error = str(source.get("transcript_error", "")).strip()
        if rss_error:
            failed_sources.append(source_name or feed_url or "未命名订阅源")
        if transcript_error:
            transcript_failed_sources.append(source_name or feed_url or "未命名订阅源")

        source_paths = source.get("wrote_paths", [])
        if isinstance(source_paths, list):
            for item in source_paths:
                path = str(item).strip()
                if path:
                    wrote_paths.append(path)

    if failed_source_count > 0:
        tone = "warning"
        summary = f"最新 poll_runs 摘要有 {failed_source_count} 个订阅源失败；调度执行状态见明细。"
    elif transcript_failed_source_count > 0:
        tone = "warning"
        summary = f"最新 poll_runs 摘要有 {transcript_failed_source_count} 个转写源失败；调度执行状态见明细。"
    elif age_minutes is not None and age_minutes > settings.rss_poll_stale_minutes:
        tone = "warning"
        summary = "最新 poll_runs 摘要时间偏旧，请结合调度执行记录判断 n8n 是否仍在跑。"
    else:
        tone = "success"
        summary = "最新 poll_runs 摘要可读，主链看起来仍在工作。"

    detail_lines = [
        f"最新 poll_runs 摘要结束于: {_format_datetime(run_finished_at) or '未知'}",
        f"检查 {source_count} 个源，成功 {success_source_count} 个，失败 {failed_source_count} 个",
        f"本轮看到 {items_seen} 条 item，最终写入 {items_written} 条",
        f"摘要文件: {latest_file}",
    ]
    if age_minutes is not None:
        detail_lines.insert(1, f"摘要距现在约 {age_minutes} 分钟")
    detail_lines[2:2] = execution_status["detail_lines"]
    if failed_sources:
        detail_lines.append(f"失败源: {', '.join(failed_sources[:3])}")
    if transcript_failed_sources:
        detail_lines.append(f"转写失败源: {', '.join(transcript_failed_sources[:3])}")
    if wrote_paths:
        detail_lines.append(f"最近写入: {', '.join(wrote_paths[:2])}")

    return _build_check("rss_poll", "RSS 主链", tone, summary, detail_lines), {
        "finished_at": _format_datetime(run_finished_at) or "未知",
        "items_written": items_written,
        "latest_file": str(latest_file),
        "source_rows": source_rows,
        "recent_executions": execution_status["recent_executions"],
        "run_started_at": _format_datetime(str(payload.get("run_started_at", "")).strip()) or "",
        "run_finished_at_raw": run_finished_at,
        "source_count": source_count,
        "success_source_count": success_source_count,
        "failed_source_count": failed_source_count,
        "items_seen": items_seen,
        "items_selected_for_processing": int(payload.get("items_selected_for_processing", 0) or 0),
        "poll_runs_version": int(payload.get("poll_runs_version", 0) or 0),
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
    mainline_llm = get_mainline_llm_status(settings)

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
        {
            "label": "Mainline LLM live model",
            "value": mainline_llm["live_model"] or mainline_llm["configured_model"] or "not found",
        },
        {
            "label": "Mainline LLM thinking",
            "value": (
                mainline_llm["live_thinking_type"]
                or mainline_llm["configured_thinking_type"]
                or "not found"
            ),
        },
        {
            "label": "Mainline LLM reasoning",
            "value": (
                mainline_llm["live_reasoning_effort"]
                or mainline_llm["configured_reasoning_effort"]
                or "not found"
            ),
        },
        {
            "label": "Mainline LLM env",
            "value": mainline_llm["env_path"],
        },
        {
            "label": "RSS 手动重跑 webhook",
            "value": settings.rss_poll_rerun_url,
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
            "rss_poll_rerun": "/api/rss-poll/rerun",
            "mainline_llm_switch": "/api/mainline-llm/switch",
        },
        "mainline_llm": mainline_llm,
        "rss_poll": {
            "latest_file": rss_poll_summary.get("latest_file", ""),
            "run_started_at": rss_poll_summary.get("run_started_at", ""),
            "run_finished_at": rss_poll_summary.get("finished_at", ""),
            "run_finished_at_raw": rss_poll_summary.get("run_finished_at_raw", ""),
            "source_count": rss_poll_summary.get("source_count", 0),
            "success_source_count": rss_poll_summary.get("success_source_count", 0),
            "failed_source_count": rss_poll_summary.get("failed_source_count", 0),
            "items_seen": rss_poll_summary.get("items_seen", 0),
            "items_selected_for_processing": rss_poll_summary.get("items_selected_for_processing", 0),
            "items_written": rss_poll_summary.get("items_written", 0),
            "poll_runs_version": rss_poll_summary.get("poll_runs_version", 0),
            "source_rows": rss_poll_summary.get("source_rows", []),
            "recent_executions": rss_poll_summary.get("recent_executions", []),
        },
    }
