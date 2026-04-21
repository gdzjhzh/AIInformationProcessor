from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlparse


ROOT_DIR = Path(__file__).resolve().parent
DEFAULT_SCHEMA_PATH = ROOT_DIR / "normalized_text_object.schema.json"
DEFAULT_EXAMPLE_DIR = ROOT_DIR / "examples"


@dataclass(frozen=True)
class ValidationIssue:
    path: str
    message: str


@dataclass(frozen=True)
class ContractSpec:
    name: str
    schema_path: Path
    example_suffix: str


@dataclass(frozen=True)
class TargetFile:
    path: Path
    contract_name: str | None
    schema_path: Path


CONTRACT_SPECS = {
    "normalized_text_object": ContractSpec(
        name="normalized_text_object",
        schema_path=ROOT_DIR / "normalized_text_object.schema.json",
        example_suffix="normalized",
    ),
    "llm_score": ContractSpec(
        name="llm_score",
        schema_path=ROOT_DIR / "llm_score.schema.json",
        example_suffix="llm_score",
    ),
    "dedupe_decision": ContractSpec(
        name="dedupe_decision",
        schema_path=ROOT_DIR / "dedupe_decision.schema.json",
        example_suffix="dedupe_decision",
    ),
    "action_policy_decision": ContractSpec(
        name="action_policy_decision",
        schema_path=ROOT_DIR / "action_policy_decision.schema.json",
        example_suffix="action_policy_decision",
    ),
    "writer_result": ContractSpec(
        name="writer_result",
        schema_path=ROOT_DIR / "writer_result.schema.json",
        example_suffix="writer_result",
    ),
}


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


def _validate_score_compatibility(document: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    ai_score = document.get("ai_score")
    score_scale = document.get("score_scale")
    score = document.get("score")
    if isinstance(ai_score, dict):
        if not isinstance(score_scale, int) or score_scale <= 0:
            issues.append(
                ValidationIssue(
                    path="$.score_scale",
                    message="score_scale must be a positive integer when ai_score is present",
                )
            )
        keep_score = ai_score.get("keep_score")
        if _is_number(keep_score) and _is_number(score) and isinstance(score_scale, int) and score_scale > 0:
            expected_score = round(float(keep_score) / float(score_scale), 6)
            actual_score = round(float(score), 6)
            if abs(expected_score - actual_score) > 0.0005:
                issues.append(
                    ValidationIssue(
                        path="$.score",
                        message=(
                            "score must stay compatible with ai_score.keep_score / score_scale "
                            f"(expected {expected_score}, got {actual_score})"
                        ),
                    )
                )
    return issues


def _validate_normalized_text_object_semantics(document: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    content_hash = str(document.get("content_hash", "")).strip()
    if content_hash and not content_hash.startswith("sha256:"):
        issues.append(
            ValidationIssue(
                path="$.content_hash",
                message="content_hash must use the canonical 'sha256:' prefix",
            )
        )

    tags = document.get("tags")
    if isinstance(tags, list) and len(tags) == 0:
        issues.append(
            ValidationIssue(
                path="$.tags",
                message="Stage 0 output must preserve at least one normalized tag",
            )
        )

    privacy_level = str(document.get("privacy_level", "")).strip().lower()
    external_llm_allowed = document.get("external_llm_allowed")
    if privacy_level in {"private", "sensitive"} and external_llm_allowed is not False:
        issues.append(
            ValidationIssue(
                path="$.external_llm_allowed",
                message="private/sensitive normalized items must set external_llm_allowed=false",
            )
        )

    return issues


def _validate_llm_score_semantics(document: dict[str, Any]) -> list[ValidationIssue]:
    return _validate_score_compatibility(document)


def _validate_dedupe_decision_semantics(document: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    dedupe_action = str(document.get("dedupe_action", "")).strip()
    notification_mode = str(document.get("notification_mode", "")).strip()
    should_continue_to_llm = document.get("should_continue_to_llm")
    should_write_to_vault = document.get("should_write_to_vault")
    should_notify = document.get("should_notify")
    should_upsert_qdrant = document.get("should_upsert_qdrant")
    status = str(document.get("status", "")).strip()
    qdrant_operation = str(document.get("qdrant_operation", "")).strip()

    expected_notification_mode = {
        "full_push": "full",
        "diff_push": "incremental",
        "silent": "silent",
    }.get(dedupe_action)
    if expected_notification_mode and notification_mode != expected_notification_mode:
        issues.append(
            ValidationIssue(
                path="$.notification_mode",
                message=f"notification_mode must be {expected_notification_mode!r} when dedupe_action={dedupe_action!r}",
            )
        )

    if document.get("matched_same_content") is True and document.get("matched_same_item") is not True:
        issues.append(
            ValidationIssue(
                path="$.matched_same_content",
                message="matched_same_content=true requires matched_same_item=true",
            )
        )

    if dedupe_action == "silent":
        if should_continue_to_llm is not False:
            issues.append(
                ValidationIssue(
                    path="$.should_continue_to_llm",
                    message="silent dedupe decisions must stop before the LLM stage",
                )
            )
        if should_write_to_vault is not False:
            issues.append(
                ValidationIssue(
                    path="$.should_write_to_vault",
                    message="silent dedupe decisions must not request Vault writes",
                )
            )
        if should_notify is not False:
            issues.append(
                ValidationIssue(
                    path="$.should_notify",
                    message="silent dedupe decisions must not request notifications",
                )
            )
        if should_upsert_qdrant is not False:
            issues.append(
                ValidationIssue(
                    path="$.should_upsert_qdrant",
                    message="silent dedupe decisions must not request Qdrant upserts",
                )
            )
        if status != "deduped":
            issues.append(
                ValidationIssue(
                    path="$.status",
                    message="silent dedupe decisions must set status='deduped'",
                )
            )
        if qdrant_operation != "skipped":
            issues.append(
                ValidationIssue(
                    path="$.qdrant_operation",
                    message="silent dedupe decisions must skip Qdrant writes",
                )
            )
    elif should_continue_to_llm is True and qdrant_operation != "pending":
        issues.append(
            ValidationIssue(
                path="$.qdrant_operation",
                message="non-silent dedupe decisions must leave Qdrant in pending state",
            )
        )
    elif should_continue_to_llm is False and qdrant_operation != "skipped":
        issues.append(
            ValidationIssue(
                path="$.qdrant_operation",
                message="when should_continue_to_llm=false, qdrant_operation must be 'skipped'",
            )
        )

    return issues


def _validate_action_policy_decision_semantics(document: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    should_write_to_vault = document.get("should_write_to_vault")
    should_notify = document.get("should_notify")
    should_upsert_qdrant = document.get("should_upsert_qdrant")
    notification_mode = str(document.get("notification_mode", "")).strip()
    status = str(document.get("status", "")).strip()
    qdrant_operation = str(document.get("qdrant_operation", "")).strip()

    if should_notify is True and should_write_to_vault is not True:
        issues.append(
            ValidationIssue(
                path="$.should_notify",
                message="notifications require should_write_to_vault=true",
            )
        )

    if should_upsert_qdrant is True and should_write_to_vault is not True:
        issues.append(
            ValidationIssue(
                path="$.should_upsert_qdrant",
                message="Qdrant upserts require should_write_to_vault=true",
            )
        )

    if should_notify is True and notification_mode == "silent":
        issues.append(
            ValidationIssue(
                path="$.notification_mode",
                message="should_notify=true cannot use notification_mode='silent'",
            )
        )

    if should_notify is not True and notification_mode != "silent":
        issues.append(
            ValidationIssue(
                path="$.notification_mode",
                message="notification_mode must be 'silent' when should_notify=false",
            )
        )

    if should_write_to_vault is True:
        if status != "enriched":
            issues.append(
                ValidationIssue(
                    path="$.status",
                    message="should_write_to_vault=true requires status='enriched'",
                )
            )
        if should_upsert_qdrant is True and qdrant_operation != "pending":
            issues.append(
                ValidationIssue(
                    path="$.qdrant_operation",
                    message="Qdrant writes must stay pending until 03b_qdrant_commit",
                )
            )
        if should_upsert_qdrant is not True and qdrant_operation != "skipped":
            issues.append(
                ValidationIssue(
                    path="$.qdrant_operation",
                    message="qdrant_operation must be 'skipped' when should_upsert_qdrant=false",
                )
            )
    else:
        if status != "deduped":
            issues.append(
                ValidationIssue(
                    path="$.status",
                    message="should_write_to_vault=false requires status='deduped'",
                )
            )
        if should_upsert_qdrant is not False:
            issues.append(
                ValidationIssue(
                    path="$.should_upsert_qdrant",
                    message="should_write_to_vault=false must also disable Qdrant upserts",
                )
            )
        if qdrant_operation != "skipped":
            issues.append(
                ValidationIssue(
                    path="$.qdrant_operation",
                    message="should_write_to_vault=false must skip Qdrant writes",
                )
            )

    return issues


def _validate_writer_result_semantics(document: dict[str, Any]) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []

    vault_path = str(document.get("vault_path", "")).strip()
    vault_write_status = str(document.get("vault_write_status", "")).strip()
    vault_write = str(document.get("vault_write", "")).strip()
    qdrant_operation = str(document.get("qdrant_operation", "")).strip()

    if vault_write_status != vault_write:
        issues.append(
            ValidationIssue(
                path="$.vault_write",
                message="vault_write must stay identical to vault_write_status",
            )
        )

    if vault_write_status == "written" and not vault_path:
        issues.append(
            ValidationIssue(
                path="$.vault_path",
                message="vault_path must be non-empty when vault_write_status='written'",
            )
        )

    if qdrant_operation == "pending" and vault_write_status != "written":
        issues.append(
            ValidationIssue(
                path="$.qdrant_operation",
                message="Qdrant can only remain pending after a successful Vault write",
            )
        )

    if vault_write_status in {"skipped", "error"} and qdrant_operation != "skipped":
        issues.append(
            ValidationIssue(
                path="$.qdrant_operation",
                message="skipped/error Vault writes must not leave Qdrant pending",
            )
        )

    return issues


SEMANTIC_VALIDATORS: dict[str, Callable[[dict[str, Any]], list[ValidationIssue]]] = {
    "normalized_text_object": _validate_normalized_text_object_semantics,
    "llm_score": _validate_llm_score_semantics,
    "dedupe_decision": _validate_dedupe_decision_semantics,
    "action_policy_decision": _validate_action_policy_decision_semantics,
    "writer_result": _validate_writer_result_semantics,
}


def validate_document(
    document: dict[str, Any],
    schema: dict[str, Any],
    *,
    contract_name: str | None = None,
) -> list[ValidationIssue]:
    issues: list[ValidationIssue] = []
    _validate_schema(document, schema, [], issues)

    if contract_name is not None:
        semantic_validator = SEMANTIC_VALIDATORS.get(contract_name)
        if semantic_validator is not None:
            issues.extend(semantic_validator(document))

    return issues


def _resolve_contract_for_schema(schema_path: Path) -> ContractSpec | None:
    resolved_path = schema_path.resolve()
    for spec in CONTRACT_SPECS.values():
        if spec.schema_path.resolve() == resolved_path:
            return spec
    return None


def _infer_contract_from_path(path: Path) -> ContractSpec | None:
    file_name = path.name
    for spec in CONTRACT_SPECS.values():
        if file_name.endswith(f".{spec.example_suffix}.json"):
            return spec
    return None


def _collect_target_files(
    paths: list[str],
    *,
    example_dir: Path,
    contract_name: str,
    schema_path: Path | None,
) -> list[TargetFile]:
    explicit_paths = [Path(path).resolve() for path in paths]

    if schema_path is not None:
        resolved_schema_path = schema_path.resolve()
        contract_spec = _resolve_contract_for_schema(resolved_schema_path)
        if explicit_paths:
            return [
                TargetFile(
                    path=path,
                    contract_name=contract_spec.name if contract_spec else None,
                    schema_path=resolved_schema_path,
                )
                for path in explicit_paths
            ]

        if contract_spec is not None:
            files = sorted(example_dir.glob(f"*.{contract_spec.example_suffix}.json"))
        else:
            files = sorted(example_dir.glob("*.json"))

        return [
            TargetFile(
                path=path.resolve(),
                contract_name=contract_spec.name if contract_spec else None,
                schema_path=resolved_schema_path,
            )
            for path in files
        ]

    if explicit_paths:
        target_files: list[TargetFile] = []
        for path in explicit_paths:
            if contract_name == "all":
                contract_spec = _infer_contract_from_path(path)
                if contract_spec is None:
                    raise ValueError(
                        f"Could not infer built-in contract from file name: {path.name}. "
                        "Use --contract or --schema."
                    )
            else:
                contract_spec = CONTRACT_SPECS[contract_name]
            target_files.append(
                TargetFile(
                    path=path,
                    contract_name=contract_spec.name,
                    schema_path=contract_spec.schema_path,
                )
            )
        return target_files

    if contract_name == "all":
        target_files = [
            TargetFile(
                path=path.resolve(),
                contract_name=spec.name,
                schema_path=spec.schema_path,
            )
            for spec in CONTRACT_SPECS.values()
            for path in sorted(example_dir.glob(f"*.{spec.example_suffix}.json"))
        ]
        return sorted(target_files, key=lambda item: item.path.name)

    spec = CONTRACT_SPECS[contract_name]
    return [
        TargetFile(
            path=path.resolve(),
            contract_name=spec.name,
            schema_path=spec.schema_path,
        )
        for path in sorted(example_dir.glob(f"*.{spec.example_suffix}.json"))
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Validate registered AIInformationProcessor contracts or captured payloads."
    )
    parser.add_argument(
        "paths",
        nargs="*",
        help="Optional JSON files to validate. Without explicit paths, examples are loaded from contracts/examples/.",
    )
    parser.add_argument(
        "--contract",
        choices=["all", *CONTRACT_SPECS.keys()],
        default="all",
        help="Built-in contract to validate. Defaults to all registered contracts.",
    )
    parser.add_argument(
        "--schema",
        help="Optional custom schema path. When provided, built-in contract discovery is bypassed.",
    )
    parser.add_argument(
        "--example-dir",
        default=str(DEFAULT_EXAMPLE_DIR),
        help="Directory containing example JSON files used when no explicit paths are provided.",
    )
    args = parser.parse_args(argv)

    if args.schema and args.contract != "all":
        parser.error("--schema cannot be combined with --contract")

    example_dir = Path(args.example_dir).resolve()
    schema_path = Path(args.schema).resolve() if args.schema else None

    try:
        target_files = _collect_target_files(
            args.paths,
            example_dir=example_dir,
            contract_name=args.contract,
            schema_path=schema_path,
        )
    except ValueError as error:
        print(str(error), file=sys.stderr)
        return 1

    if not target_files:
        print("No JSON files found to validate.", file=sys.stderr)
        return 1

    schema_cache: dict[Path, dict[str, Any]] = {}
    had_errors = False

    for target_file in target_files:
        document = _load_json(target_file.path)
        if not isinstance(document, dict):
            print(f"[FAIL] {target_file.path}: root JSON value must be an object", file=sys.stderr)
            had_errors = True
            continue

        schema = schema_cache.get(target_file.schema_path)
        if schema is None:
            schema = _load_json(target_file.schema_path)
            schema_cache[target_file.schema_path] = schema

        issues = validate_document(document, schema, contract_name=target_file.contract_name)
        if issues:
            had_errors = True
            print(f"[FAIL] {target_file.path}")
            for issue in issues:
                print(f"  - {issue.path}: {issue.message}")
            continue

        contract_label = target_file.contract_name or target_file.schema_path.stem
        print(f"[OK]   {target_file.path} ({contract_label})")

    return 1 if had_errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
