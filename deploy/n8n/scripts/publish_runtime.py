#!/usr/bin/env python3
from __future__ import annotations

import argparse
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from debug_log import append_debug_log, default_debug_log_path


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def run_command(command: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        cwd=str(cwd),
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def wait_for_http(base_url: str, timeout_seconds: int, poll_interval_seconds: float) -> dict[str, Any]:
    deadline = time.time() + timeout_seconds
    last_error = ""
    while time.time() < deadline:
        req = urllib.request.Request(base_url, method="GET")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                return {
                    "base_url": base_url,
                    "status_code": resp.status,
                    "ready": True,
                }
        except urllib.error.HTTPError as exc:
            return {
                "base_url": base_url,
                "status_code": exc.code,
                "ready": True,
                "note": "n8n responded with HTTP error status but the process is reachable",
            }
        except Exception as exc:
            last_error = f"{type(exc).__name__}: {exc}"
            time.sleep(poll_interval_seconds)

    raise RuntimeError(f"Timed out waiting for n8n at {base_url}: {last_error or 'no response'}")


def main() -> int:
    script_dir = Path(__file__).resolve().parent
    parser = argparse.ArgumentParser(
        description=(
            "Publish repo-managed workflow JSON into the local n8n runtime. "
            "This is the external deployment entrypoint; it runs sync, restart, and runtime alignment checks."
        )
    )
    parser.add_argument(
        "--workflow-dir",
        type=Path,
        default=script_dir.parents[1] / "n8n" / "workflows",
        help="Directory containing repo-managed workflow JSON files.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=script_dir.parents[1] / "data" / "n8n" / "database.sqlite",
        help="Path to the live n8n SQLite database.",
    )
    parser.add_argument(
        "--backup-dir",
        type=Path,
        default=script_dir.parents[2] / "backups" / "n8n-sync",
        help="Directory used for automatic SQLite backups before sync.",
    )
    parser.add_argument(
        "--backup-retain",
        type=int,
        default=5,
        help="Maximum number of SQLite backups to keep in --backup-dir. Use 0 to disable pruning.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=script_dir.parents[1] / ".env",
        help="Path to deploy/.env.",
    )
    parser.add_argument(
        "--compose-file",
        type=Path,
        default=script_dir.parents[1] / "compose.yaml",
        help="Path to deploy/compose.yaml.",
    )
    parser.add_argument(
        "--compose-dir",
        type=Path,
        default=script_dir.parents[1],
        help="Working directory for docker compose commands.",
    )
    parser.add_argument(
        "--service-name",
        default="n8n",
        help="Docker Compose service to restart after sync.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:5678",
        help="Host-reachable n8n base URL used after restart.",
    )
    parser.add_argument(
        "--restart-timeout-seconds",
        type=int,
        default=90,
        help="How long to wait for n8n to respond after restart.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=2.0,
        help="Polling interval while waiting for n8n to respond after restart.",
    )
    parser.add_argument(
        "--workflow-id",
        action="append",
        default=[],
        help="Optional workflow id to publish. Repeat to publish multiple ids.",
    )
    parser.add_argument(
        "--include-untracked",
        action="store_true",
        help="Include untracked local workflow JSON files in the publish set. Default is tracked repo files only.",
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
        "--allow-runtime-extras",
        action="store_true",
        help="Allow runtime workflows that are outside the tracked repo-managed workflow set during alignment checks.",
    )
    parser.add_argument(
        "--run-smoke-qdrant",
        action="store_true",
        help="Run smoke_qdrant_gate.py after runtime alignment succeeds.",
    )
    parser.add_argument(
        "--run-verify-transcript",
        action="store_true",
        help="Run verify_transcript_mainline.py after runtime alignment succeeds.",
    )
    parser.add_argument(
        "--no-restart",
        action="store_true",
        help="Skip docker compose restart. Use only when you know runtime webhook/cache state is already fresh.",
    )
    parser.add_argument(
        "--debug-log",
        type=Path,
        default=default_debug_log_path(),
        help="Append a summary to this debug log file.",
    )
    args = parser.parse_args()
    args.debug_log = args.debug_log.resolve()

    include_ids = [value.strip() for value in args.workflow_id if value.strip()]
    env_values = load_dotenv(args.env_file) if args.env_file.is_file() else {}
    base_url = args.base_url.rstrip("/")
    if args.base_url == "http://127.0.0.1:5678" and env_values.get("N8N_PORT"):
        base_url = f"http://127.0.0.1:{env_values['N8N_PORT']}"

    step_results: list[dict[str, Any]] = []
    append_debug_log(
        script_name="publish_runtime.py",
        stage="publish_runtime",
        status="start",
        summary="Starting n8n runtime publish flow.",
        details={
            "workflow_dir": args.workflow_dir,
            "db_path": args.db_path,
            "backup_dir": args.backup_dir,
            "backup_retain": args.backup_retain,
            "compose_file": args.compose_file,
            "compose_dir": args.compose_dir,
            "service_name": args.service_name,
            "base_url": base_url,
            "requested_workflow_ids": include_ids,
            "include_untracked": args.include_untracked,
            "prune_unmanaged": not args.no_prune_unmanaged,
            "allow_runtime_extras": args.allow_runtime_extras,
            "run_smoke_qdrant": args.run_smoke_qdrant,
            "run_verify_transcript": args.run_verify_transcript,
            "restart_enabled": not args.no_restart,
        },
        log_path=args.debug_log,
    )

    sync_command = [
        sys.executable,
        str(script_dir / "sync_workflows.py"),
        "--workflow-dir",
        str(args.workflow_dir),
        "--db-path",
        str(args.db_path),
        "--backup-dir",
        str(args.backup_dir),
        "--backup-retain",
        str(args.backup_retain),
        "--debug-log",
        str(args.debug_log),
    ]
    if args.include_untracked:
        sync_command.append("--include-untracked")
    if args.no_prune_unmanaged:
        sync_command.append("--no-prune-unmanaged")
    for workflow_id in include_ids:
        sync_command.extend(["--workflow-id", workflow_id])

    sync_result = run_command(sync_command, cwd=args.compose_dir)
    step_results.append(
        {
            "step": "sync_workflows",
            "command": sync_command,
            "returncode": sync_result.returncode,
        }
    )
    if sync_result.returncode != 0:
        append_debug_log(
            script_name="publish_runtime.py",
            stage="publish_runtime",
            status="failure",
            summary="sync_workflows.py failed during publish flow.",
            details={"steps": step_results},
            raw_output="\n".join(filter(None, [sync_result.stdout, sync_result.stderr])),
            log_path=args.debug_log,
        )
        sys.stdout.write(sync_result.stdout)
        sys.stderr.write(sync_result.stderr)
        return sync_result.returncode

    if not args.no_restart:
        restart_command = [
            "docker",
            "compose",
            "-f",
            str(args.compose_file),
            "restart",
            args.service_name,
        ]
        restart_result = run_command(restart_command, cwd=args.compose_dir)
        step_results.append(
            {
                "step": "restart_n8n",
                "command": restart_command,
                "returncode": restart_result.returncode,
            }
        )
        if restart_result.returncode != 0:
            append_debug_log(
                script_name="publish_runtime.py",
                stage="publish_runtime",
                status="failure",
                summary="docker compose restart failed during publish flow.",
                details={"steps": step_results},
                raw_output="\n".join(filter(None, [restart_result.stdout, restart_result.stderr])),
                log_path=args.debug_log,
            )
            sys.stdout.write(restart_result.stdout)
            sys.stderr.write(restart_result.stderr)
            return restart_result.returncode

        try:
            readiness = wait_for_http(
                base_url=base_url,
                timeout_seconds=args.restart_timeout_seconds,
                poll_interval_seconds=args.poll_interval_seconds,
            )
        except Exception as exc:
            append_debug_log(
                script_name="publish_runtime.py",
                stage="publish_runtime",
                status="failure",
                summary=f"n8n did not become reachable after restart: {exc}",
                details={"steps": step_results, "base_url": base_url, "error": str(exc)},
                log_path=args.debug_log,
            )
            print(exc, file=sys.stderr)
            return 1

        step_results.append({"step": "wait_for_n8n", **readiness})

    alignment_command = [
        sys.executable,
        str(script_dir / "check_runtime_alignment.py"),
        "--workflow-dir",
        str(args.workflow_dir),
        "--db-path",
        str(args.db_path),
        "--debug-log",
        str(args.debug_log),
    ]
    if args.include_untracked:
        alignment_command.append("--include-untracked")
    if args.allow_runtime_extras:
        alignment_command.append("--allow-runtime-extras")
    for workflow_id in include_ids:
        alignment_command.extend(["--workflow-id", workflow_id])

    alignment_result = run_command(alignment_command, cwd=args.compose_dir)
    step_results.append(
        {
            "step": "check_runtime_alignment",
            "command": alignment_command,
            "returncode": alignment_result.returncode,
        }
    )
    if alignment_result.returncode != 0:
        append_debug_log(
            script_name="publish_runtime.py",
            stage="publish_runtime",
            status="failure",
            summary="Runtime alignment check failed after sync/restart.",
            details={"steps": step_results},
            raw_output="\n".join(filter(None, [alignment_result.stdout, alignment_result.stderr])),
            log_path=args.debug_log,
        )
        sys.stdout.write(alignment_result.stdout)
        sys.stderr.write(alignment_result.stderr)
        return alignment_result.returncode

    optional_steps = [
        (
            args.run_smoke_qdrant,
            "smoke_qdrant_gate",
            [
                sys.executable,
                str(script_dir / "smoke_qdrant_gate.py"),
                "--env-file",
                str(args.env_file),
                "--debug-log",
                str(args.debug_log),
            ],
        ),
        (
            args.run_verify_transcript,
            "verify_transcript_mainline",
            [
                sys.executable,
                str(script_dir / "verify_transcript_mainline.py"),
                "--env-file",
                str(args.env_file),
                "--db-path",
                str(args.db_path),
                "--base-url",
                base_url,
                "--debug-log",
                str(args.debug_log),
            ],
        ),
    ]

    for enabled, step_name, command in optional_steps:
        if not enabled:
            continue
        result = run_command(command, cwd=args.compose_dir)
        step_results.append(
            {
                "step": step_name,
                "command": command,
                "returncode": result.returncode,
            }
        )
        if result.returncode != 0:
            append_debug_log(
                script_name="publish_runtime.py",
                stage="publish_runtime",
                status="failure",
                summary=f"{step_name} failed during publish flow.",
                details={"steps": step_results},
                raw_output="\n".join(filter(None, [result.stdout, result.stderr])),
                log_path=args.debug_log,
            )
            sys.stdout.write(result.stdout)
            sys.stderr.write(result.stderr)
            return result.returncode

    append_debug_log(
        script_name="publish_runtime.py",
        stage="publish_runtime",
        status="success",
        summary=(
            "Publish flow completed: tracked repo workflows synced, runtime refreshed, "
            "and definition-hash alignment checked."
        ),
        details={"steps": step_results, "debug_log": args.debug_log},
        log_path=args.debug_log,
    )
    print("Publish flow completed with definition-hash alignment.")
    print(f"Central debug log: {args.debug_log.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
