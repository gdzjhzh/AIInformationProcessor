#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator


ROOT_DIR = Path(__file__).resolve().parents[3]
WORKFLOW_DIR = ROOT_DIR / "deploy" / "n8n" / "workflows"

LEGACY_FIELDS = (
    "obsidian_inbox_dir",
    "raw_text",
    "raw_html",
    "transcript_text",
    "calibrated_transcript",
    "action",
)

LEGACY_FIELD_PATTERNS: dict[str, tuple[re.Pattern[str], ...]] = {
    field: (
        re.compile(rf"\$json\.{re.escape(field)}\b"),
        re.compile(rf"\$json\[['\"]{re.escape(field)}['\"]\]"),
        re.compile(rf"['\"]{re.escape(field)}['\"]\s*:"),
        re.compile(rf"(?<![A-Za-z0-9_]){re.escape(field)}(?=\s*:)"),
    )
    for field in LEGACY_FIELDS
}

LEGACY_BOUNDARY_MESSAGE = (
    "legacy fields are only allowed in ingress adapters, "
    "00_common_normalize_text_object, and the temporary 05 compatibility shim"
)

ALLOWED_LEGACY_FIELD_ACCESS: dict[str, dict[str, set[str]]] = {
    "00_common_normalize_text_object.json": {
        "Example Source Payload": set(LEGACY_FIELDS),
        "Normalize Text Object": set(LEGACY_FIELDS),
    },
    "01_rss_to_obsidian_raw.json": {
        "Build Normalize Input": {"obsidian_inbox_dir", "raw_text", "raw_html"},
    },
    "04_video_transcript_ingest.json": {
        "Example Transcript Request": {"obsidian_inbox_dir"},
        "Resolve Transcript Result": {"transcript_text"},
        "Transcript Adapter": {
            "obsidian_inbox_dir",
            "raw_text",
            "raw_html",
            "transcript_text",
            "calibrated_transcript",
        },
    },
    "05_common_vault_writer.json": {
        "Prepare Vault Write Context": {"obsidian_inbox_dir"},
    },
    "06_manual_media_submit.json": {
        "Normalize Manual Media Request": {"obsidian_inbox_dir"},
    },
    "90_local_verify_transcript_mainline.json": {
        "Normalize Verify Request": {"obsidian_inbox_dir"},
    },
}

REQUIRED_CONNECTIONS: dict[str, dict[str, set[str]]] = {
    "01_rss_to_obsidian_raw.json": {
        "04 Video Transcript Ingest": {"00 Common Normalize Text Object"},
    },
}

FORBIDDEN_CONNECTIONS: dict[str, dict[str, set[str]]] = {
    "01_rss_to_obsidian_raw.json": {
        "04 Video Transcript Ingest": {"05 Common Vault Writer"},
    },
}


@dataclass(frozen=True)
class ValidationIssue:
    location: str
    message: str


def normalize_paths(paths: list[str]) -> list[str]:
    normalized: list[str] = []
    for raw in paths:
        value = raw.replace("\\", "/").lstrip("./")
        if value:
            normalized.append(value)
    return normalized


def iter_target_workflows(paths: list[str]) -> list[Path]:
    if not paths:
        return sorted(WORKFLOW_DIR.glob("*.json"))

    selected: list[Path] = []
    for raw in paths:
        if not raw.startswith("deploy/n8n/workflows/") or not raw.endswith(".json"):
            continue
        path = (ROOT_DIR / raw).resolve()
        if path.exists():
            selected.append(path)

    deduped = sorted({path for path in selected})
    return deduped


def walk_strings(value: Any, path_parts: list[str]) -> Iterator[tuple[str, str]]:
    if isinstance(value, str):
        yield (".".join(path_parts), value)
        return

    if isinstance(value, dict):
        for key, child in value.items():
            yield from walk_strings(child, [*path_parts, str(key)])
        return

    if isinstance(value, list):
        for index, child in enumerate(value):
            yield from walk_strings(child, [*path_parts, f"[{index}]"])


def collect_connected_nodes(workflow: dict[str, Any], source_node: str) -> set[str]:
    connections = workflow.get("connections", {})
    source_map = connections.get(source_node, {})
    main = source_map.get("main", [])
    result: set[str] = set()
    if not isinstance(main, list):
        return result

    for branch in main:
        if not isinstance(branch, list):
            continue
        for edge in branch:
            if not isinstance(edge, dict):
                continue
            target = edge.get("node")
            if isinstance(target, str) and target.strip():
                result.add(target.strip())
    return result


def validate_legacy_fields(workflow_path: Path, workflow: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    allowed_by_node = ALLOWED_LEGACY_FIELD_ACCESS.get(workflow_path.name, {})

    for index, node in enumerate(workflow.get("nodes", [])):
        if not isinstance(node, dict):
            continue
        node_name = str(node.get("name", f"node-{index}")).strip() or f"node-{index}"
        allowed_fields = allowed_by_node.get(node_name, set())

        for string_path, text in walk_strings(node, [f"nodes[{index}]", node_name]):
            matched_fields = [
                field
                for field, patterns in LEGACY_FIELD_PATTERNS.items()
                if any(pattern.search(text) for pattern in patterns)
            ]
            for field in sorted(set(matched_fields)):
                if field in allowed_fields:
                    continue
                issues.append(
                    ValidationIssue(
                        location=f"{workflow_path.name}:{node_name}:{string_path}",
                        message=f"legacy field {field!r} is not allowed here; {LEGACY_BOUNDARY_MESSAGE}",
                    )
                )

    return issues


def validate_connection_invariants(workflow_path: Path, workflow: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    for source_node, expected_targets in REQUIRED_CONNECTIONS.get(workflow_path.name, {}).items():
        connected = collect_connected_nodes(workflow, source_node)
        missing = sorted(expected_targets - connected)
        for target in missing:
            issues.append(
                ValidationIssue(
                    location=f"{workflow_path.name}:{source_node}",
                    message=f"must connect to {target!r} to stay inside the shared mainline boundary",
                )
            )

    for source_node, forbidden_targets in FORBIDDEN_CONNECTIONS.get(workflow_path.name, {}).items():
        connected = collect_connected_nodes(workflow, source_node)
        unexpected = sorted(forbidden_targets & connected)
        for target in unexpected:
            issues.append(
                ValidationIssue(
                    location=f"{workflow_path.name}:{source_node}",
                    message=f"must not connect directly to {target!r}; route through 00_common_normalize_text_object first",
                )
            )

    return issues


def validate_workflow(workflow_path: Path) -> list[ValidationIssue]:
    document = json.loads(workflow_path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        return [
            ValidationIssue(
                location=workflow_path.name,
                message="workflow root JSON value must be an object",
            )
        ]

    issues = validate_legacy_fields(workflow_path, document)
    issues.extend(validate_connection_invariants(workflow_path, document))
    return issues


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate n8n workflow legacy-field boundaries and shared-mainline invariants."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional changed files. When omitted, all tracked workflow JSON files are checked.",
    )
    args = parser.parse_args(argv)

    target_workflows = iter_target_workflows(normalize_paths(args.paths))
    if not target_workflows:
        print("[workflow-boundary] skipped (no workflow files selected)")
        return 0

    had_errors = False
    for workflow_path in target_workflows:
        issues = validate_workflow(workflow_path)
        if issues:
            had_errors = True
            print(f"[FAIL] {workflow_path}")
            for issue in issues:
                print(f"  - {issue.location}: {issue.message}")
            continue
        print(f"[OK]   {workflow_path}")

    return 1 if had_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
