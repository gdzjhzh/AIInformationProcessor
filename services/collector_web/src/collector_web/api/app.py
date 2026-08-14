import json
from typing import Any
from urllib.parse import parse_qs, urlparse

from fastapi import FastAPI, HTTPException, Query, Request, status
from fastapi.responses import HTMLResponse, RedirectResponse
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
from ..auth import (
    attach_session_cookie,
    clear_session_cookie,
    encode_session,
    passwords_match,
    require_browser_session,
    require_internal_token,
    template_auth_context,
)
from ..config import get_settings
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


def _safe_next_path(value: str) -> str:
    """只允许站内相对跳转，避免登录后被带到外站。"""
    candidate = (value or "").strip() or "/"
    parsed = urlparse(candidate)
    if parsed.scheme or parsed.netloc or not candidate.startswith("/"):
        return "/"
    return candidate


def _form_value(form: dict[str, list[str]], name: str, default: str = "") -> str:
    """读取 application/x-www-form-urlencoded 字段的第一个值。"""
    values = form.get(name) or []
    if not values:
        return default
    return values[0]


async def _read_urlencoded_form(request: Request) -> dict[str, list[str]]:
    """解析登录表单，不引入 python-multipart。"""
    raw = (await request.body()).decode("utf-8", errors="replace")
    return parse_qs(raw, keep_blank_values=True)


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

    def page_context(request: Request, extra: dict[str, Any] | None = None) -> dict[str, Any]:
        """组装页面模板变量；只注入 CSRF/登录态，不下发内部令牌。"""
        context = {"request": request, **template_auth_context(request, settings)}
        if extra:
            context.update(extra)
        return context

    @app.on_event("startup")
    async def startup_event() -> None:
        init_database(settings)

    @app.get("/health")
    async def health() -> dict[str, object]:
        return {
            "ok": True,
            "db_exists": settings.db_path.exists(),
            "qdrant_collection": settings.qdrant_collection,
            "feishu_notify_mode": settings.feishu_notify_mode,
            "feishu_app_configured": bool(
                settings.feishu_app_id
                and settings.feishu_app_secret
                and settings.feishu_target_chat_id
            ),
            "internal_auth_configured": bool(settings.internal_token),
            "browser_auth_configured": bool(settings.ui_password),
        }

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request, next: str = "/") -> HTMLResponse:
        return templates.TemplateResponse(
            "login.html",
            page_context(request, {"next_path": _safe_next_path(next), "login_error": ""}),
        )

    @app.post("/login")
    async def login_submit(request: Request) -> Any:
        form = await _read_urlencoded_form(request)
        password = _form_value(form, "password")
        next_path = _safe_next_path(_form_value(form, "next", "/"))
        if not settings.ui_password or not passwords_match(password, settings.ui_password):
            return templates.TemplateResponse(
                "login.html",
                page_context(
                    request,
                    {"next_path": next_path, "login_error": "密码不正确"},
                ),
                status_code=401,
            )
        response = RedirectResponse(url=next_path, status_code=status.HTTP_303_SEE_OTHER)
        attach_session_cookie(response, settings, encode_session(settings))
        return response

    @app.post("/logout")
    async def logout_submit() -> RedirectResponse:
        response = RedirectResponse(url="/login", status_code=status.HTTP_303_SEE_OTHER)
        clear_session_cookie(response)
        return response

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
    async def rss_poll_rerun_api(request: Request) -> dict[str, Any]:
        require_browser_session(request, settings)
        try:
            return trigger_rss_poll_rerun(settings)
        except RssPollRerunError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/mainline-llm/switch", status_code=status.HTTP_202_ACCEPTED)
    async def mainline_llm_switch_api(
        request: Request,
        payload: MainlineLlmSwitchRequest,
    ) -> dict[str, Any]:
        require_browser_session(request, settings)
        try:
            return switch_mainline_llm_model(settings, payload.model)
        except MainlineLlmSwitchError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @app.post("/api/internal/feishu/notify", status_code=status.HTTP_202_ACCEPTED)
    async def feishu_notify_api(
        request: Request,
        payload: FeishuNotifyRequest,
    ) -> dict[str, Any]:
        require_internal_token(request, settings)
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
        request: Request,
        payload: CalibrationCompareRequest,
    ) -> dict[str, Any]:
        require_browser_session(request, settings)
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
    async def calibration_compare_open_directory_api(
        request: Request,
        job_id: str,
    ) -> dict[str, Any]:
        require_browser_session(request, settings)
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
        request: Request,
        payload: ManualMediaSubmitRequest,
    ) -> dict[str, Any]:
        require_browser_session(request, settings)
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
        request: Request,
        payload: ManualMediaPrecheckRequest,
    ) -> dict[str, Any]:
        require_browser_session(request, settings)
        return precheck_manual_media_submission(settings, payload.url)

    @app.post(
        "/api/manual-media-submit/{submission_id}/cancel",
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def cancel_manual_media_submit_api(
        request: Request,
        submission_id: int,
    ) -> dict[str, Any]:
        require_browser_session(request, settings)
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
    async def delete_vector_and_rerun_api(
        request: Request,
        submission_id: int,
    ) -> dict[str, Any]:
        require_browser_session(request, settings)
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
        require_internal_token(request, settings)
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
        return templates.TemplateResponse("home.html", page_context(request, build_page_context()))

    @app.get("/manual-media-submit", response_class=HTMLResponse)
    async def manual_media_submit_page(
        request: Request,
        submission_id: int | None = Query(default=None, ge=1),
    ) -> HTMLResponse:
        return templates.TemplateResponse(
            "manual_submit.html",
            page_context(request, build_page_context(submission_id=submission_id)),
        )

    @app.get("/calibration-compare", response_class=HTMLResponse)
    async def calibration_compare_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            "calibration_compare.html",
            page_context(request),
        )

    @app.get("/rss-poll", response_class=HTMLResponse)
    async def rss_poll_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            "rss_poll.html",
            page_context(request, {"audit": get_latest_rss_poll_audit(settings)}),
        )

    @app.get("/status", response_class=HTMLResponse)
    async def status_page(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            "status.html",
            page_context(request, get_service_status(settings)),
        )

    return app
