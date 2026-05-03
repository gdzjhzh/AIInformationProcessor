#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
import sqlite3
import subprocess
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


def run_git_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def resolve_repo_root(path: Path) -> Path:
    result = run_git_command(["git", "rev-parse", "--show-toplevel"], cwd=path)
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not resolve git repo root from {path}: "
            f"{result.stderr.strip() or result.stdout.strip() or 'git rev-parse failed'}"
        )
    return Path(result.stdout.strip()).resolve()


def list_repo_managed_workflow_paths(
    workflow_dir: Path,
    *,
    tracked_only: bool = True,
) -> tuple[list[Path], list[Path]]:
    all_paths = sorted(path.resolve() for path in workflow_dir.glob("*.json"))
    if not tracked_only:
        return all_paths, []

    repo_root = resolve_repo_root(workflow_dir)
    try:
        pathspec = workflow_dir.resolve().relative_to(repo_root).as_posix()
    except ValueError as exc:
        raise RuntimeError(
            f"Workflow directory {workflow_dir.resolve()} is not inside git repo {repo_root}"
        ) from exc

    result = run_git_command(["git", "ls-files", "--", pathspec], cwd=repo_root)
    if result.returncode != 0:
        raise RuntimeError(
            f"Could not list tracked workflow files under {workflow_dir}: "
            f"{result.stderr.strip() or result.stdout.strip() or 'git ls-files failed'}"
        )

    tracked_paths = {
        (repo_root / raw_line.strip()).resolve()
        for raw_line in result.stdout.splitlines()
        if raw_line.strip().endswith(".json")
    }
    managed = [path for path in all_paths if path in tracked_paths]
    ignored = [path for path in all_paths if path not in tracked_paths]
    return managed, ignored


def load_workflows(
    workflow_dir: Path,
    include_ids: set[str] | None,
    *,
    tracked_only: bool = True,
) -> list[tuple[Path, dict[str, Any]]]:
    managed_paths, _ = list_repo_managed_workflow_paths(workflow_dir, tracked_only=tracked_only)
    workflows: list[tuple[Path, dict[str, Any]]] = []
    for path in managed_paths:
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
            scope = "tracked repo workflows" if tracked_only else "workflow_dir"
            raise ValueError(f"Workflow ids not found in {scope} {workflow_dir}: {', '.join(sorted(missing))}")
    return workflows


def workflow_definition_payload(workflow: dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(workflow.get("name") or ""),
        "active": bool(workflow.get("active")),
        "nodes": workflow.get("nodes", []),
        "connections": workflow.get("connections", {}),
        "settings": workflow.get("settings", {}),
        "staticData": normalize_static_data(workflow.get("staticData")),
        "pinData": workflow.get("pinData", {}),
        "meta": workflow.get("meta", {}),
        "isArchived": bool(workflow.get("isArchived")),
        "description": workflow.get("description"),
    }


def workflow_definition_hash(workflow: dict[str, Any]) -> str:
    payload = workflow_definition_payload(workflow)
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return digest


def parse_runtime_json(value: Any, fallback: Any) -> Any:
    if value in (None, ""):
        return fallback
    if isinstance(value, (dict, list)):
        return value
    return json.loads(str(value))


def normalize_static_data(value: Any) -> Any:
    if value in (None, "", {}):
        return None
    if not isinstance(value, dict):
        return value

    normalized: dict[str, Any] = {}
    for key, item in value.items():
        if isinstance(item, dict) and set(item.keys()) == {"recurrenceRules"} and item["recurrenceRules"] == []:
            continue
        normalized[key] = item

    return normalized or None


def workflow_entity_definition_payload(row: sqlite3.Row | dict[str, Any]) -> dict[str, Any]:
    return {
        "name": str(row["name"] or ""),
        "active": bool(row["active"]),
        "nodes": parse_runtime_json(row["nodes"], []),
        "connections": parse_runtime_json(row["connections"], {}),
        "settings": parse_runtime_json(row["settings"], {}),
        "staticData": normalize_static_data(parse_runtime_json(row["staticData"], None)),
        "pinData": parse_runtime_json(row["pinData"], {}),
        "meta": parse_runtime_json(row["meta"], {}),
        "isArchived": bool(row["isArchived"]),
        "description": row["description"],
    }


def workflow_entity_definition_hash(row: sqlite3.Row | dict[str, Any]) -> str:
    payload = workflow_entity_definition_payload(row)
    digest = hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    return digest


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


def webhook_node_specs(workflow: dict[str, Any]) -> list[dict[str, str]]:
    specs: list[dict[str, str]] = []
    workflow_id = str(workflow["id"])
    for node in workflow.get("nodes", []):
        if node.get("type") != "n8n-nodes-base.webhook":
            continue
        node_name = str(node.get("name") or "").strip()
        parameters = node.get("parameters") if isinstance(node.get("parameters"), dict) else {}
        path = str(parameters.get("path") or "").strip().strip("/")
        if not node_name or not path:
            continue
        method = str(parameters.get("httpMethod") or "GET").strip().upper()
        specs.append(
            {
                "node": node_name,
                "method": method,
                "webhookPath": f"{workflow_id}/{node_name}/{path}",
            }
        )
    return specs


def sync_webhook_rows(
    cursor: sqlite3.Cursor,
    workflow: dict[str, Any],
) -> list[dict[str, str]]:
    if not workflow.get("active") or not table_exists(cursor, "webhook_entity"):
        return []

    workflow_id = str(workflow["id"])
    synced: list[dict[str, str]] = []
    for spec in webhook_node_specs(workflow):
        row = fetch_one(
            cursor,
            """
            SELECT rowid, webhookPath, method
            FROM webhook_entity
            WHERE workflowId = ? AND node = ?
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (workflow_id, spec["node"]),
        )
        if row is None:
            cursor.execute(
                """
                INSERT INTO webhook_entity (workflowId, webhookPath, method, node, webhookId, pathLength)
                VALUES (?, ?, ?, ?, NULL, NULL)
                """,
                (workflow_id, spec["webhookPath"], spec["method"], spec["node"]),
            )
            synced.append(spec)
            continue

        current_path = str(row["webhookPath"] or "")
        current_method = str(row["method"] or "")
        if current_path != spec["webhookPath"] or current_method != spec["method"]:
            cursor.execute(
                """
                UPDATE webhook_entity
                SET webhookPath = ?, method = ?
                WHERE rowid = ?
                """,
                (spec["webhookPath"], spec["method"], row["rowid"]),
            )
            synced.append(spec)

    return synced


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


def delete_runtime_workflow(cursor: sqlite3.Cursor, workflow_id: str) -> None:
    if table_exists(cursor, "webhook_entity"):
        cursor.execute("DELETE FROM webhook_entity WHERE workflowId = ?", (workflow_id,))
    if table_exists(cursor, "workflow_published_version"):
        cursor.execute("DELETE FROM workflow_published_version WHERE workflowId = ?", (workflow_id,))
    if table_exists(cursor, "workflow_publish_history"):
        cursor.execute("DELETE FROM workflow_publish_history WHERE workflowId = ?", (workflow_id,))
    if table_exists(cursor, "shared_workflow"):
        cursor.execute("DELETE FROM shared_workflow WHERE workflowId = ?", (workflow_id,))
    cursor.execute("DELETE FROM workflow_entity WHERE id = ?", (workflow_id,))


def set_workflow_active_version(
    cursor: sqlite3.Cursor,
    workflow_id: str,
    version_id: str | None,
) -> None:
    cursor.execute(
        """
        UPDATE workflow_entity
        SET activeVersionId = ?
        WHERE id = ?
        """,
        (version_id, workflow_id),
    )


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
                description = ?
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
                None,
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
    backup_retain: int = 1,
    include_ids: set[str] | None = None,
    tracked_only: bool = True,
    prune_unmanaged: bool = True,
) -> dict[str, Any]:
    workflow_dir = workflow_dir.resolve()
    db_path = db_path.resolve()
    backup_dir = backup_dir.resolve()
    if not workflow_dir.is_dir():
        raise FileNotFoundError(f"Workflow directory does not exist: {workflow_dir}")
    if not db_path.is_file():
        raise FileNotFoundError(f"n8n database does not exist: {db_path}")

    managed_paths, ignored_paths = list_repo_managed_workflow_paths(workflow_dir, tracked_only=tracked_only)
    workflows = load_workflows(workflow_dir, include_ids, tracked_only=tracked_only)
    if not workflows:
        raise ValueError(f"No workflow JSON files found in {workflow_dir}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        conn.execute("PRAGMA foreign_keys = ON")
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
        synced_webhook_rows: list[dict[str, Any]] = []
        pruned_runtime_workflows: list[dict[str, Any]] = []
        for path, workflow in workflows:
            version_id = upsert_workflow_entity(cursor, workflow, personal_project["id"], now)
            upsert_workflow_history(cursor, workflow, version_id, now)
            if workflow.get("active"):
                set_workflow_active_version(cursor, workflow["id"], version_id)
                ensure_published_version(cursor, workflow["id"], version_id, now, project_owner_id)
            else:
                set_workflow_active_version(cursor, workflow["id"], None)
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
            webhook_rows = sync_webhook_rows(cursor, workflow)
            if webhook_rows:
                synced_webhook_rows.append(
                    {
                        "workflow_id": str(workflow["id"]),
                        "workflow_name": str(workflow.get("name") or workflow["id"]),
                        "synced_rows": webhook_rows,
                    }
                )
            synced.append(
                f"{workflow['id']} | active={bool(workflow.get('active'))} | version={version_id} | {path.name}"
            )

        expected_workflow_ids = {str(workflow["id"]) for _, workflow in workflows}
        unmanaged_runtime_workflows: list[dict[str, Any]] = []
        if include_ids is None:
            cursor.execute(
                """
                SELECT id, name, active, updatedAt
                FROM workflow_entity
                ORDER BY updatedAt DESC, id ASC
                """
            )
            unmanaged_runtime_workflows = [
                {
                    "workflow_id": str(row["id"]),
                    "workflow_name": str(row["name"] or row["id"]),
                    "active": bool(row["active"]),
                    "updatedAt": str(row["updatedAt"] or ""),
                }
                for row in cursor.fetchall()
                if str(row["id"]) not in expected_workflow_ids
            ]
            if prune_unmanaged:
                for row in unmanaged_runtime_workflows:
                    delete_runtime_workflow(cursor, row["workflow_id"])
                    pruned_runtime_workflows.append(row)

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
        "tracked_only": tracked_only,
        "ignored_workflow_files": [path.name for path in ignored_paths],
        "managed_workflow_files": [path.name for path in managed_paths],
        "synced": synced,
        "pruned_webhook_rows": pruned_webhook_rows,
        "synced_webhook_rows": synced_webhook_rows,
        "unmanaged_runtime_workflows": unmanaged_runtime_workflows if include_ids is None else [],
        "pruned_runtime_workflows": pruned_runtime_workflows,
        "prune_unmanaged": bool(prune_unmanaged and include_ids is None),
    }


def print_sync_result(result: dict[str, Any]) -> None:
    print(f"Backed up active n8n DB to: {result['backup_path']}")
    if result["pruned_backups"]:
        print(
            f"Pruned {len(result['pruned_backups'])} old backup(s); "
            f"kept the most recent {result['backup_retain']}."
        )
    if result["ignored_workflow_files"]:
        print(
            "Ignored local workflow files that are not tracked in git: "
            + ", ".join(result["ignored_workflow_files"])
        )
    print("Synced workflows:")
    for line in result["synced"]:
        print(f"  - {line}")
    if result["prune_unmanaged"]:
        if result["pruned_runtime_workflows"]:
            print("Removed unmanaged runtime workflows:")
            for row in result["pruned_runtime_workflows"]:
                print(
                    "  - "
                    f"{row['workflow_id']} | active={row['active']} | {row['workflow_name']}"
                )
        else:
            print("Removed unmanaged runtime workflows: none")
    elif result["unmanaged_runtime_workflows"]:
        print("Unmanaged runtime workflows remain (prune skipped):")
        for row in result["unmanaged_runtime_workflows"]:
            print(
                "  - "
                f"{row['workflow_id']} | active={row['active']} | {row['workflow_name']}"
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
        "--backup-retain",
        type=int,
        default=1,
        help="Maximum number of SQLite backups to keep in --backup-dir. Use 0 to disable pruning.",
    )
    parser.add_argument(
        "--workflow-id",
        action="append",
        default=[],
        help="Optional workflow id to sync. Repeat to sync multiple ids.",
    )
    parser.add_argument(
        "--include-untracked",
        action="store_true",
        help="Treat untracked local workflow JSON files as part of the publish set. Default is tracked repo files only.",
    )
    parser.add_argument(
        "--no-prune-unmanaged",
        action="store_true",
        help=(
            "Do not remove runtime workflows that are outside the tracked repo-managed workflow set. "
            "Default behavior prunes unmanaged runtime workflows during full publish."
        ),
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
            tracked_only=not args.include_untracked,
            prune_unmanaged=not args.no_prune_unmanaged,
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
