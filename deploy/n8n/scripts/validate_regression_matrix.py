#!/usr/bin/env python3
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import dataclass
from pathlib import Path
from types import ModuleType
from typing import Any, Callable


ROOT_DIR = Path(__file__).resolve().parents[3]
WORKFLOW_DIR = ROOT_DIR / "deploy" / "n8n" / "workflows"
CONTRACT_DIR = ROOT_DIR / "contracts"
SCRIPT_DIR = Path(__file__).resolve().parent


@dataclass(frozen=True)
class CheckFailure:
    location: str
    message: str


def load_module(module_path: Path, module_name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(module_name, module_path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load module: {module_path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    return module


VALIDATE_CONTRACT = load_module(CONTRACT_DIR / "validate_contract.py", "aip_validate_contract")
WORKFLOW_BOUNDARIES = load_module(
    SCRIPT_DIR / "validate_workflow_boundaries.py",
    "aip_validate_workflow_boundaries",
)


def load_json(path: Path) -> dict[str, Any]:
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        raise ValueError(f"{path} root JSON value must be an object")
    return document


def workflow_path(name: str) -> Path:
    return WORKFLOW_DIR / name


def load_workflow(name: str) -> dict[str, Any]:
    return load_json(workflow_path(name))


def find_node(workflow: dict[str, Any], node_name: str) -> dict[str, Any] | None:
    for node in workflow.get("nodes", []):
        if isinstance(node, dict) and node.get("name") == node_name:
            return node
    return None


def node_js_code(workflow: dict[str, Any], node_name: str) -> str:
    node = find_node(workflow, node_name)
    if node is None:
        raise KeyError(f"workflow does not include node {node_name!r}")
    parameters = node.get("parameters", {})
    js_code = parameters.get("jsCode")
    if not isinstance(js_code, str):
        raise KeyError(f"node {node_name!r} does not expose parameters.jsCode")
    return js_code


def connected_nodes(workflow: dict[str, Any], source_node: str) -> set[str]:
    return WORKFLOW_BOUNDARIES.collect_connected_nodes(workflow, source_node)


def require_edge(
    workflow_name: str,
    workflow: dict[str, Any],
    source_node: str,
    target_node: str,
    failures: list[CheckFailure],
) -> None:
    if target_node not in connected_nodes(workflow, source_node):
        failures.append(
            CheckFailure(
                location=f"{workflow_name}:{source_node}",
                message=f"must connect to {target_node!r}",
            )
        )


def forbid_edge(
    workflow_name: str,
    workflow: dict[str, Any],
    source_node: str,
    target_node: str,
    failures: list[CheckFailure],
) -> None:
    if target_node in connected_nodes(workflow, source_node):
        failures.append(
            CheckFailure(
                location=f"{workflow_name}:{source_node}",
                message=f"must not connect directly to {target_node!r}",
            )
        )


def require_code_contains(
    workflow_name: str,
    workflow: dict[str, Any],
    node_name: str,
    snippet: str,
    failures: list[CheckFailure],
) -> None:
    code = node_js_code(workflow, node_name)
    if snippet not in code:
        failures.append(
            CheckFailure(
                location=f"{workflow_name}:{node_name}",
                message=f"missing code snippet {snippet!r}",
            )
        )


def check_contract_validate_all_examples() -> list[CheckFailure]:
    failures: list[CheckFailure] = []
    schema_cache: dict[Path, dict[str, Any]] = {}
    target_files = VALIDATE_CONTRACT._collect_target_files(
        [],
        example_dir=(CONTRACT_DIR / "examples").resolve(),
        contract_name="all",
        schema_path=None,
    )

    if not target_files:
        return [CheckFailure("contracts/examples", "no example files found")]

    for target_file in target_files:
        document = VALIDATE_CONTRACT._load_json(target_file.path)
        schema = schema_cache.get(target_file.schema_path)
        if schema is None:
            schema = VALIDATE_CONTRACT._load_json(target_file.schema_path)
            schema_cache[target_file.schema_path] = schema
        issues = VALIDATE_CONTRACT.validate_document(
            document,
            schema,
            contract_name=target_file.contract_name,
        )
        for issue in issues:
            failures.append(
                CheckFailure(
                    location=f"{target_file.path.relative_to(ROOT_DIR)}:{issue.path}",
                    message=issue.message,
                )
            )
    return failures


def check_workflow_graph_mainline_guard() -> list[CheckFailure]:
    failures: list[CheckFailure] = []
    for workflow_name in sorted(path.name for path in WORKFLOW_DIR.glob("*.json")):
        workflow = load_workflow(workflow_name)
        if find_node(workflow, "04 Video Transcript Ingest") and find_node(workflow, "05 Common Vault Writer"):
            forbid_edge(
                workflow_name,
                workflow,
                "04 Video Transcript Ingest",
                "05 Common Vault Writer",
                failures,
            )
    return failures


def check_normalized_no_legacy_after_00() -> list[CheckFailure]:
    failures: list[CheckFailure] = []
    for path in sorted(WORKFLOW_DIR.glob("*.json")):
        workflow = load_json(path)
        issues = WORKFLOW_BOUNDARIES.validate_legacy_fields(path, workflow)
        for issue in issues:
            failures.append(CheckFailure(issue.location, issue.message))
    return failures


def check_llm_score_scale_invariant() -> list[CheckFailure]:
    failures: list[CheckFailure] = []
    schema = load_json(CONTRACT_DIR / "llm_score.schema.json")
    if schema.get("properties", {}).get("score_scale", {}).get("const") != 100:
        failures.append(
            CheckFailure(
                "contracts/llm_score.schema.json:$.properties.score_scale",
                "score_scale must stay fixed at 100",
            )
        )

    for example_path in sorted((CONTRACT_DIR / "examples").glob("*.llm_score.json")):
        document = VALIDATE_CONTRACT._load_json(example_path)
        issues = VALIDATE_CONTRACT.validate_document(document, schema, contract_name="llm_score")
        for issue in issues:
            failures.append(
                CheckFailure(
                    location=f"{example_path.relative_to(ROOT_DIR)}:{issue.path}",
                    message=issue.message,
                )
            )

    enrich_workflow = load_workflow("02_enrich_with_llm.json")
    require_code_contains(
        "02_enrich_with_llm.json",
        enrich_workflow,
        "Validate Normalized Text Object",
        "score_scale=100 before enrichment",
        failures,
    )
    require_code_contains(
        "02_enrich_with_llm.json",
        enrich_workflow,
        "Parse And Merge Enrichment",
        "const scoreScale = 100;",
        failures,
    )
    require_code_contains(
        "02_enrich_with_llm.json",
        enrich_workflow,
        "Parse And Merge Enrichment",
        "keepScore / scoreScale",
        failures,
    )
    require_code_contains(
        "02_enrich_with_llm.json",
        enrich_workflow,
        "Parse And Merge Enrichment",
        "Math.abs(normalizedScore - score) > 0.001",
        failures,
    )

    policy_workflow = load_workflow("04a_action_policy.json")
    require_code_contains(
        "04a_action_policy.json",
        policy_workflow,
        "Apply Action Policy",
        "scoreScale !== 100",
        failures,
    )
    require_code_contains(
        "04a_action_policy.json",
        policy_workflow,
        "Apply Action Policy",
        "keepScore / scoreScale",
        failures,
    )
    require_code_contains(
        "04a_action_policy.json",
        policy_workflow,
        "Apply Action Policy",
        "Math.abs(normalizedScore - score) > 0.001",
        failures,
    )
    return failures


def check_privacy_external_llm_guard() -> list[CheckFailure]:
    failures: list[CheckFailure] = []
    schema = load_json(CONTRACT_DIR / "normalized_text_object.schema.json")
    properties = schema.get("properties", {})
    if "privacy_level" not in properties:
        failures.append(
            CheckFailure(
                "contracts/normalized_text_object.schema.json",
                "privacy_level must be part of the canonical NormalizedTextObject schema",
            )
        )
    if "external_llm_allowed" not in properties:
        failures.append(
            CheckFailure(
                "contracts/normalized_text_object.schema.json",
                "external_llm_allowed must be part of the canonical NormalizedTextObject schema",
            )
        )

    private_example = CONTRACT_DIR / "examples" / "private.normalized.json"
    if not private_example.exists():
        failures.append(
            CheckFailure(
                "contracts/examples",
                "private.normalized.json must exist to exercise the privacy contract",
            )
        )
    else:
        document = VALIDATE_CONTRACT._load_json(private_example)
        issues = VALIDATE_CONTRACT.validate_document(
            document,
            schema,
            contract_name="normalized_text_object",
        )
        for issue in issues:
            failures.append(
                CheckFailure(
                    location=f"{private_example.relative_to(ROOT_DIR)}:{issue.path}",
                    message=issue.message,
                )
            )

    workflow = load_workflow("02_enrich_with_llm.json")
    require_edge(
        "02_enrich_with_llm.json",
        workflow,
        "Validate Normalized Text Object",
        "Guard Privacy Before External LLM",
        failures,
    )
    require_edge(
        "02_enrich_with_llm.json",
        workflow,
        "Guard Privacy Before External LLM",
        "Build LLM Request",
        failures,
    )
    require_code_contains(
        "02_enrich_with_llm.json",
        workflow,
        "Guard Privacy Before External LLM",
        "privacy_level",
        failures,
    )
    require_code_contains(
        "02_enrich_with_llm.json",
        workflow,
        "Guard Privacy Before External LLM",
        "external_llm_allowed",
        failures,
    )
    require_code_contains(
        "02_enrich_with_llm.json",
        workflow,
        "Guard Privacy Before External LLM",
        "private",
        failures,
    )
    require_code_contains(
        "02_enrich_with_llm.json",
        workflow,
        "Guard Privacy Before External LLM",
        "sensitive",
        failures,
    )
    require_code_contains(
        "02_enrich_with_llm.json",
        workflow,
        "Guard Privacy Before External LLM",
        "blocked external LLM",
        failures,
    )
    return failures


def check_qdrant_commit_after_vault_write_only() -> list[CheckFailure]:
    failures: list[CheckFailure] = []
    workflow = load_workflow("03b_qdrant_commit.json")
    require_code_contains(
        "03b_qdrant_commit.json",
        workflow,
        "Build Qdrant Commit Payload",
        "vaultWriteStatus === 'written'",
        failures,
    )
    require_code_contains(
        "03b_qdrant_commit.json",
        workflow,
        "Build Qdrant Commit Payload",
        "Boolean($json.should_upsert_qdrant)",
        failures,
    )
    require_edge(
        "03b_qdrant_commit.json",
        workflow,
        "Build Qdrant Commit Payload",
        "Should Commit Qdrant?",
        failures,
    )
    require_edge(
        "03b_qdrant_commit.json",
        workflow,
        "Should Commit Qdrant?",
        "Qdrant Upsert",
        failures,
    )
    require_edge(
        "03b_qdrant_commit.json",
        workflow,
        "Should Commit Qdrant?",
        "Finalize Skipped Commit",
        failures,
    )
    return failures


def check_rss_transcript_uses_shared_mainline() -> list[CheckFailure]:
    failures: list[CheckFailure] = []
    workflow_name = "01_rss_to_obsidian_raw.json"
    workflow = load_workflow(workflow_name)
    for source_node, target_node in (
        ("Route Transcript Candidates", "04 Video Transcript Ingest"),
        ("04 Video Transcript Ingest", "00 Common Normalize Text Object"),
        ("00 Common Normalize Text Object", "01a Rule Prefilter"),
        ("01a Rule Prefilter", "Should Continue To Qdrant?"),
        ("Should Continue To Qdrant?", "03 Qdrant Gate"),
        ("03 Qdrant Gate", "Should Continue To LLM?"),
        ("Should Continue To LLM?", "02 Enrich With LLM"),
        ("02 Enrich With LLM", "04a Action Policy"),
        ("04a Action Policy", "05 Common Vault Writer"),
        ("05 Common Vault Writer", "03b Qdrant Commit"),
    ):
        require_edge(workflow_name, workflow, source_node, target_node, failures)
    forbid_edge(workflow_name, workflow, "04 Video Transcript Ingest", "05 Common Vault Writer", failures)
    return failures


def check_manual_media_uses_shared_mainline() -> list[CheckFailure]:
    failures: list[CheckFailure] = []
    workflow_name = "06_manual_media_submit.json"
    workflow = load_workflow(workflow_name)
    for source_node, target_node in (
        ("Normalize Manual Media Request", "04 Video Transcript Ingest"),
        ("04 Video Transcript Ingest", "Normalize Manual Submit Result"),
        ("Normalize Manual Submit Result", "Should Continue To Shared Mainline?"),
        ("Should Continue To Shared Mainline?", "00 Common Normalize Text Object"),
        ("00 Common Normalize Text Object", "01a Rule Prefilter"),
        ("01a Rule Prefilter", "Should Continue To Qdrant?"),
        ("Should Continue To Qdrant?", "03 Qdrant Gate"),
        ("03 Qdrant Gate", "Should Continue To LLM?"),
        ("Should Continue To LLM?", "02 Enrich With LLM"),
        ("02 Enrich With LLM", "04a Action Policy"),
        ("04a Action Policy", "Attach Manual Workflow Label"),
        ("Attach Manual Workflow Label", "05 Common Vault Writer"),
        ("05 Common Vault Writer", "03b Qdrant Commit"),
    ):
        require_edge(workflow_name, workflow, source_node, target_node, failures)
    forbid_edge(workflow_name, workflow, "04 Video Transcript Ingest", "05 Common Vault Writer", failures)
    return failures


def check_local_verify_no_vault_write() -> list[CheckFailure]:
    failures: list[CheckFailure] = []
    workflow_name = "90_local_verify_transcript_mainline.json"
    workflow = load_workflow(workflow_name)
    if find_node(workflow, "05 Common Vault Writer") is not None:
        failures.append(
            CheckFailure(
                location=workflow_name,
                message="local verify workflow must not include 05 Common Vault Writer",
            )
        )

    for source_node, target_node in (
        ("Normalize Verify Request", "04 Video Transcript Ingest"),
        ("04 Video Transcript Ingest", "Normalize Verify Result"),
        ("Normalize Verify Result", "Should Continue To Shared Mainline?"),
        ("Should Continue To Shared Mainline?", "00 Common Normalize Text Object"),
        ("00 Common Normalize Text Object", "01a Rule Prefilter"),
        ("01a Rule Prefilter", "Should Continue To Qdrant?"),
        ("Should Continue To Qdrant?", "03 Qdrant Gate"),
        ("03 Qdrant Gate", "Should Continue To LLM?"),
        ("Should Continue To LLM?", "02 Enrich With LLM"),
        ("02 Enrich With LLM", "04a Action Policy"),
        ("04a Action Policy", "Return Verify Result"),
    ):
        require_edge(workflow_name, workflow, source_node, target_node, failures)
    return failures


CHECKS: dict[str, Callable[[], list[CheckFailure]]] = {
    "contract_validate_all_examples": check_contract_validate_all_examples,
    "workflow_graph_mainline_guard": check_workflow_graph_mainline_guard,
    "normalized_no_legacy_after_00": check_normalized_no_legacy_after_00,
    "llm_score_scale_invariant": check_llm_score_scale_invariant,
    "privacy_external_llm_guard": check_privacy_external_llm_guard,
    "qdrant_commit_after_vault_write_only": check_qdrant_commit_after_vault_write_only,
    "rss_transcript_uses_shared_mainline": check_rss_transcript_uses_shared_mainline,
    "manual_media_uses_shared_mainline": check_manual_media_uses_shared_mainline,
    "local_verify_no_vault_write": check_local_verify_no_vault_write,
}


def main() -> int:
    had_failures = False
    for check_name, check in CHECKS.items():
        failures = check()
        if failures:
            had_failures = True
            print(f"[FAIL] {check_name}")
            for failure in failures:
                print(f"  - {failure.location}: {failure.message}")
            continue
        print(f"[OK]   {check_name}")
    return 1 if had_failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
