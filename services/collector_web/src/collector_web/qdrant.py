import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

from .config import Settings


class QdrantOperationError(RuntimeError):
    pass


def _request_json(
    url: str,
    *,
    payload: dict[str, Any] | None,
    timeout_seconds: int,
) -> dict[str, Any]:
    request = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8") if payload is not None else None,
        headers={"Content-Type": "application/json"},
        method="POST" if payload is not None else "GET",
    )

    try:
        with urllib.request.urlopen(request, timeout=timeout_seconds) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise QdrantOperationError(
            f"Qdrant returned HTTP {exc.code}: {body}"
        ) from exc
    except Exception as exc:  # pragma: no cover - network/runtime failures
        raise QdrantOperationError(f"Qdrant request failed: {exc}") from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise QdrantOperationError(f"Qdrant returned non-JSON body: {body}") from exc

    if not isinstance(parsed, dict):
        raise QdrantOperationError("Qdrant returned JSON, but it was not an object")

    return parsed


def _item_id_filter(item_id: str) -> dict[str, Any]:
    return {
        "must": [
            {
                "key": "item_id",
                "match": {"value": item_id},
            }
        ]
    }


def _is_offset_zero_error(exc: Exception) -> bool:
    """识别当前 Qdrant 1.17.1 对 payload filter 的 OffsetZero panic。"""
    return "OffsetZero" in str(exc)


def _scroll_point_ids_by_item_id(
    settings: Settings,
    collection: str,
    item_id: str,
) -> list[str]:
    """在 filter 不可用时，无过滤 scroll 后在客户端按 item_id 筛选。"""
    base_url = settings.qdrant_base_url.rstrip("/")
    matched_ids: list[str] = []
    offset: Any = None
    while True:
        payload: dict[str, Any] = {
            "limit": 256,
            "with_payload": True,
            "with_vector": False,
        }
        if offset is not None:
            payload["offset"] = offset
        response = _request_json(
            f"{base_url}/collections/{collection}/points/scroll",
            payload=payload,
            timeout_seconds=settings.qdrant_timeout_seconds,
        )
        result = response.get("result") if isinstance(response.get("result"), dict) else {}
        for point in result.get("points") or []:
            if not isinstance(point, dict):
                continue
            point_payload = point.get("payload") if isinstance(point.get("payload"), dict) else {}
            if str(point_payload.get("item_id") or "").strip() != item_id:
                continue
            point_id = point.get("id")
            if point_id is not None:
                matched_ids.append(str(point_id))
        offset = result.get("next_page_offset")
        if not offset:
            break
    return matched_ids


def delete_points_by_item_id(settings: Settings, item_id: str) -> dict[str, Any]:
    normalized_item_id = item_id.strip()
    if not normalized_item_id:
        raise QdrantOperationError("item_id is required for Qdrant deletion")

    base_url = settings.qdrant_base_url.rstrip("/")
    collection = urllib.parse.quote(settings.qdrant_collection, safe="")
    filter_payload = {"filter": _item_id_filter(normalized_item_id)}
    used_scroll_fallback = False

    try:
        count_before_response = _request_json(
            f"{base_url}/collections/{collection}/points/count",
            payload=filter_payload,
            timeout_seconds=settings.qdrant_timeout_seconds,
        )
        count_before = int(
            count_before_response.get("result", {}).get("count", 0) or 0
        )
        delete_selector: dict[str, Any] = filter_payload
    except QdrantOperationError as exc:
        if not _is_offset_zero_error(exc):
            raise
        used_scroll_fallback = True
        point_ids = _scroll_point_ids_by_item_id(settings, collection, normalized_item_id)
        count_before = len(point_ids)
        delete_selector = {"points": point_ids}

    delete_response = None
    if count_before > 0:
        delete_response = _request_json(
            f"{base_url}/collections/{collection}/points/delete?wait=true",
            payload=delete_selector,
            timeout_seconds=settings.qdrant_timeout_seconds,
        )

    if used_scroll_fallback:
        count_after = len(
            _scroll_point_ids_by_item_id(settings, collection, normalized_item_id)
        )
    else:
        count_after_response = _request_json(
            f"{base_url}/collections/{collection}/points/count",
            payload=filter_payload,
            timeout_seconds=settings.qdrant_timeout_seconds,
        )
        count_after = int(count_after_response.get("result", {}).get("count", 0) or 0)

    return {
        "item_id": normalized_item_id,
        "qdrant_base_url": settings.qdrant_base_url,
        "qdrant_collection": settings.qdrant_collection,
        "count_before": count_before,
        "count_after": count_after,
        "deleted_count": max(count_before - count_after, 0),
        "delete_response": delete_response,
        "used_scroll_fallback": used_scroll_fallback,
    }


def get_collection_snapshot(settings: Settings) -> dict[str, Any]:
    base_url = settings.qdrant_base_url.rstrip("/")
    collection = urllib.parse.quote(settings.qdrant_collection, safe="")

    collection_response = _request_json(
        f"{base_url}/collections/{collection}",
        payload=None,
        timeout_seconds=settings.qdrant_timeout_seconds,
    )
    count_response = _request_json(
        f"{base_url}/collections/{collection}/points/count",
        payload={},
        timeout_seconds=settings.qdrant_timeout_seconds,
    )

    result = collection_response.get("result", {})
    if not isinstance(result, dict):
        result = {}

    config = result.get("config", {})
    if not isinstance(config, dict):
        config = {}

    params = config.get("params", {})
    if not isinstance(params, dict):
        params = {}

    vectors = params.get("vectors", {})
    vector_size = None
    distance = ""
    if isinstance(vectors, dict):
        vector_size = vectors.get("size")
        distance = str(vectors.get("distance", "")).strip()

    search_ok = False
    search_error = ""
    if isinstance(vector_size, int) and vector_size > 0:
        probe = [0.0] * vector_size
        probe[0] = 1.0
        try:
            _request_json(
                f"{base_url}/collections/{collection}/points/search",
                payload={"vector": probe, "limit": 1, "with_payload": False},
                timeout_seconds=settings.qdrant_timeout_seconds,
            )
            search_ok = True
        except QdrantOperationError as exc:
            search_error = str(exc)

    return {
        "qdrant_base_url": settings.qdrant_base_url,
        "qdrant_collection": settings.qdrant_collection,
        "status": str(result.get("status", "")).strip() or "unknown",
        "optimizer_status": str(result.get("optimizer_status", "")).strip() or "unknown",
        "points_count": int(count_response.get("result", {}).get("count", 0) or 0),
        "vector_size": vector_size,
        "distance": distance,
        "search_ok": search_ok,
        "search_error": search_error,
    }
