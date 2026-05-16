"""Cookie-based authentication middleware for the Web UI."""

import os
import secrets
import logging
from typing import Optional

from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import RedirectResponse, Response

_MAX_AGE = 7 * 24 * 3600  # 7 days
_COOKIE_NAME = "bp_session"

_PUBLIC_PREFIXES = ("/api/", "/mcp", "/static/", "/vnc/")
_PUBLIC_PATHS = ("/web/login", "/web/login/")

_secret_key: Optional[str] = None


def get_secret_key() -> str:
    key = os.environ.get("SECRET_KEY")
    if not key:
        key = secrets.token_hex(32)
        logging.getLogger("benchmark_platform").warning(
            "SECRET_KEY not set — generated ephemeral key. Sessions will not survive restart."
        )
    return key


def _get_serializer() -> URLSafeTimedSerializer:
    global _secret_key
    if _secret_key is None:
        _secret_key = get_secret_key()
    return URLSafeTimedSerializer(_secret_key, salt="bp-session")


def create_session_cookie(team_id: str, role: str, team_name: str) -> str:
    s = _get_serializer()
    return s.dumps({"team_id": team_id, "role": role, "team_name": team_name})


def verify_session_cookie(cookie_value: str) -> Optional[dict]:
    s = _get_serializer()
    try:
        data = s.loads(cookie_value, max_age=_MAX_AGE)
        return data
    except (BadSignature, SignatureExpired):
        return None


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if any(path.startswith(p) for p in _PUBLIC_PREFIXES):
            return await call_next(request)
        if path in _PUBLIC_PATHS:
            return await call_next(request)
        if path == "/":
            return await call_next(request)

        cookie = request.cookies.get(_COOKIE_NAME)
        user = verify_session_cookie(cookie) if cookie else None

        if user is None:
            if request.headers.get("HX-Request"):
                return Response(status_code=401, headers={"HX-Redirect": "/web/login"})
            return RedirectResponse("/web/login", status_code=302)

        if user["role"] == "observer" and not path.startswith("/web/scoreboard"):
            return RedirectResponse("/web/scoreboard", status_code=302)

        request.state.user = user
        return await call_next(request)
