#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def fetch_one(cursor: sqlite3.Cursor, query: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
    cursor.execute(query, params)
    return cursor.fetchone()


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
        "--workflow-id",
        action="append",
        default=[],
        help="Optional workflow id to sync. Repeat to sync multiple ids.",
    )
    args = parser.parse_args()

    workflow_dir = args.workflow_dir.resolve()
    db_path = args.db_path.resolve()
    include_ids = {value.strip() for value in args.workflow_id if value.strip()} or None

    if not workflow_dir.is_dir():
        raise SystemExit(f"Workflow directory does not exist: {workflow_dir}")
    if not db_path.is_file():
        raise SystemExit(f"n8n database does not exist: {db_path}")

    workflows = load_workflows(workflow_dir, include_ids)
    if not workflows:
        raise SystemExit(f"No workflow JSON files found in {workflow_dir}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        backup_path = backup_database(conn, args.backup_dir.resolve())
        cursor = conn.cursor()
        personal_project = fetch_one(
            cursor,
            "SELECT id FROM project WHERE type = 'personal' ORDER BY createdAt ASC LIMIT 1",
        )
        if not personal_project:
            raise SystemExit("Could not find a personal project in the active n8n database.")

        now = utc_now_sql()
        synced: list[str] = []
        for path, workflow in workflows:
            version_id = upsert_workflow_entity(cursor, workflow, personal_project["id"], now)
            upsert_workflow_history(cursor, workflow, version_id, now)
            synced.append(
                f"{workflow['id']} | active={bool(workflow.get('active'))} | version={version_id} | {path.name}"
            )

        conn.commit()
    finally:
        conn.close()

    print(f"Backed up active n8n DB to: {backup_path}")
    print("Synced workflows:")
    for line in synced:
        print(f"  - {line}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
