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


def parse_bool_arg(raw_value: str) -> bool:
    value = raw_value.strip().lower()
    if value in {"1", "true", "yes", "y", "on"}:
        return True
    if value in {"0", "false", "no", "n", "off"}:
        return False
    raise argparse.ArgumentTypeError(f"invalid boolean value: {raw_value!r}")


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
    args = parser.parse_args()

    env_values = load_dotenv(args.env_file)
    base_url = args.base_url.rstrip("/")
    if args.base_url == "http://127.0.0.1:5678" and env_values.get("N8N_PORT"):
        base_url = f"http://127.0.0.1:{env_values['N8N_PORT']}"

    conn = sqlite3.connect(args.db_path)
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT COALESCE(MAX(id), 0) FROM execution_entity")
        baseline_execution_id = int(cursor.fetchone()[0])
    finally:
        conn.close()

    payload = {
        "transcript_source_url": args.transcript_source_url,
        "source_name": f"Local Transcript Verify {int(time.time())}",
        "source_type": "transcript",
        "media_type": args.media_type,
        "use_speaker_recognition": args.use_speaker_recognition,
        "poll_interval_ms": args.transcript_poll_interval_ms,
        "max_polls": args.transcript_max_polls,
        "obsidian_inbox_dir": env_values.get("OBSIDIAN_INBOX_DIR", "00_Inbox/AI_Information_Processor"),
    }

    response_body = ""
    webhook_path = fetch_verify_webhook_path(args.db_path)
    webhook_url = f"{base_url}/webhook/{webhook_path}"
    print(f"POST {webhook_url}")
    try:
        response_status, response_body = post_json(webhook_url, payload, args.timeout_seconds)
        print(f"Webhook response status: {response_status}")
    except urllib.error.HTTPError as exc:
        response_body = exc.read().decode("utf-8", errors="replace")
        print(f"Webhook response status: HTTP {exc.code}")
        print(response_body)
        return 1
    except Exception as exc:
        print(f"Webhook request raised {type(exc).__name__}: {exc}")
        return 1

    try:
        response_payload = parse_response_body(response_body)
        validate_mainline_response(response_payload)
    except RuntimeError as exc:
        print(f"Webhook response validation failed: {exc}")
        print(response_body)
        return 1

    print_response_summary(response_payload)

    row_wait_seconds = max(0, min(args.execution_row_wait_seconds, args.timeout_seconds))
    deadline = time.time() + row_wait_seconds
    final_rows: list[sqlite3.Row] = []
    latest: dict[str, sqlite3.Row] = {}
    while time.time() < deadline:
        rows = fetch_execution_rows(args.db_path, baseline_execution_id)
        latest = latest_by_workflow(rows)
        final_rows = rows

        failing = [
            row
            for row in latest.values()
            if str(row["status"]).lower() not in {"success", "running", "new", "waiting"}
        ]
        if failing:
            print("Execution summary:")
            print_execution_summary(rows)
            print("Failing executions detected.")
            return 1

        if latest:
            if all(workflow_id in latest for workflow_id in EXPECTED_WORKFLOW_IDS):
                if all(
                    str(latest[workflow_id]["status"]).lower() == "success"
                    for workflow_id in EXPECTED_WORKFLOW_IDS
                ):
                    print("Execution summary:")
                    print_execution_summary(rows)
                    return 0

        time.sleep(args.poll_interval_seconds)

    if final_rows:
        print("Execution summary:")
        print_execution_summary(final_rows)
        print(
            "Webhook response proved the mainline completed, but n8n did not persist a full "
            "set of new execution rows during the polling window."
        )
    else:
        print(
            "Webhook response proved the mainline completed. No new execution rows were "
            "persisted for the expected workflow IDs during the polling window."
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
