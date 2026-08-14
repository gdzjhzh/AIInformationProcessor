import hashlib
import hmac
import secrets
import time
from dataclasses import dataclass
from typing import Any

from fastapi import HTTPException, Request, status
from fastapi.responses import Response

from .config import Settings

SESSION_COOKIE = "collector_session"
CSRF_HEADER = "X-Collector-CSRF"
SESSION_TTL_SECONDS = 7 * 24 * 60 * 60


@dataclass(frozen=True)
class BrowserSession:
    csrf: str
    expires_at: int


def internal_request_headers(settings: Settings, extra: dict[str, str] | None = None) -> dict[str, str]:
    """给 n8n webhook 等内部调用带上服务令牌，不暴露给浏览器。"""
    headers = {"Content-Type": "application/json"}
    if extra:
        headers.update(extra)
    if settings.internal_token:
        headers["Authorization"] = f"Bearer {settings.internal_token}"
        headers["X-Collector-Internal-Token"] = settings.internal_token
    return headers


def extract_internal_token(request: Request) -> str:
    """从 Authorization Bearer 或专用头取出内部调用令牌。"""
    authorization = request.headers.get("Authorization", "").strip()
    scheme, _, credential = authorization.partition(" ")
    if scheme.lower() == "bearer" and credential.strip():
        return credential.strip()
    return request.headers.get("X-Collector-Internal-Token", "").strip()


def secrets_match(provided: str, expected: str) -> bool:
    """比较密钥；长度不同时直接拒绝，避免 compare_digest 抛错变成 500。"""
    if not expected or not provided:
        return False
    if len(provided) != len(expected):
        return False
    return hmac.compare_digest(provided, expected)


def require_internal_token(request: Request, settings: Settings) -> None:
    """服务间接口鉴权：只认内部令牌，不认浏览器 Session。"""
    expected = settings.internal_token
    if not expected:
        return
    if not secrets_match(extract_internal_token(request), expected):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid internal token")


def session_secret(settings: Settings) -> str:
    """Session 签名密钥；未单独配置时从 UI 密码派生，避免再抄一份服务令牌。"""
    if settings.session_secret:
        return settings.session_secret
    if settings.ui_password:
        return hashlib.sha256(f"{settings.ui_password}:collector-web-session".encode("utf-8")).hexdigest()
    return ""


def _sign(secret: str, payload: str) -> str:
    return hmac.new(secret.encode("utf-8"), payload.encode("utf-8"), hashlib.sha256).hexdigest()


def encode_session(settings: Settings, *, csrf: str | None = None, now: int | None = None) -> str:
    """签发浏览器 Session，cookie 里只有过期时间和 CSRF，不含服务令牌。"""
    secret = session_secret(settings)
    if not secret:
        raise RuntimeError("browser session secret is not configured")
    expires_at = int(now if now is not None else time.time()) + SESSION_TTL_SECONDS
    csrf_token = csrf or secrets.token_hex(16)
    payload = f"{expires_at}.{csrf_token}"
    return f"{payload}.{_sign(secret, payload)}"


def decode_session(settings: Settings, raw: str) -> BrowserSession | None:
    """校验并解析浏览器 Session。"""
    secret = session_secret(settings)
    if not secret or not raw:
        return None
    parts = raw.split(".")
    if len(parts) != 3:
        return None
    expires_raw, csrf, signature = parts
    payload = f"{expires_raw}.{csrf}"
    expected = _sign(secret, payload)
    if not hmac.compare_digest(expected, signature):
        return None
    try:
        expires_at = int(expires_raw)
    except ValueError:
        return None
    if expires_at < int(time.time()):
        return None
    if not csrf:
        return None
    return BrowserSession(csrf=csrf, expires_at=expires_at)


def read_session(request: Request, settings: Settings) -> BrowserSession | None:
    """从 HttpOnly cookie 读取当前浏览器 Session。"""
    return decode_session(settings, request.cookies.get(SESSION_COOKIE, ""))


def attach_session_cookie(response: Response, settings: Settings, raw_session: str) -> None:
    """写入 HttpOnly Session cookie。"""
    response.set_cookie(
        SESSION_COOKIE,
        raw_session,
        httponly=True,
        samesite="lax",
        path="/",
        max_age=SESSION_TTL_SECONDS,
    )


def clear_session_cookie(response: Response) -> None:
    """登出时删除 Session cookie。"""
    response.delete_cookie(SESSION_COOKIE, path="/")


def passwords_match(provided: str, expected: str) -> bool:
    """比较 UI 密码，长度不同时直接拒绝。"""
    return secrets_match(provided, expected)


def require_browser_session(request: Request, settings: Settings) -> BrowserSession | None:
    """浏览器写接口鉴权：配置了 UI 密码时必须有 Session 和 CSRF。"""
    if not settings.ui_password:
        return read_session(request, settings)

    session = read_session(request, settings)
    if session is None:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="browser session required")

    csrf = request.headers.get(CSRF_HEADER, "").strip()
    if not csrf or not hmac.compare_digest(csrf, session.csrf):
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="invalid CSRF token")
    return session


def template_auth_context(request: Request, settings: Settings) -> dict[str, Any]:
    """给 Jinja 页面提供 CSRF 和登录态，绝不下发内部令牌。"""
    session = read_session(request, settings)
    return {
        "csrf_token": session.csrf if session else "",
        "browser_auth_required": bool(settings.ui_password),
        "browser_signed_in": session is not None,
    }
