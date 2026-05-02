#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import sqlite3
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

from debug_log import append_debug_log, default_debug_log_path

VERIFY_WORKFLOW_ID = "918c7f6da45023eb"
TRANSCRIPT_WORKFLOW_ID = "acb525fca8ea4dc4"
NORMALIZE_WORKFLOW_ID = "d4f093a8e2f74e39"
ENRICH_WORKFLOW_ID = "828e50ae98c24f31"
GATE_WORKFLOW_ID = "a793499a65e344bc"
EXPECTED_WORKFLOW_IDS = [
    VERIFY_WORKFLOW_ID,
    TRANSCRIPT_WORKFLOW_ID,
    NORMALIZE_WORKFLOW_ID,
    ENRICH_WORKFLOW_ID,
    GATE_WORKFLOW_ID,
]


class VerificationError(RuntimeError):
    def __init__(self, message: str, details: dict[str, Any] | None = None):
        super().__init__(message)
        self.details = details or {}


def load_dotenv(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def post_json(url: str, payload: dict, timeout_seconds: int) -> tuple[int, str]:
    req = urllib.request.Request(
        url,
        method="POST",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout_seconds) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        return resp.status, body


def parse_response_body(response_body: str) -> dict[str, Any]:
    try:
        payload = json.loads(response_body)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Webhook returned non-JSON body: {exc}") from exc

    if not isinstance(payload, dict):
        raise RuntimeError("Webhook returned JSON, but it was not an object.")

    return payload


def validate_mainline_response(payload: dict[str, Any]) -> None:
    required_keys = ["item_id", "content_hash", "summary", "dedupe_action"]
    missing = [key for key in required_keys if not payload.get(key)]
    if missing:
        raise RuntimeError(
            "Webhook response is missing keys that prove the mainline completed: "
            + ", ".join(missing)
        )

    dedupe_action = str(payload.get("dedupe_action", "")).strip().lower()
    if dedupe_action not in {"push", "diff_push", "silent"}:
        raise RuntimeError(f"Unexpected dedupe_action in webhook response: {dedupe_action!r}")

    original_item = payload.get("original_item")
    if not isinstance(original_item, dict):
        raise RuntimeError("Webhook response is missing original_item from 04.")


def print_response_summary(payload: dict[str, Any]) -> None:
    summary_fields = [
        ("item_id", payload.get("item_id")),
        ("title", payload.get("title")),
        ("status", payload.get("status")),
        ("dedupe_action", payload.get("dedupe_action")),
        ("matched_score", payload.get("matched_score")),
        ("vault_path", payload.get("vault_path")),
    ]
    print("Webhook response summary:")
    for key, value in summary_fields:
        print(f"  - {key}: {value}")


def response_summary(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": payload.get("item_id"),
        "title": payload.get("title"),
        "status": payload.get("status"),
        "dedupe_action": payload.get("dedupe_action"),
        "matched_score": payload.get("matched_score"),
        "vault_path": payload.get("vault_path"),
    }


def fetch_execution_rows(db_path: Path, min_id: int) -> list[sqlite3.Row]:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        cursor = conn.cursor()
        placeholders = ",".join("?" for _ in EXPECTED_WORKFLOW_IDS)
        cursor.execute(
            f"""
            SELECT id, workflowId, status, mode, startedAt, stoppedAt
            FROM execution_entity
            WHERE id > ? AND workflowId IN ({placeholders})
            ORDER BY id ASC
            """,
            (min_id, *EXPECTED_WORKFLOW_IDS),
        )
        return cursor.fetchall()
    finally:
        conn.close()


def fetch_verify_webhook_path(db_path: Path) -> str:
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT webhookPath
            FROM webhook_entity
            WHERE workflowId = ?
            ORDER BY rowid DESC
            LIMIT 1
            """,
            (VERIFY_WORKFLOW_ID,),
        )
        row = cursor.fetchone()
    finally:
        conn.close()

    if row is None or not row[0]:
        raise RuntimeError(
            "Verification webhook is not registered in webhook_entity for workflow "
            f"{VERIFY_WORKFLOW_ID}. Re-sync workflows and restart n8n first."
        )

    return str(row[0]).strip()


def latest_by_workflow(rows: list[sqlite3.Row]) -> dict[str, sqlite3.Row]:
    latest: dict[str, sqlite3.Row] = {}
    for row in rows:
        latest[row["workflowId"]] = row
    return latest


def print_execution_summary(rows: list[sqlite3.Row]) -> None:
    latest = latest_by_workflow(rows)
    for workflow_id in EXPECTED_WORKFLOW_IDS:
        row = latest.get(workflow_id)
        if row is None:
            print(f"  - {workflow_id}: missing")
            continue
        print(
            "  - "
            f"{workflow_id}: status={row['status']} mode={row['mode']} "
            f"execution_id={row['id']} startedAt={row['startedAt']} stoppedAt={row['stoppedAt']}"
        )


def execution_summary(rows: list[sqlite3.Row]) -> list[dict[str, Any]]:
    latest = latest_by_workflow(rows)
    summary: list[dict[str, Any]] = []
    for workflow_id in EXPECTED_WORKFLOW_IDS:
        row = latest.get(workflow_id)
        summary.append(
            {
                "workflow_id": workflow_id,
                "status": str(row["status"]) if row is not None else "missing",
                "mode": str(row["mode"]) if row is not None else None,
                "execution_id": int(row["id"]) if row is not None else None,
                "startedAt": str(row["startedAt"]) if row is not None else None,
                "stoppedAt": str(row["stoppedAt"]) if row is not None else None,
            }
        )
    return summary


def parse_bool_arg(raw_value: str) -> bool:
    value = raw_value.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean value: {raw_value!r}")


def run_verification(
    *,
    env_file: Path,
    db_path: Path,
    base_url: str,
    transcript_source_url: str,
    media_type: str,
    use_speaker_recognition: bool,
    transcript_poll_interval_ms: int,
    transcript_max_polls: int,
    timeout_seconds: int,
    poll_interval_seconds: float,
    execution_row_wait_seconds: int,
) -> dict[str, Any]:
    env_file = env_file.resolve()
    db_path = db_path.resolve()
    env_values = load_dotenv(env_file)
    resolved_base_url = base_url.rstrip("/")
    if base_url == "http://127.0.0.1:5678" and env_values.get("N8N_PORT"):
        resolved_base_url = f"http://127.0.0.1:{env_values['N8N_PORT']}"

    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(id), 0) FROM execution_entity")
        baseline_execution_id = int(cursor.fetchone()[0])
    finally:
        conn.close()

    payload = {
        "transcript_source_url": transcript_source_url,
        "source_name": f"Local Transcript Verify {int(time.time())}",
        "source_type": "transcript",
        "media_type": media_type,
        "use_speaker_recognition": use_speaker_recognition,
        "poll_interval_ms": transcript_poll_interval_ms,
        "max_polls": transcript_max_polls,
        "obsidian_inbox_dir": env_values.get("OBSIDIAN_INBOX_DIR", "00_Inbox/Signal_To_Obsidian"),
    }

    webhook_path = fetch_verify_webhook_path(db_path)
    webhook_url = f"{resolved_base_url}/webhook/{webhook_path}"
    details: dict[str, Any] = {
        "env_file": env_file,
        "db_path": db_path,
        "base_url": resolved_base_url,
        "webhook_url": webhook_url,
        "payload": payload,
        "baseline_execution_id": baseline_execution_id,
    }

    try:
        response_status, response_body = post_json(webhook_url, payload, timeout_seconds)
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        details.update(
            {
                "response_status": f"HTTP {exc.code}",
                "response_body": response_body,
            }
        )
        raise VerificationError(f"Webhook responded with HTTP {exc.code}", details) from exc
    except Exception as exc:
        details["request_error"] = f"{type(exc).__name__}: {exc}"
        raise VerificationError(f"Webhook request failed: {exc}", details) from exc

    details.update(
        {
            "response_status": response_status,
            "response_body": response_body,
        }
    )

    try:
        response_payload = parse_response_body(response_body)
        validate_mainline_response(response_payload)
    except RuntimeError as exc:
        details["response_validation_error"] = str(exc)
        raise VerificationError(f"Webhook response validation failed: {exc}", details) from exc

    details["response_summary"] = response_summary(response_payload)

    row_wait_seconds = max(0, min(execution_row_wait_seconds, timeout_seconds))
    deadline = time.time() + row_wait_seconds
    final_rows: list[sqlite3.Row] = []

    while time.time() < deadline:
        rows = fetch_execution_rows(db_path, baseline_execution_id)
        latest = latest_by_workflow(rows)
        final_rows = rows

        failing = [
            row
            for row in latest.values()
            if str(row["status"]).lower() not in {"success", "running", "new", "waiting"}
        ]
        if failing:
            details["execution_summary"] = execution_summary(rows)
            raise VerificationError("Failing executions detected.", details)

        if latest and all(workflow_id in latest for workflow_id in EXPECTED_WORKFLOW_IDS):
            if all(
                str(latest[workflow_id]["status"]).lower() == "success"
                for workflow_id in EXPECTED_WORKFLOW_IDS
            ):
                details["execution_summary"] = execution_summary(rows)
                details["execution_wait_result"] = "all_expected_workflows_succeeded"
                return details

        time.sleep(poll_interval_seconds)

    if final_rows:
        details["execution_summary"] = execution_summary(final_rows)
        details["execution_wait_result"] = (
            "webhook_succeeded_but_execution_rows_were_partial_during_poll_window"
        )
        return details

    details["execution_summary"] = []
    details["execution_wait_result"] = (
        "webhook_succeeded_without_persisted_execution_rows_during_poll_window"
    )
    return details


def print_verification_result(result: dict[str, Any]) -> None:
    print(f"POST {result['webhook_url']}")
    print(f"Webhook response status: {result['response_status']}")
    print("Webhook response summary:")
    for key, value in result["response_summary"].items():
        print(f"  - {key}: {value}")
    if result["execution_summary"]:
        print("Execution summary:")
        for row in result["execution_summary"]:
            print(
                "  - "
                f"{row['workflow_id']}: status={row['status']} mode={row['mode']} "
                f"execution_id={row['execution_id']} startedAt={row['startedAt']} "
                f"stoppedAt={row['stoppedAt']}"
            )
    if result["execution_wait_result"] == "all_expected_workflows_succeeded":
        return
    if result["execution_summary"]:
        print(
            "Webhook response proved the mainline completed, but n8n did not persist a full "
            "set of new execution rows during the polling window."
        )
    else:
        print(
            "Webhook response proved the mainline completed. No new execution rows were "
            "persisted for the expected workflow IDs during the polling window."
        )


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="backslashreplace")

    parser = argparse.ArgumentParser(
        description="Trigger the live local verification webhook and confirm that 90 -> 04 -> 00 -> 02 -> 03 all executed successfully in the main n8n instance."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(__file__).resolve().parents[2] / ".env",
        help="Path to deploy/.env.",
    )
    parser.add_argument(
        "--db-path",
        type=Path,
        default=Path(__file__).resolve().parents[2] / "data" / "n8n" / "database.sqlite",
        help="Path to the live n8n SQLite database.",
    )
    parser.add_argument(
        "--base-url",
        default="http://127.0.0.1:5678",
        help="Base URL for the local n8n instance.",
    )
    parser.add_argument(
        "--transcript-source-url",
        default="https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        help="Video URL sent into the validation webhook.",
    )
    parser.add_argument(
        "--media-type",
        default="video",
        help="media_type sent into workflow 04.",
    )
    parser.add_argument(
        "--use-speaker-recognition",
        type=parse_bool_arg,
        default=False,
        help="Whether workflow 04 should request speaker recognition from VideoTranscriptAPI.",
    )
    parser.add_argument(
        "--transcript-poll-interval-ms",
        type=int,
        default=3000,
        help="poll_interval_ms sent into workflow 04 for Transcript API status polling.",
    )
    parser.add_argument(
        "--transcript-max-polls",
        type=int,
        default=40,
        help="max_polls sent into workflow 04 for Transcript API status polling.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=180,
        help="Webhook request timeout and execution wait timeout in seconds.",
    )
    parser.add_argument(
        "--poll-interval-seconds",
        type=float,
        default=2.0,
        help="Polling interval while waiting for execution rows to finish.",
    )
    parser.add_argument(
        "--execution-row-wait-seconds",
        type=int,
        default=20,
        help="How long to wait for optional execution_entity rows after the webhook already returned a valid mainline response.",
    )
    parser.add_argument(
        "--debug-log",
        type=Path,
        default=default_debug_log_path(),
        help="Append a summary to this debug log file.",
    )
    args = parser.parse_args()

    try:
        result = run_verification(
            env_file=args.env_file,
            db_path=args.db_path,
            base_url=args.base_url,
            transcript_source_url=args.transcript_source_url,
            media_type=args.media_type,
            use_speaker_recognition=args.use_speaker_recognition,
            transcript_poll_interval_ms=args.transcript_poll_interval_ms,
            transcript_max_polls=args.transcript_max_polls,
            timeout_seconds=args.timeout_seconds,
            poll_interval_seconds=args.poll_interval_seconds,
            execution_row_wait_seconds=args.execution_row_wait_seconds,
        )
        print_verification_result(result)
        append_debug_log(
            script_name="verify_transcript_mainline.py",
            stage="verify_transcript_mainline",
            status="success",
            summary=(
                "Verification webhook completed and the mainline returned a valid response."
            ),
            details=result,
            log_path=args.debug_log,
        )
        return 0
    except VerificationError as exc:
        details = exc.details or {
            "env_file": args.env_file,
            "db_path": args.db_path,
            "base_url": args.base_url,
        }
        append_debug_log(
            script_name="verify_transcript_mainline.py",
            stage="verify_transcript_mainline",
            status="failure",
            summary=str(exc),
            details=details,
            log_path=args.debug_log,
        )
        print(exc, file=sys.stderr)
        response_body = details.get("response_body")
        if response_body:
            print(response_body, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
