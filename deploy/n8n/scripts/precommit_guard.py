#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import shlex
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[3]
CONTRACT_SCRIPT = ROOT_DIR / "contracts" / "validate_contract.py"
WORKFLOW_BOUNDARY_SCRIPT = Path(__file__).resolve().with_name("validate_workflow_boundaries.py")
SMOKE_SCRIPT = Path(__file__).resolve().with_name("smoke_qdrant_gate.py")
DEFAULT_ENV_FILE = ROOT_DIR / "deploy" / ".env"
DEFAULT_QDRANT_BASE_URL = "http://127.0.0.1:6333"

CONTRACT_TRIGGERS = (
    "contracts/",
    "deploy/n8n/workflows/",
    "deploy/n8n/scripts/precommit_guard.py",
    "deploy/n8n/scripts/validate_workflow_boundaries.py",
    "deploy/README.md",
    "deploy/n8n/WORKFLOW_NOTES.md",
)

SMOKE_TRIGGERS = (
    "deploy/n8n/workflows/",
    "deploy/n8n/scripts/smoke_qdrant_gate.py",
    "deploy/compose.yaml",
    "deploy/.env.example",
)


def normalize_paths(paths: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw in paths:
        value = raw.replace("\\", "/").lstrip("./")
        if value:
            normalized.append(value)
    return normalized


def matches_trigger(path: str, trigger: str) -> bool:
    if trigger.endswith("/"):
        return path.startswith(trigger)
    return path == trigger


def should_run(paths: list[str], triggers: tuple[str, ...]) -> bool:
    if not paths:
        return True
    return any(matches_trigger(path, trigger) for path in paths for trigger in triggers)


def run_command(command: list[str], *, label: str) -> int:
    printable = " ".join(shlex.quote(part) for part in command)
    print(f"[pre-commit] {label}: {printable}")
    completed = subprocess.run(command, cwd=ROOT_DIR)
    return completed.returncode


def ensure_qdrant_reachable(base_url: str) -> bool:
    health_url = f"{base_url.rstrip('/')}/collections"
    try:
        with urllib.request.urlopen(health_url, timeout=5) as response:
            response.read(1)
        return True
    except (urllib.error.URLError, TimeoutError) as exc:
        print(
            "[pre-commit] smoke skipped? no. "
            f"Qdrant is required for workflow smoke but {health_url} is unreachable: {exc}",
            file=sys.stderr,
        )
        return False


def run_contract_check(paths: list[str]) -> int:
    if not should_run(paths, CONTRACT_TRIGGERS):
        print("[pre-commit] contract: skipped (no contract-sensitive files changed)")
        return 0
    contract_exit = run_command([sys.executable, str(CONTRACT_SCRIPT)], label="contract")
    if contract_exit != 0:
        return contract_exit
    return run_command([sys.executable, str(WORKFLOW_BOUNDARY_SCRIPT)], label="workflow-boundary")


def run_smoke_check(paths: list[str], *, env_file: Path, qdrant_base_url: str) -> int:
    if not should_run(paths, SMOKE_TRIGGERS):
        print("[pre-commit] smoke: skipped (no runtime-sensitive files changed)")
        return 0

    if os.getenv("AIP_SKIP_SMOKE") == "1":
        print("[pre-commit] smoke: skipped because AIP_SKIP_SMOKE=1")
        return 0

    if not env_file.exists():
        print(
            f"[pre-commit] smoke: required env file is missing: {env_file}",
            file=sys.stderr,
        )
        return 1

    if not ensure_qdrant_reachable(qdrant_base_url):
        return 1

    command = [
        sys.executable,
        str(SMOKE_SCRIPT),
        "--env-file",
        str(env_file),
        "--qdrant-base-url",
        qdrant_base_url,
        "--no-debug-log",
    ]
    return run_command(command, label="smoke")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Run repo-local contract and smoke checks from pre-commit."
    )
    parser.add_argument(
        "--check",
        choices=("contract", "smoke", "all"),
        default="all",
        help="Which guard to run.",
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=DEFAULT_ENV_FILE,
        help="Path to deploy/.env for runtime smoke.",
    )
    parser.add_argument(
        "--qdrant-base-url",
        default=DEFAULT_QDRANT_BASE_URL,
        help="Host-reachable Qdrant base URL used by runtime smoke.",
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Files staged in the current commit. Pre-commit provides these automatically.",
    )
    args = parser.parse_args(argv)

    paths = normalize_paths(args.paths)

    if args.check == "contract":
        return run_contract_check(paths)

    if args.check == "smoke":
        return run_smoke_check(paths, env_file=args.env_file.resolve(), qdrant_base_url=args.qdrant_base_url)

    contract_exit = run_contract_check(paths)
    if contract_exit != 0:
        return contract_exit
    return run_smoke_check(paths, env_file=args.env_file.resolve(), qdrant_base_url=args.qdrant_base_url)


if __name__ == "__main__":
    raise SystemExit(main())
