from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_SCHEMA_PATH = ROOT_DIR / "normalized_text_object.schema.json"
DEFAULT_EXAMPLE_DIR = ROOT_DIR / "examples"


@dataclass
class ValidationIssue:
    path: str
    message: str


def _format_path(path_parts: list[str]) -> str:
    if not path_parts:
      return "$"
    return "$." + ".".join(path_parts)


def _load_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def _is_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _matches_type(expected: str, value: Any) -> bool:
    type_checks = {
        "object": lambda candidate: isinstance(candidate, dict),
        "array": lambda candidate: isinstance(candidate, list),
        "string": lambda candidate: isinstance(candidate, str),
        "number": _is_number,
        "integer": lambda candidate: isinstance(candidate, int) and not isinstance(candidate, bool),
        "boolean": lambda candidate: isinstance(candidate, bool),
        "null": lambda candidate: candidate is None,
    }
    checker = type_checks.get(expected)
    if checker is None:
        raise ValueError(f"Unsupported schema type: {expected}")
    return checker(value)


def _check_format(value: str, fmt: str) -> bool:
    if fmt == "date-time":
        try:
            datetime.fromisoformat(value.replace("Z", "+00:00"))
            return True
        except ValueError:
            return False

    if fmt == "uri":
        parsed = urlparse(value)
        return bool(parsed.scheme and parsed.netloc)

    raise ValueError(f"Unsupported format checker: {fmt}")


def _validate_schema(
    value: Any,
    schema: dict[str, Any],
    path_parts: list[str],
    issues: list[ValidationIssue],
) -> None:
    expected_type = schema.get("type")
    if expected_type is not None:
        expected_types = expected_type if isinstance(expected_type, list) else [expected_type]
        if not any(_matches_type(candidate_type, value) for candidate_type in expected_types):
            expected_display = " | ".join(expected_types)
            issues.append(
                ValidationIssue(
                    path=_format_path(path_parts),
                    message=f"expected type {expected_display}, got {type(value).__name__}",
                )
            )
            return

    if "enum" in schema and value not in schema["enum"]:
        issues.append(
            ValidationIssue(
                path=_format_path(path_parts),
                message=f"value {value!r} is not in enum {schema['enum']!r}",
            )
        )

    if isinstance(value, str):
        min_length = schema.get("minLength")
        if min_length is not None and len(value) < min_length:
            issues.append(
                ValidationIssue(
                    path=_format_path(path_parts),
                    message=f"string length {len(value)} is smaller than minLength {min_length}",
                )
            )

        pattern = schema.get("pattern")
        if pattern and re.search(pattern, value) is None:
            issues.append(
                ValidationIssue(
                    path=_format_path(path_parts),
                    message=f"string does not match pattern {pattern!r}",
                )
            )

        value_format = schema.get("format")
        if value_format and not _check_format(value, value_format):
            issues.append(
                ValidationIssue(
                    path=_format_path(path_parts),
                    message=f"string is not a valid {value_format}",
                )
            )

    if _is_number(value):
        minimum = schema.get("minimum")
        if minimum is not None and value < minimum:
            issues.append(
                ValidationIssue(
                    path=_format_path(path_parts),
                    message=f"number {value} is smaller than minimum {minimum}",
                )
            )

        maximum = schema.get("maximum")
        if maximum is not None and value > maximum:
            issues.append(
                ValidationIssue(
                    path=_format_path(path_parts),
                    message=f"number {value} is larger than maximum {maximum}",
                )
            )

    if isinstance(value, list):
        min_items = schema.get("minItems")
        if min_items is not None and len(value) < min_items:
            issues.append(
                ValidationIssue(
                    path=_format_path(path_parts),
                    message=f"array length {len(value)} is smaller than minItems {min_items}",
                )
            )

        if schema.get("uniqueItems"):
            seen: set[str] = set()
            duplicates: list[str] = []
            for item in value:
                item_key = json.dumps(item, ensure_ascii=False, sort_keys=True)
                if item_key in seen and item_key not in duplicates:
                    duplicates.append(item_key)
                seen.add(item_key)
            if duplicates:
                issues.append(
                    ValidationIssue(
                        path=_format_path(path_parts),
                        message="array contains duplicate items",
                    )
                )

        item_schema = schema.get("items")
        if isinstance(item_schema, dict):
            for index, item in enumerate(value):
                _validate_schema(item, item_schema, [*path_parts, f"[{index}]"], issues)

    if isinstance(value, dict):
        required_fields = schema.get("required", [])
        for field in required_fields:
            if field not in value:
                issues.append(
                    ValidationIssue(
                        path=_format_path(path_parts),
                        message=f"missing required field {field!r}",
                    )
                )

        canonical_mappings = schema.get("x-canonicalMappings", {})
        for forbidden_field in schema.get("x-forbiddenProperties", []):
            if forbidden_field in value:
                canonical_field = canonical_mappings.get(forbidden_field)
                if canonical_field:
                    message = f"forbidden field {forbidden_field!r}; use canonical field {canonical_field!r}"
                else:
                    message = f"forbidden field {forbidden_field!r}"
                issues.append(
                    ValidationIssue(
                        path=_format_path([*path_parts, forbidden_field]),
                        message=message,
                    )
                )

        properties = schema.get("properties", {})
        if schema.get("additionalProperties") is False:
            for field in value:
                if field not in properties:
                    issues.append(
                        ValidationIssue(
                            path=_format_path([*path_parts, field]),
                            message="field is not allowed by schema",
                        )
                    )

        for field, field_schema in properties.items():
            if field in value and isinstance(field_schema, dict):
                _validate_schema(value[field], field_schema, [*path_parts, field], issues)


def _validate_semantics(document: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    status = str(document.get("status", "")).strip()
    if status in {"enriched", "deduped"}:
        if not str(document.get("summary", "")).strip():
            issues.append(
                ValidationIssue(path="$.summary", message=f"summary is required when status={status!r}")
            )
        if not str(document.get("reason", "")).strip():
            issues.append(
                ValidationIssue(path="$.reason", message=f"reason is required when status={status!r}")
            )
        if not str(document.get("enriched_at", "")).strip():
            issues.append(
                ValidationIssue(path="$.enriched_at", message=f"enriched_at is required when status={status!r}")
            )

    if document.get("dedupe_action") == "silent" and document.get("should_write_to_vault") is True:
        issues.append(
            ValidationIssue(
                path="$.should_write_to_vault",
                message="silent items must not request Vault write",
            )
        )

    vault_write_status = str(document.get("vault_write_status", "")).strip()
    if vault_write_status == "written" and not str(document.get("vault_path", "")).strip():
        issues.append(
            ValidationIssue(
                path="$.vault_path",
                message="vault_path must be non-empty when vault_write_status='written'",
            )
        )

    if document.get("qdrant_operation") == "upserted" and vault_write_status != "written":
        issues.append(
            ValidationIssue(
                path="$.qdrant_operation",
                message="Qdrant cannot be upserted before Vault write succeeds",
            )
        )

    if document.get("should_upsert_qdrant") is True:
        if not str(document.get("qdrant_upsert_endpoint", "")).strip():
            issues.append(
                ValidationIssue(
                    path="$.qdrant_upsert_endpoint",
                    message="qdrant_upsert_endpoint is required when should_upsert_qdrant=true",
                )
            )
        payload = document.get("qdrant_upsert_payload")
        if not isinstance(payload, dict) or not isinstance(payload.get("points"), list) or not payload["points"]:
            issues.append(
                ValidationIssue(
                    path="$.qdrant_upsert_payload",
                    message="qdrant_upsert_payload.points must be a non-empty array when should_upsert_qdrant=true",
                )
            )

    return issues


def validate_document(document: dict[str, Any], schema: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    _validate_schema(document, schema, [], issues)
    issues.extend(_validate_semantics(document))
    return issues


def _collect_target_files(paths: list[str], example_dir: Path) -> list[Path]:
    if paths:
        return [Path(path).resolve() for path in paths]
    return sorted(example_dir.glob("*.json"))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate NormalizedTextObject examples or captured payloads against the machine-readable contract."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional JSON files to validate. Defaults to contracts/examples/*.json.",
    )
    parser.add_argument(
        "--schema",
        default=str(DEFAULT_SCHEMA_PATH),
        help="Path to the contract schema JSON file.",
    )
    parser.add_argument(
        "--example-dir",
        default=str(DEFAULT_EXAMPLE_DIR),
        help="Directory containing example JSON files used when no explicit paths are provided.",
    )
    args = parser.parse_args(argv)

    schema_path = Path(args.schema).resolve()
    example_dir = Path(args.example_dir).resolve()
    target_files = _collect_target_files(args.paths, example_dir)

    if not target_files:
        print("No JSON files found to validate.", file=sys.stderr)
        return 1

    schema = _load_json(schema_path)
    had_errors = False

    for target_file in target_files:
        document = _load_json(target_file)
        if not isinstance(document, dict):
            print(f"[FAIL] {target_file}: root JSON value must be an object", file=sys.stderr)
            had_errors = True
            continue

        issues = validate_document(document, schema)
        if issues:
            had_errors = True
            print(f"[FAIL] {target_file}")
            for issue in issues:
                print(f"  - {issue.path}: {issue.message}")
            continue

        print(f"[OK]   {target_file}")

    return 1 if had_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
