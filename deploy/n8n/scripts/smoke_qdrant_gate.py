#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import sys
import urllib.error
import urllib.request
import uuid
from pathlib import Path

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


def request_json(
    method: str,
    url: str,
    payload: dict | None = None,
    extra_headers: dict[str, str] | None = None,
) -> dict:
    data = None
    headers = {"Content-Type": "application/json"}
    if extra_headers:
        headers.update(extra_headers)
    if payload is not None:
        data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, method=method, data=data, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"{method} {url} -> HTTP {exc.code}: {body}") from exc


def make_unit_vector(size: int, cosine: float) -> list[float]:
    if size < 2:
        raise ValueError("Vector size must be at least 2")
    if not -1 <= cosine <= 1:
        raise ValueError("Cosine must be between -1 and 1")
    other = math.sqrt(max(0.0, 1 - cosine**2))
    vector = [0.0] * size
    vector[0] = cosine
    vector[1] = other
    return vector


def qdrant_uuid(name: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, name))


def decide_action(
    item_id: str,
    content_hash: str,
    match: dict | None,
    diff_threshold: float,
    silent_threshold: float,
) -> dict[str, object]:
    dedupe_action = "full_push"
    notification_mode = "full"
    should_write_to_vault = True
    should_notify = True
    should_upsert_qdrant = True
    matched_payload = match.get("payload") if match else None
    matched_score = float(match.get("score", 0)) if match else 0.0

    same_item = bool(matched_payload and matched_payload.get("item_id") == item_id)
    same_content = bool(same_item and matched_payload.get("content_hash") == content_hash)

    if same_content:
        dedupe_action = "silent"
        notification_mode = "silent"
        should_write_to_vault = False
        should_notify = False
        should_upsert_qdrant = False
    elif same_item:
        dedupe_action = "diff_push"
        notification_mode = "incremental"
    elif match and matched_score >= silent_threshold:
        dedupe_action = "silent"
        notification_mode = "silent"
        should_write_to_vault = False
        should_notify = False
        should_upsert_qdrant = False
    elif match and matched_score >= diff_threshold:
        dedupe_action = "diff_push"
        notification_mode = "incremental"

    return {
        "dedupe_action": dedupe_action,
        "notification_mode": notification_mode,
        "should_write_to_vault": should_write_to_vault,
        "should_notify": should_notify,
        "should_upsert_qdrant": should_upsert_qdrant,
        "matched_score": matched_score,
        "matched_payload": matched_payload,
    }


def run_smoke(
    *,
    env_file: Path,
    qdrant_base_url: str,
) -> dict:
    env_file = env_file.resolve()
    env_values = load_dotenv(env_file)
    embedding_base_url = env_values.get("EMBEDDING_BASE_URL", "")
    embedding_api_key = env_values.get("EMBEDDING_API_KEY", "")
    embedding_model = env_values.get("EMBEDDING_MODEL", "")
    embedding_input_max_chars = int(env_values.get("EMBEDDING_INPUT_MAX_CHARS", "6000") or "6000")
    qdrant_collection = env_values.get("QDRANT_COLLECTION", "article_embeddings") or "article_embeddings"
    qdrant_vector_size = int(env_values.get("QDRANT_VECTOR_SIZE", "0") or "0")
    diff_threshold = float(env_values.get("QDRANT_DIFF_THRESHOLD", "0.85") or "0.85")
    silent_threshold = float(env_values.get("QDRANT_SILENT_THRESHOLD", "0.97") or "0.97")

    embedding_probe_skipped = not (embedding_base_url and embedding_api_key and embedding_model)
    embedding_vector_length: int | None = None
    if not (embedding_base_url and embedding_api_key and embedding_model):
        embedding_probe_skipped = True
    else:
        probe = request_json(
            "POST",
            f"{embedding_base_url.rstrip('/')}/embeddings",
            {
                "model": embedding_model,
                "input": "AIInformationProcessor qdrant gate smoke test",
            },
            {
                "Authorization": f"Bearer {embedding_api_key}",
            },
        )
        embedding = probe.get("data", [{}])[0].get("embedding")
        if not isinstance(embedding, list):
            raise RuntimeError("Embedding probe failed: response did not include data[0].embedding")
        embedding_vector_length = len(embedding)
        if qdrant_vector_size and len(embedding) != qdrant_vector_size:
            raise RuntimeError(
                "Embedding probe failed: vector length does not match "
                f"QDRANT_VECTOR_SIZE ({len(embedding)} != {qdrant_vector_size})"
            )

    collection_url = f"{qdrant_base_url.rstrip('/')}/collections/{qdrant_collection}"
    collection = request_json("GET", collection_url)
    actual_size = int(collection["result"]["config"]["params"]["vectors"]["size"])
    if actual_size != qdrant_vector_size:
        raise RuntimeError(
            f"Collection size mismatch: env QDRANT_VECTOR_SIZE={qdrant_vector_size}, actual={actual_size}"
        )

    smoke_collection = f"{qdrant_collection}__smoke"
    smoke_url = f"{qdrant_base_url.rstrip('/')}/collections/{smoke_collection}"
    try:
        request_json("DELETE", smoke_url)
    except RuntimeError:
        pass
    request_json(
        "PUT",
        smoke_url,
        {
            "vectors": {
                "size": qdrant_vector_size,
                "distance": "Cosine",
            }
        },
    )

    base_vector = make_unit_vector(qdrant_vector_size, 1.0)
    request_json(
        "PUT",
        f"{smoke_url}/points",
        {
            "points": [
                {
                    "id": qdrant_uuid("smoke-base"),
                    "vector": base_vector,
                    "payload": {
                        "item_id": "smoke-base-item",
                        "content_hash": "sha256:base",
                        "title": "Smoke base item",
                        "canonical_url": "https://example.com/base",
                    },
                }
            ]
        },
    )

    scenarios = [
        {
            "name": "full_push_new_event",
            "item_id": "smoke-new-item",
            "content_hash": "sha256:new",
            "vector": make_unit_vector(qdrant_vector_size, 0.5),
            "expected": "full_push",
        },
        {
            "name": "diff_push_similar_event",
            "item_id": "smoke-similar-item",
            "content_hash": "sha256:similar",
            "vector": make_unit_vector(qdrant_vector_size, 0.9),
            "expected": "diff_push",
        },
        {
            "name": "silent_exact_duplicate",
            "item_id": "smoke-base-item",
            "content_hash": "sha256:base",
            "vector": make_unit_vector(qdrant_vector_size, 1.0),
            "expected": "silent",
        },
        {
            "name": "diff_push_same_item_updated",
            "item_id": "smoke-base-item",
            "content_hash": "sha256:updated",
            "vector": make_unit_vector(qdrant_vector_size, 1.0),
            "expected": "diff_push",
        },
    ]

    failures: list[str] = []
    scenario_results: list[dict[str, object]] = []
    for scenario in scenarios:
        search = request_json(
            "POST",
            f"{smoke_url}/points/search",
            {
                "vector": scenario["vector"],
                "limit": 1,
                "with_payload": True,
            },
        )
        matches = search.get("result", [])
        match = matches[0] if matches else None
        outcome = decide_action(
            item_id=str(scenario["item_id"]),
            content_hash=str(scenario["content_hash"]),
            match=match,
            diff_threshold=diff_threshold,
            silent_threshold=silent_threshold,
        )
        actual = str(outcome["dedupe_action"])
        scenario_results.append(
            {
                "name": scenario["name"],
                "expected_action": scenario["expected"],
                "actual_action": actual,
                "matched_score": round(float(outcome["matched_score"]), 4),
                "should_write_to_vault": bool(outcome["should_write_to_vault"]),
                "should_upsert_qdrant": bool(outcome["should_upsert_qdrant"]),
            }
        )
        if actual != scenario["expected"]:
            failures.append(f"{scenario['name']}: expected {scenario['expected']}, got {actual}")

    request_json("DELETE", smoke_url)

    if failures:
        raise RuntimeError("Smoke test failures: " + "; ".join(failures))

    return {
        "env_file": env_file,
        "qdrant_base_url": qdrant_base_url,
        "embedding_base_url_set": bool(embedding_base_url),
        "embedding_api_key_set": bool(embedding_api_key),
        "embedding_model_set": bool(embedding_model),
        "embedding_probe_skipped": embedding_probe_skipped,
        "embedding_vector_length": embedding_vector_length,
        "embedding_input_max_chars": embedding_input_max_chars,
        "qdrant_collection": qdrant_collection,
        "qdrant_vector_size": qdrant_vector_size,
        "actual_vector_size": actual_size,
        "diff_threshold": diff_threshold,
        "silent_threshold": silent_threshold,
        "scenario_results": scenario_results,
    }


def print_smoke_result(result: dict) -> None:
    print("Embedding config:")
    print(f"  EMBEDDING_BASE_URL set: {result['embedding_base_url_set']}")
    print(f"  EMBEDDING_API_KEY set: {result['embedding_api_key_set']}")
    print(f"  EMBEDDING_MODEL set: {result['embedding_model_set']}")
    if result["embedding_probe_skipped"]:
        print("  live embedding probe skipped: one or more embedding env vars are blank")
    else:
        print(f"  live embedding vector length: {result['embedding_vector_length']}")

    print("Qdrant collection:")
    print(f"  name: {result['qdrant_collection']}")
    print(f"  configured vector size: {result['qdrant_vector_size']}")
    print(f"  actual vector size: {result['actual_vector_size']}")
    print(f"  diff threshold: {result['diff_threshold']}")
    print(f"  silent threshold: {result['silent_threshold']}")

    print("Synthetic gate scenarios:")
    for scenario in result["scenario_results"]:
        print(
            f"  {scenario['name']}: score={scenario['matched_score']:.4f} "
            f"action={scenario['actual_action']} write={scenario['should_write_to_vault']} "
            f"upsert={scenario['should_upsert_qdrant']}"
        )
    print("Smoke test passed.")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check embedding config, Qdrant collection status, and synthetic 03_qdrant_gate behavior."
    )
    parser.add_argument(
        "--env-file",
        type=Path,
        default=Path(__file__).resolve().parents[2] / ".env",
        help="Path to the deploy/.env file.",
    )
    parser.add_argument(
        "--qdrant-base-url",
        default="http://localhost:6333",
        help="Qdrant base URL reachable from the host.",
    )
    parser.add_argument(
        "--debug-log",
        type=Path,
        default=default_debug_log_path(),
        help="Append a summary to this debug log file.",
    )
    parser.add_argument(
        "--no-debug-log",
        action="store_true",
        help="Do not append results to DEBUG_LOG.md. Useful for pre-commit and other no-side-effect checks.",
    )
    args = parser.parse_args()

    try:
        result = run_smoke(
            env_file=args.env_file,
            qdrant_base_url=args.qdrant_base_url,
        )
        print_smoke_result(result)
        if not args.no_debug_log:
            append_debug_log(
                script_name="smoke_qdrant_gate.py",
                stage="smoke_qdrant_gate",
                status="success",
                summary=f"Synthetic gate smoke passed with {len(result['scenario_results'])} scenario(s).",
                details=result,
                log_path=args.debug_log,
            )
        return 0
    except Exception as exc:
        if not args.no_debug_log:
            append_debug_log(
                script_name="smoke_qdrant_gate.py",
                stage="smoke_qdrant_gate",
                status="failure",
                summary=f"Smoke test failed: {exc}",
                details={
                    "env_file": args.env_file,
                    "qdrant_base_url": args.qdrant_base_url,
                    "error": str(exc),
                },
                log_path=args.debug_log,
            )
        print(exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
