import hmac
import json
from typing import Any

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, Field

from ..calibration_compare import (
    CalibrationCompareError,
    get_calibration_compare_job,
    open_calibration_compare_directory,
    publicize_calibration_compare_payload,
    submit_calibration_compare,
)
from ..config import Settings, get_settings
from ..db import init_database
from ..feishu_app import FeishuAppError, FeishuCallbackAuthError, handle_card_action, send_compact_notification
from ..manual_submit import (
    ManualMediaSubmitError,
    cancel_manual_submission,
    delete_vector_and_rerun_submission,
    enqueue_manual_submission,
)
from ..mainline_llm import MainlineLlmSwitchError, switch_mainline_llm_model
from ..precheck import precheck_manual_media_submission
from ..repository import (
    complete_manual_submission,
    get_dashboard_data,
    get_manual_submission,
    list_recent_manual_submissions,
)
from ..rss_audit import get_latest_rss_poll_audit
from ..rss_poll import RssPollRerunError, trigger_rss_poll_rerun
from ..status import get_service_status


class ManualMediaSubmitRequest(BaseModel):
    url: str = Field(min_length=1)
    max_polls: int | None = Field(default=None, ge=1)
    poll_interval_ms: int | None = Field(default=None, ge=1000)
    use_speaker_recognition: bool | None = None


class ManualMediaPrecheckRequest(BaseModel):
    url: str = Field(min_length=1)


class ManualMediaSubmitCallbackRequest(BaseModel):
    submission_id: int = Field(ge=1)
    result: dict[str, Any]


class CalibrationCompareRequest(BaseModel):
    url: str = Field(min_length=1)
    enable_thinking: bool = False


class MainlineLlmSwitchRequest(BaseModel):
    model: str | None = None


class FeishuNotifyRequest(BaseModel):
    payload: dict[str, Any] = Field(default_factory=dict)


def _extract_internal_token(request: Request) -> str:
    """从 Authorization Bearer 或专用头取出内部调用令牌。"""
    authorization = request.headers.get("Authorization", "").strip()
    scheme, _, credential = authorization.partition(" ")
    if scheme.lower() == "bearer" and credential.strip():
        return credential.strip()
    return request.headers.get("X-Collector-Internal-Token", "").strip()


def _require_internal_token(request: Request, settings: Settings) -> None:
    """内部接口鉴权：配置了令牌时必须匹配，未配置则保持本机兼容。"""
    expected = settings.internal_token
    if not expected:
        return
    provided = _extract_internal_token(request)
    if not provided or not hmac.compare_digest(provided, expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal token")


def _build_submit_payload(payload: ManualMediaSubmitRequest) -> dict[str, Any]:
    submit_payload = {"url": payload.url.strip()}
    if payload.max_polls is not None:
        submit_payload["max_polls"] = payload.max_polls
    if payload.poll_interval_ms is not None:
        submit_payload["poll_interval_ms"] = payload.poll_interval_ms
    if payload.use_speaker_recognition is not None:
        submit_payload["use_speaker_recognition"] = payload.use_speaker_recognition
    return submit_payload


def create_app() -> FastAPI:
    settings = get_settings()
    templates = Jinja2Templates(directory=str(settings.templates_dir))

    app = FastAPI(
        title="Collector Web",
        description="Subscription dashboard for Signal to Obsidian",
        version="0.1.0",
    )

    if settings.static_dir.exists():
        app.mount("/static", StaticFiles(directory=str(settings.static_dir)), name="static")

    @app.on_event("startup")
    async def startup_event() -> None:
        init_database(settings)

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "ok": True,
            "db_path": str(settings.db_path),
            "db_exists": settings.db_path.exists(),
            "manual_media_submit_url": settings.manual_media_submit_url,
            "qdrant_base_url": settings.qdrant_base_url,
            "qdrant_collection": settings.qdrant_collection,
            "feishu_notify_mode": settings.feishu_notify_mode,
            "feishu_app_configured": bool(
                settings.feishu_app_id
                and settings.feishu_app_secret
                and settings.feishu_target_chat_id
            ),
        }

    @app.get("/api/collections")
    async def collections_api() -> dict[str, object]:
        return get_dashboard_data(settings)

    @app.get("/api/status")
    async def status_api() -> dict[str, object]:
        return get_service_status(settings)

    @app.get("/api/rss-poll/latest")
    async def rss_poll_latest_api() -> dict[str, Any]:
        return get_latest_rss_poll_audit(settings)

    @app.post("/api/rss-poll/rerun", status_code=status.HTTP_202_ACCEPTED)
    async def rss_poll_rerun_api() -> dict[str, Any]:
        try:
            return trigger_rss_poll_rerun(settings)
        except RssPollRerunError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/mainline-llm/switch", status_code=status.HTTP_202_ACCEPTED)
    async def mainline_llm_switch_api(payload: MainlineLlmSwitchRequest) -> dict[str, Any]:
        try:
            return switch_mainline_llm_model(settings, payload.model)
        except MainlineLlmSwitchError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/internal/feishu/notify", status_code=status.HTTP_202_ACCEPTED)
    async def feishu_notify_api(
        request: Request,
        payload: FeishuNotifyRequest,
    ) -> dict[str, Any]:
        _require_internal_token(request, settings)
        try:
            return send_compact_notification(settings, payload.payload)
        except FeishuAppError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/feishu/card-action")
    async def feishu_card_action_api(request: Request) -> dict[str, Any]:
        raw_body = await request.body()
        try:
            payload = json.loads(raw_body)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail="invalid JSON body") from exc
        if not isinstance(payload, dict):
            raise HTTPException(status_code=400, detail="invalid callback body")
        try:
            return handle_card_action(
                settings,
                payload,
                headers=request.headers,
                raw_body=raw_body,
            )
        except FeishuCallbackAuthError as exc:
            raise HTTPException(status_code=401, detail=str(exc)) from exc
        except FeishuAppError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/calibration-compare", status_code=status.HTTP_202_ACCEPTED)
    async def calibration_compare_api(
        payload: CalibrationCompareRequest,
    ) -> dict[str, Any]:
        try:
            result = submit_calibration_compare(
                settings,
                payload.url.strip(),
                enable_thinking=payload.enable_thinking,
            )
        except CalibrationCompareError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return publicize_calibration_compare_payload(settings, result)

    @app.get("/api/calibration-compare/{job_id}")
    async def calibration_compare_status_api(job_id: str) -> dict[str, Any]:
        try:
            result = get_calibration_compare_job(settings, job_id)
        except CalibrationCompareError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc
        return publicize_calibration_compare_payload(settings, result)

    @app.post("/api/calibration-compare/{job_id}/open-directory")
    async def calibration_compare_open_directory_api(job_id: str) -> dict[str, Any]:
        try:
            return open_calibration_compare_directory(settings, job_id)
        except CalibrationCompareError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    def build_page_context(submission_id: int | None = None) -> dict[str, Any]:
        dashboard = get_dashboard_data(settings)
        selected_submission = None
        if submission_id is not None:
            selected_submission = get_manual_submission(settings, submission_id)
        elif dashboard["manual_submissions"]:
            selected_submission = dashboard["manual_submissions"][0]

        return {
            "summary": dashboard["summary"],
            "collections": dashboard["collections"],
            "platform_groups": dashboard["platform_groups"],
            "manual_submission_summary": dashboard["manual_submission_summary"],
            "manual_submissions": dashboard["manual_submissions"],
            "selected_submission": selected_submission,
        }

    @app.get("/api/manual-media-submit/history")
    async def manual_media_submit_history_api(
        limit: int = Query(default=settings.manual_submission_history_limit, ge=1, le=100),
    ) -> dict[str, Any]:
        return {
            "ok": True,
            "items": list_recent_manual_submissions(settings, limit=limit),
        }

    @app.get("/api/manual-media-submit/{submission_id}")
    async def manual_media_submit_detail_api(submission_id: int) -> dict[str, Any]:
        submission = get_manual_submission(settings, submission_id)
        if submission is None:
            raise HTTPException(status_code=404, detail="manual submission not found")
        return {"ok": True, "submission": submission}

    @app.post("/api/manual-media-submit", status_code=status.HTTP_202_ACCEPTED)
    async def manual_media_submit_api(
        payload: ManualMediaSubmitRequest,
    ) -> dict[str, Any]:
        try:
            submission = enqueue_manual_submission(
                settings,
                _build_submit_payload(payload),
            )
        except ManualMediaSubmitError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

        return {
            "ok": True,
            "submission": submission,
        }

    @app.post("/api/manual-media-submit/precheck")
    async def manual_media_submit_precheck_api(
        payload: ManualMediaPrecheckRequest,
    ) -> dict[str, Any]:
        return precheck_manual_media_submission(settings, payload.url)

    @app.post(
        "/api/manual-media-submit/{submission_id}/cancel",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def cancel_manual_media_submit_api(submission_id: int) -> dict[str, Any]:
        try:
            submission, cancel_mode = cancel_manual_submission(
                settings,
                submission_id,
            )
        except ManualMediaSubmitError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "ok": True,
            "submission": submission,
            "cancel_mode": cancel_mode,
        }

    @app.post(
        "/api/manual-media-submit/{submission_id}/delete-vector-and-rerun",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def delete_vector_and_rerun_api(submission_id: int) -> dict[str, Any]:
        try:
            rerun_submission, delete_detail = delete_vector_and_rerun_submission(
                settings,
                submission_id,
            )
        except ManualMediaSubmitError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

        return {
            "ok": True,
            "submission": rerun_submission,
            "deleted_vector": delete_detail,
        }

    @app.post("/api/internal/manual-media-submit-callback")
    async def manual_media_submit_callback_api(
        request: Request,
        payload: ManualMediaSubmitCallbackRequest,
    ) -> dict[str, Any]:
        _require_internal_token(request, settings)
        submission = complete_manual_submission(
            settings,
            payload.submission_id,
            payload.result,
        )
        if submission is None:
            raise HTTPException(status_code=404, detail="manual submission not found")
        return {
            "ok": True,
            "submission": submission,
        }

    @app.get("/", response_class=HTMLResponse)
    async def home(request: Request) -> HTMLResponse:
        context = {
            "request": request,
            **build_page_context(),
        }
        return templates.TemplateResponse("home.html", context)

    @app.get("/manual-media-submit", response_class=HTMLResponse)
    async def manual_media_submit_page(
        request: Request,
        submission_id: int | None = Query(default=None, ge=1),
    ) -> HTMLResponse:
        context = {
            "request": request,
            **build_page_context(submission_id=submission_id),
        }
        return templates.TemplateResponse("manual_submit.html", context)

    @app.get("/calibration-compare", response_class=HTMLResponse)
    async def calibration_compare_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            "calibration_compare.html",
            {"request": request},
        )

    @app.get("/rss-poll", response_class=HTMLResponse)
    async def rss_poll_page(request: Request) -> HTMLResponse:
        audit = get_latest_rss_poll_audit(settings)
        return templates.TemplateResponse(
            "rss_poll.html",
            {
                "request": request,
                "audit": audit,
            },
        )

    @app.get("/status", response_class=HTMLResponse)
    async def status_page(request: Request) -> HTMLResponse:
        context = {
            "request": request,
            **get_service_status(settings),
        }
        return templates.TemplateResponse("status.html", context)

    return app
