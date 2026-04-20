#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
import sys
from pathlib import Path
from typing import Any

from debug_log import append_debug_log, default_debug_log_path
from sync_workflows import (
    fetch_one,
    list_repo_managed_workflow_paths,
    load_workflows,
    table_exists,
    workflow_definition_hash,
    workflow_entity_definition_hash,
)


def webhook_node_names(workflow: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for node in workflow.get("nodes", []):
        if node.get("type") == "n8n-nodes-base.webhook":
            names.append(str(node.get("name") or "").strip())
    return [name for name in names if name]


def run_alignment_check(
    *,
    workflow_dir: Path,
    db_path: Path,
    include_ids: set[str] | None = None,
    tracked_only: bool = True,
    allow_runtime_extras: bool = False,
) -> dict[str, Any]:
    workflow_dir = workflow_dir.resolve()
    db_path = db_path.resolve()
    if not workflow_dir.is_dir():
        raise FileNotFoundError(f"Workflow directory does not exist: {workflow_dir}")
    if not db_path.is_file():
        raise FileNotFoundError(f"n8n database does not exist: {db_path}")

    managed_paths, ignored_paths = list_repo_managed_workflow_paths(
        workflow_dir,
        tracked_only=tracked_only,
    )
    workflows = load_workflows(workflow_dir, include_ids, tracked_only=tracked_only)
    if not workflows:
        raise ValueError(f"No workflow JSON files found in {workflow_dir}")

    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        published_table_exists = table_exists(cursor, "workflow_published_version")
        checks: list[dict[str, Any]] = []
        errors: list[str] = []
        warnings: list[str] = []
        expected_workflow_ids = {str(workflow["id"]) for _, workflow in workflows}

        if ignored_paths:
            warnings.append(
                "Ignored local workflow files that are not tracked in git: "
                + ", ".join(path.name for path in ignored_paths)
            )

        runtime_extra_workflows: list[dict[str, Any]] = []
        if include_ids is None and not allow_runtime_extras:
            cursor.execute(
                """
                SELECT id, name, active, updatedAt
                FROM workflow_entity
                ORDER BY updatedAt DESC, id ASC
                """
            )
            runtime_extra_workflows = [
                {
                    "workflow_id": str(row["id"]),
                    "workflow_name": str(row["name"] or row["id"]),
                    "active": bool(row["active"]),
                    "updatedAt": str(row["updatedAt"] or ""),
                }
                for row in cursor.fetchall()
                if str(row["id"]) not in expected_workflow_ids
            ]
            for row in runtime_extra_workflows:
                errors.append(
                    f"{row['workflow_id']}: runtime contains unmanaged workflow "
                    f"{row['workflow_name']}"
                )

        for path, workflow in workflows:
            workflow_id = str(workflow["id"])
            expected_active = bool(workflow.get("active"))
            expected_version_id = str(workflow.get("versionId") or "").strip()
            expected_definition_hash = workflow_definition_hash(workflow)
            if not expected_version_id:
                raise ValueError(f"Workflow {workflow_id} is missing versionId")

            check: dict[str, Any] = {
                "workflow_id": workflow_id,
                "name": workflow.get("name"),
                "file": path.name,
                "expected_active": expected_active,
                "expected_version_id": expected_version_id,
                "expected_definition_hash": expected_definition_hash,
            }

            row = fetch_one(
                cursor,
                """
                SELECT name, active, versionId, activeVersionId,
                       nodes, connections, settings, staticData, pinData, meta,
                       description, isArchived
                FROM workflow_entity
                WHERE id = ?
                """,
                (workflow_id,),
            )
            if row is None:
                errors.append(f"{workflow_id}: missing from workflow_entity")
                check["status"] = "missing"
                checks.append(check)
                continue

            db_active = bool(row["active"])
            db_version_id = str(row["versionId"] or "").strip()
            db_active_version_id = str(row["activeVersionId"] or "").strip()
            db_definition_hash = workflow_entity_definition_hash(row)
            check.update(
                {
                    "db_active": db_active,
                    "db_version_id": db_version_id,
                    "db_active_version_id": db_active_version_id or None,
                    "db_definition_hash": db_definition_hash,
                }
            )

            if db_active != expected_active:
                errors.append(
                    f"{workflow_id}: active mismatch repo={expected_active} runtime={db_active}"
                )
            if db_version_id != expected_version_id:
                errors.append(
                    f"{workflow_id}: versionId mismatch repo={expected_version_id} runtime={db_version_id}"
                )
            expected_active_version = expected_version_id if expected_active else ""
            if db_active_version_id != expected_active_version:
                errors.append(
                    f"{workflow_id}: activeVersionId mismatch repo={expected_active_version or 'None'} "
                    f"runtime={db_active_version_id or 'None'}"
                )
            if db_definition_hash != expected_definition_hash:
                errors.append(
                    f"{workflow_id}: definition hash mismatch repo={expected_definition_hash} "
                    f"runtime={db_definition_hash}"
                )

            history_row = fetch_one(
                cursor,
                "SELECT versionId FROM workflow_history WHERE versionId = ?",
                (expected_version_id,),
            )
            check["history_has_version"] = history_row is not None
            if history_row is None:
                errors.append(f"{workflow_id}: versionId {expected_version_id} missing from workflow_history")

            if published_table_exists:
                published_row = fetch_one(
                    cursor,
                    """
                    SELECT publishedVersionId
                    FROM workflow_published_version
                    WHERE workflowId = ?
                    """,
                    (workflow_id,),
                )
                published_version_id = (
                    str(published_row["publishedVersionId"] or "").strip() if published_row else ""
                )
                check["published_version_id"] = published_version_id or None
                if expected_active:
                    if published_version_id != expected_version_id:
                        errors.append(
                            f"{workflow_id}: publishedVersionId mismatch repo={expected_version_id} "
                            f"runtime={published_version_id or 'None'}"
                        )
                elif published_version_id:
                    errors.append(
                        f"{workflow_id}: inactive workflow still has publishedVersionId={published_version_id}"
                    )

            expected_webhook_nodes = webhook_node_names(workflow)
            if expected_webhook_nodes:
                cursor.execute(
                    """
                    SELECT node, webhookPath, method
                    FROM webhook_entity
                    WHERE workflowId = ?
                    ORDER BY rowid ASC
                    """,
                    (workflow_id,),
                )
                webhook_rows = cursor.fetchall()
                check["webhook_rows"] = [
                    {
                        "node": str(row["node"] or ""),
                        "webhookPath": str(row["webhookPath"] or ""),
                        "method": str(row["method"] or ""),
                    }
                    for row in webhook_rows
                ]
                registered_nodes = {
                    entry["node"] for entry in check["webhook_rows"] if entry["node"]
                }
                missing_nodes = sorted(set(expected_webhook_nodes) - registered_nodes)
                extra_nodes = sorted(registered_nodes - set(expected_webhook_nodes))
                if expected_active and missing_nodes:
                    errors.append(
                        f"{workflow_id}: missing webhook registrations for node(s): {', '.join(missing_nodes)}"
                    )
                if extra_nodes:
                    warnings.append(
                        f"{workflow_id}: extra webhook registrations remain for node(s): {', '.join(extra_nodes)}"
                    )
                distinct_paths = {
                    entry["webhookPath"] for entry in check["webhook_rows"] if entry["webhookPath"]
                }
                if len(distinct_paths) > len(expected_webhook_nodes):
                    warnings.append(
                        f"{workflow_id}: multiple webhook paths are registered in runtime; "
                        "consider a clean restart if stale rows remain"
                    )

            check["status"] = "ok"
            checks.append(check)

        return {
            "workflow_dir": workflow_dir,
            "db_path": db_path,
            "requested_workflow_ids": sorted(include_ids or []),
            "tracked_only": tracked_only,
            "managed_workflow_files": [path.name for path in managed_paths],
            "ignored_workflow_files": [path.name for path in ignored_paths],
            "checked": checks,
            "errors": errors,
            "warnings": warnings,
            "runtime_extra_workflows": runtime_extra_workflows,
        }
    finally:
        conn.close()


def print_alignment_result(result: dict[str, Any]) -> None:
    print("Runtime alignment summary:")
    for item in result["checked"]:
        print(
            "  - "
            f"{item['workflow_id']} | file={item['file']} | "
            f"repo_active={item.get('expected_active')} | "
            f"runtime_active={item.get('db_active', 'missing')} | "
            f"repo_version={item.get('expected_version_id')} | "
            f"runtime_version={item.get('db_version_id', 'missing')} | "
            f"repo_hash={item.get('expected_definition_hash', 'n/a')[:12]} | "
            f"runtime_hash={item.get('db_definition_hash', 'missing')[:12] if item.get('db_definition_hash') else 'missing'}"
        )
    if result["runtime_extra_workflows"]:
        print("Extra runtime workflows:")
        for row in result["runtime_extra_workflows"]:
            print(
                "  - "
                f"{row['workflow_id']} | active={row['active']} | {row['workflow_name']}"
            )
    if result["warnings"]:
        print("Warnings:")
        for warning in result["warnings"]:
            print(f"  - {warning}")
    if result["errors"]:
        print("Errors:")
        for error in result["errors"]:
            print(f"  - {error}")
    else:
        print("Runtime alignment passed.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare repo-managed workflow JSON files against the active n8n runtime database."
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
        "--workflow-id",
        action="append",
        default=[],
        help="Optional workflow id to check. Repeat to check multiple ids.",
    )
    parser.add_argument(
        "--include-untracked",
        action="store_true",
        help="Treat untracked local workflow JSON files as part of the repo comparison set.",
    )
    parser.add_argument(
        "--allow-runtime-extras",
        action="store_true",
        help="Allow runtime workflows that are outside the tracked repo-managed workflow set.",
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
        result = run_alignment_check(
            workflow_dir=args.workflow_dir,
            db_path=args.db_path,
            include_ids=include_ids,
            tracked_only=not args.include_untracked,
            allow_runtime_extras=args.allow_runtime_extras,
        )
        print_alignment_result(result)
        status = "success" if not result["warnings"] else "warning"
        append_debug_log(
            script_name="check_runtime_alignment.py",
            stage="runtime_alignment",
            status=status,
            summary=(
                f"Checked {len(result['checked'])} workflow(s); "
                f"errors={len(result['errors'])}, warnings={len(result['warnings'])}."
            ),
            details=result,
            log_path=args.debug_log,
        )
        return 0 if not result["errors"] else 1
    except Exception as exc:
        append_debug_log(
            script_name="check_runtime_alignment.py",
            stage="runtime_alignment",
            status="failure",
            summary=f"Runtime alignment check failed: {exc}",
            details={
                "workflow_dir": args.workflow_dir,
                "db_path": args.db_path,
                "requested_workflow_ids": sorted(include_ids or []),
                "error": str(exc),
            },
            log_path=args.debug_log,
        )
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
