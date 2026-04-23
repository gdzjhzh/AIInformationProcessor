import json
import threading
import urllib.error
import urllib.request
from typing import Any

from .config import Settings
from .qdrant import QdrantOperationError, delete_points_by_item_id
from .repository import (
    cancel_manual_submission as cancel_manual_submission_in_repository,
    complete_manual_submission,
    create_manual_submission,
    fail_manual_submission,
    get_manual_submission,
    mark_manual_submission_running,
    record_qdrant_delete_detail,
)


class ManualMediaSubmitError(RuntimeError):
    pass


def submit_manual_media(settings: Settings, payload: dict[str, Any]) -> dict[str, Any]:
    request = urllib.request.Request(
        settings.manual_media_submit_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(
            request,
            timeout=settings.manual_media_submit_timeout_seconds,
        ) as response:
            body = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise ManualMediaSubmitError(
            f"manual media submit webhook returned HTTP {exc.code}: {body}"
        ) from exc
    except Exception as exc:  # pragma: no cover - network/runtime failures
        raise ManualMediaSubmitError(
            f"manual media submit webhook request failed: {exc}"
        ) from exc

    try:
        parsed = json.loads(body)
    except json.JSONDecodeError as exc:
        raise ManualMediaSubmitError(
            f"manual media submit webhook returned non-JSON body: {body}"
        ) from exc

    if not isinstance(parsed, dict):
        raise ManualMediaSubmitError(
            "manual media submit webhook returned JSON, but it was not an object"
        )

    return parsed


def _run_manual_submission(settings: Settings, submission_id: int) -> None:
    submission = get_manual_submission(settings, submission_id)
    if submission is None:
        return

    if not mark_manual_submission_running(settings, submission_id):
        return
    try:
        result = submit_manual_media(settings, submission["request_payload"])
    except ManualMediaSubmitError as exc:
        fail_manual_submission(
            settings,
            submission_id,
            str(exc),
            stage="06_manual_media_submit",
        )
        return

    complete_manual_submission(settings, submission_id, result)


def enqueue_manual_submission(
    settings: Settings,
    payload: dict[str, Any],
    *,
    rerun_of_submission_id: int | None = None,
    qdrant_delete_detail: dict[str, Any] | None = None,
) -> dict[str, Any]:
    submission = create_manual_submission(
        settings,
        payload,
        rerun_of_submission_id=rerun_of_submission_id,
        qdrant_delete_detail=qdrant_delete_detail,
    )
    worker = threading.Thread(
        target=_run_manual_submission,
        args=(settings, submission["id"]),
        daemon=True,
        name=f"collector-web-submit-{submission['id']}",
    )
    worker.start()
    return submission


def cancel_manual_submission(
    settings: Settings,
    submission_id: int,
) -> tuple[dict[str, Any], str]:
    submission, cancel_mode = cancel_manual_submission_in_repository(settings, submission_id)
    if submission is None:
        raise ManualMediaSubmitError("manual submission not found")

    if cancel_mode == "not_cancellable":
        raise ManualMediaSubmitError("current submission can no longer be cancelled")

    return submission, cancel_mode


def delete_vector_and_rerun_submission(
    settings: Settings,
    submission_id: int,
) -> tuple[dict[str, Any], dict[str, Any]]:
    submission = get_manual_submission(settings, submission_id)
    if submission is None:
        raise ManualMediaSubmitError("manual submission not found")

    if not submission["item_id"]:
        raise ManualMediaSubmitError("current submission does not have an item_id")

    if submission["dedupe_action"] != "silent":
        raise ManualMediaSubmitError("current submission is not blocked by silent dedupe")

    try:
        delete_detail = delete_points_by_item_id(settings, submission["item_id"])
    except QdrantOperationError as exc:
        raise ManualMediaSubmitError(str(exc)) from exc

    record_qdrant_delete_detail(settings, submission_id, delete_detail)
    rerun_submission = enqueue_manual_submission(
        settings,
        submission["request_payload"],
        rerun_of_submission_id=submission_id,
        qdrant_delete_detail=delete_detail,
    )
    return rerun_submission, delete_detail
