#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from debug_log import append_debug_log, default_debug_log_path


def utc_now_sql() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S.%f")[:-3]


def dumps_json(value: Any) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


def load_workflows(workflow_dir: Path, include_ids: set[str] | None) -> list[tuple[Path, dict[str, Any]]]:
    workflows: list[tuple[Path, dict[str, Any]]] = []
    for path in sorted(workflow_dir.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        workflow_id = str(data.get("id", "")).strip()
        if not workflow_id:
            raise ValueError(f"{path} is missing workflow id")
        if include_ids and workflow_id not in include_ids:
            continue
        workflows.append((path, data))
    if include_ids:
        missing = include_ids - {workflow["id"] for _, workflow in workflows}
        if missing:
            raise ValueError(f"Workflow ids not found in {workflow_dir}: {', '.join(sorted(missing))}")
    return workflows


def backup_database(conn: sqlite3.Connection, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup_path = backup_dir / f"n8n-main-{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}.sqlite"
    backup_conn = sqlite3.connect(backup_path)
    try:
        conn.backup(backup_conn)
    finally:
        backup_conn.close()
    return backup_path


def prune_backup_files(backup_dir: Path, retain: int) -> list[Path]:
    if retain < 0:
        raise ValueError(f"backup_retain must be >= 0, got {retain}")
    if retain == 0 or not backup_dir.exists():
        return []

    backup_files = sorted(
        (path for path in backup_dir.glob("n8n-main-*.sqlite") if path.is_file()),
        key=lambda path: (path.stat().st_mtime_ns, path.name),
        reverse=True,
    )

    removed: list[Path] = []
    for path in backup_files[retain:]:
        path.unlink()
        removed.append(path)
    return removed


def fetch_one(cursor: sqlite3.Cursor, query: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    cursor.execute(query, params)
    return cursor.fetchone()


def table_exists(cursor: sqlite3.Cursor, table_name: str) -> bool:
    row = fetch_one(
        cursor,
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    )
    return row is not None


def ensure_shared_workflow(
    cursor: sqlite3.Cursor,
    workflow_id: str,
    project_id: str,
    now: str,
) -> None:
    existing = fetch_one(
        cursor,
        "SELECT workflowId FROM shared_workflow WHERE workflowId = ? AND projectId = ?",
        (workflow_id, project_id),
    )
    if existing:
        cursor.execute(
            """
            UPDATE shared_workflow
            SET role = ?, updatedAt = ?
            WHERE workflowId = ? AND projectId = ?
            """,
            ("workflow:owner", now, workflow_id, project_id),
        )
        return

    cursor.execute(
        """
        INSERT INTO shared_workflow (workflowId, projectId, role, createdAt, updatedAt)
        VALUES (?, ?, ?, ?, ?)
        """,
        (workflow_id, project_id, "workflow:owner", now, now),
    )


def webhook_node_names(workflow: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for node in workflow.get("nodes", []):
        if node.get("type") == "n8n-nodes-base.webhook":
            name = str(node.get("name") or "").strip()
            if name:
                names.append(name)
    return names


def prune_webhook_rows(
    cursor: sqlite3.Cursor,
    workflow: dict[str, Any],
) -> list[dict[str, str]]:
    if not table_exists(cursor, "webhook_entity"):
        return []

    workflow_id = str(workflow["id"])
    expected_nodes = set(webhook_node_names(workflow))
    cursor.execute(
        """
        SELECT rowid, node, webhookPath, method
        FROM webhook_entity
        WHERE workflowId = ?
        ORDER BY rowid DESC
        """,
        (workflow_id,),
    )
    rows = cursor.fetchall()

    seen_nodes: set[str] = set()
    removed: list[dict[str, str]] = []
    for row in rows:
        node_name = str(row["node"] or "").strip()
        keep = bool(
            workflow.get("active")
            and node_name
            and node_name in expected_nodes
            and node_name not in seen_nodes
        )
        if keep:
            seen_nodes.add(node_name)
            continue

        cursor.execute("DELETE FROM webhook_entity WHERE rowid = ?", (row["rowid"],))
        removed.append(
            {
                "node": node_name,
                "webhookPath": str(row["webhookPath"] or ""),
                "method": str(row["method"] or ""),
            }
        )

    return removed


def ensure_published_version(
    cursor: sqlite3.Cursor,
    workflow_id: str,
    version_id: str,
    now: str,
    user_id: str | None,
) -> None:
    if not table_exists(cursor, "workflow_published_version"):
        return

    existing = fetch_one(
        cursor,
        "SELECT publishedVersionId FROM workflow_published_version WHERE workflowId = ?",
        (workflow_id,),
    )
    if existing:
        cursor.execute(
            """
            UPDATE workflow_published_version
            SET publishedVersionId = ?, updatedAt = ?
            WHERE workflowId = ?
            """,
            (version_id, now, workflow_id),
        )
    else:
        cursor.execute(
            """
            INSERT INTO workflow_published_version (workflowId, publishedVersionId, createdAt, updatedAt)
            VALUES (?, ?, ?, ?)
            """,
            (workflow_id, version_id, now, now),
        )

    if not table_exists(cursor, "workflow_publish_history"):
        return

    history = fetch_one(
        cursor,
        """
        SELECT id
        FROM workflow_publish_history
        WHERE workflowId = ? AND versionId = ? AND event = ?
        ORDER BY createdAt DESC
        LIMIT 1
        """,
        (workflow_id, version_id, "activated"),
    )
    if history:
        return

    cursor.execute(
        """
        INSERT INTO workflow_publish_history (workflowId, versionId, event, userId, createdAt)
        VALUES (?, ?, ?, ?, ?)
        """,
        (workflow_id, version_id, "activated", user_id, now),
    )


def remove_published_version(
    cursor: sqlite3.Cursor,
    workflow_id: str,
    version_id: str,
    now: str,
    user_id: str | None,
) -> None:
    if table_exists(cursor, "workflow_published_version"):
        cursor.execute(
            "DELETE FROM workflow_published_version WHERE workflowId = ?",
            (workflow_id,),
        )

    if not table_exists(cursor, "workflow_publish_history"):
        return

    history = fetch_one(
        cursor,
        """
        SELECT id
        FROM workflow_publish_history
        WHERE workflowId = ? AND versionId = ? AND event = ?
        ORDER BY createdAt DESC
        LIMIT 1
        """,
        (workflow_id, version_id, "deactivated"),
    )
    if history:
        return

    cursor.execute(
        """
        INSERT INTO workflow_publish_history (workflowId, versionId, event, userId, createdAt)
        VALUES (?, ?, ?, ?, ?)
        """,
        (workflow_id, version_id, "deactivated", user_id, now),
    )


def upsert_workflow_entity(
    cursor: sqlite3.Cursor,
    workflow: dict[str, Any],
    project_id: str,
    now: str,
) -> str:
    workflow_id = workflow["id"]
    version_id = str(workflow.get("versionId") or "").strip()
    if not version_id:
        raise ValueError(f"Workflow {workflow_id} is missing versionId")

    nodes_json = dumps_json(workflow.get("nodes", []))
    connections_json = dumps_json(workflow.get("connections", {}))
    settings_json = dumps_json(workflow.get("settings", {}))
    static_data_json = dumps_json(workflow.get("staticData"))
    pin_data_json = dumps_json(workflow.get("pinData", {}))
    meta_json = dumps_json(workflow.get("meta", {}))
    active = 1 if workflow.get("active") else 0
    active_version_id = version_id if active else None
    is_archived = 1 if workflow.get("isArchived") else 0
    name = str(workflow.get("name") or workflow_id)
    description = workflow.get("description")

    existing = fetch_one(
        cursor,
        """
        SELECT versionId, versionCounter
        FROM workflow_entity
        WHERE id = ?
        """,
        (workflow_id,),
    )

    if existing:
        version_counter = int(existing["versionCounter"] or 1)
        if existing["versionId"] != version_id:
            version_counter += 1
        cursor.execute(
            """
            UPDATE workflow_entity
            SET name = ?,
                active = ?,
                nodes = ?,
                connections = ?,
                settings = ?,
                staticData = ?,
                pinData = ?,
                versionId = ?,
                meta = ?,
                updatedAt = ?,
                isArchived = ?,
                versionCounter = ?,
                description = ?,
                activeVersionId = ?
            WHERE id = ?
            """,
            (
                name,
                active,
                nodes_json,
                connections_json,
                settings_json,
                static_data_json,
                pin_data_json,
                version_id,
                meta_json,
                now,
                is_archived,
                version_counter,
                description,
                active_version_id,
                workflow_id,
            ),
        )
    else:
        cursor.execute(
            """
            INSERT INTO workflow_entity (
                id, name, active, nodes, connections, settings, staticData, pinData,
                versionId, triggerCount, meta, createdAt, updatedAt, isArchived,
                versionCounter, description, activeVersionId
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                workflow_id,
                name,
                active,
                nodes_json,
                connections_json,
                settings_json,
                static_data_json,
                pin_data_json,
                version_id,
                0,
                meta_json,
                now,
                now,
                is_archived,
                1,
                description,
                active_version_id,
            ),
        )
        ensure_shared_workflow(cursor, workflow_id, project_id, now)

    return version_id


def upsert_workflow_history(
    cursor: sqlite3.Cursor,
    workflow: dict[str, Any],
    version_id: str,
    now: str,
) -> None:
    workflow_id = workflow["id"]
    name = workflow.get("name")
    description = workflow.get("description")
    nodes_json = dumps_json(workflow.get("nodes", [])) or "[]"
    connections_json = dumps_json(workflow.get("connections", {})) or "{}"
    existing = fetch_one(
        cursor,
        "SELECT versionId FROM workflow_history WHERE versionId = ?",
        (version_id,),
    )

    if existing:
        cursor.execute(
            """
            UPDATE workflow_history
            SET workflowId = ?,
                authors = ?,
                updatedAt = ?,
                nodes = ?,
                connections = ?,
                name = ?,
                autosaved = ?,
                description = ?
            WHERE versionId = ?
            """,
            (
                workflow_id,
                "repo-sync",
                now,
                nodes_json,
                connections_json,
                name,
                0,
                description,
                version_id,
            ),
        )
        return

    cursor.execute(
        """
        INSERT INTO workflow_history (
            versionId, workflowId, authors, createdAt, updatedAt,
            nodes, connections, name, autosaved, description
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            version_id,
            workflow_id,
            "repo-sync",
            now,
            now,
            nodes_json,
            connections_json,
            name,
            0,
            description,
            ),
    )


def run_sync(
    *,
    workflow_dir: Path,
    db_path: Path,
    backup_dir: Path,
    backup_retain: int = 5,
    include_ids: set[str] | None = None,
) -> dict[str, Any]:
    workflow_dir = workflow_dir.resolve()
    db_path = db_path.resolve()
    backup_dir = backup_dir.resolve()
    if not workflow_dir.is_dir():
        raise FileNotFoundError(f"Workflow directory does not exist: {workflow_dir}")
    if not db_path.is_file():
        raise FileNotFoundError(f"n8n database does not exist: {db_path}")

    workflows = load_workflows(workflow_dir, include_ids)
    if not workflows:
        raise ValueError(f"No workflow JSON files found in {workflow_dir}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        backup_path = backup_database(conn, backup_dir)
        cursor = conn.cursor()
        personal_project = fetch_one(
            cursor,
            "SELECT * FROM project WHERE type = 'personal' ORDER BY createdAt ASC LIMIT 1",
        )
        if not personal_project:
            raise RuntimeError("Could not find a personal project in the active n8n database.")
        project_owner_id = personal_project["creatorId"] if "creatorId" in personal_project.keys() else None

        now = utc_now_sql()
        synced: list[str] = []
        pruned_webhook_rows: list[dict[str, Any]] = []
        for path, workflow in workflows:
            version_id = upsert_workflow_entity(cursor, workflow, personal_project["id"], now)
            upsert_workflow_history(cursor, workflow, version_id, now)
            if workflow.get("active"):
                ensure_published_version(cursor, workflow["id"], version_id, now, project_owner_id)
            else:
                remove_published_version(cursor, workflow["id"], version_id, now, project_owner_id)
            removed = prune_webhook_rows(cursor, workflow)
            if removed:
                pruned_webhook_rows.append(
                    {
                        "workflow_id": str(workflow["id"]),
                        "workflow_name": str(workflow.get("name") or workflow["id"]),
                        "removed_rows": removed,
                    }
                )
            synced.append(
                f"{workflow['id']} | active={bool(workflow.get('active'))} | version={version_id} | {path.name}"
            )

        conn.commit()
    finally:
        conn.close()

    pruned_backups = prune_backup_files(backup_dir, backup_retain)

    return {
        "workflow_dir": workflow_dir,
        "db_path": db_path,
        "backup_path": backup_path,
        "backup_retain": backup_retain,
        "pruned_backups": pruned_backups,
        "requested_workflow_ids": sorted(include_ids or []),
        "synced": synced,
        "pruned_webhook_rows": pruned_webhook_rows,
    }


def print_sync_result(result: dict[str, Any]) -> None:
    print(f"Backed up active n8n DB to: {result['backup_path']}")
    if result["pruned_backups"]:
        print(
            f"Pruned {len(result['pruned_backups'])} old backup(s); "
            f"kept the most recent {result['backup_retain']}."
        )
    print("Synced workflows:")
    for line in result["synced"]:
        print(f"  - {line}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Sync repo-managed n8n workflow JSON files into the active runtime database."
    )
    parser.add_argument(
        "--workflow-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / "workflows",
        help="Directory containing repo-managed workflow JSON files.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data" / "n8n" / "database.sqlite",
        help="Path to the active n8n SQLite database.",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=Path(__file__).resolve().parents[3] / "backups" / "n8n-sync",
        help="Directory used for automatic SQLite backups before sync.",
    )
    parser.add_argument(
        "--backup-retain",
        type=int,
        default=5,
        help="Maximum number of SQLite backups to keep in --backup-dir. Use 0 to disable pruning.",
    )
    parser.add_argument(
        "--workflow-id",
        action="append",
        default=[],
        help="Optional workflow id to sync. Repeat to sync multiple ids.",
    )
    parser.add_argument(
        "--debug-log",
        type=Path,
        default=default_debug_log_path(),
        help="Append a summary to this debug log file.",
    )
    args = parser.parse_args()
    include_ids = {value.strip() for value in args.workflow_id if value.strip()} or None

    try:
        result = run_sync(
            workflow_dir=args.workflow_dir,
            db_path=args.db_path,
            backup_dir=args.backup_dir,
            backup_retain=args.backup_retain,
            include_ids=include_ids,
        )
        print_sync_result(result)
        append_debug_log(
            script_name="sync_workflows.py",
            stage="sync_workflows",
            status="success",
            summary=f"Synced {len(result['synced'])} workflow(s) into the active runtime database.",
            details=result,
            log_path=args.debug_log,
        )
        return 0
    except Exception as exc:
        append_debug_log(
            script_name="sync_workflows.py",
            stage="sync_workflows",
            status="failure",
            summary=f"Workflow sync failed: {exc}",
            details={
                "workflow_dir": args.workflow_dir,
                "db_path": args.db_path,
                "backup_dir": args.backup_dir,
                "backup_retain": args.backup_retain,
                "requested_workflow_ids": sorted(include_ids or []),
                "error": str(exc),
            },
            log_path=args.debug_log,
        )
        print(exc, file=sys.stderr)
        return 1

if __name__ == "__main__":
    raise SystemExit(main())
