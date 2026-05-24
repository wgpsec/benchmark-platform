# benchmark_platform/auth.py
"""FastAPI dependency for Agent-Token authentication."""

from typing import Optional

from fastapi import Header, HTTPException, Request

from benchmark_platform.db import get_or_create_default_team, get_team_by_token
from benchmark_platform.web.auth_middleware import verify_session_cookie, _COOKIE_NAME


def _team_from_cookie(request: Request) -> Optional[dict]:
    """Try to authenticate via session cookie (Web UI browser calls)."""
    cookie = request.cookies.get(_COOKIE_NAME)
    if not cookie:
        return None
    session = verify_session_cookie(cookie)
    if not session:
        return None
    return get_team_by_token_or_id(session["team_id"])


def get_team_by_token_or_id(team_id: str) -> Optional[dict]:
    from benchmark_platform.db import _get_conn
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, name, token, created_at FROM teams WHERE id = ?", (team_id,)
    ).fetchone()
    return dict(row) if row else None


async def get_current_team(request: Request, agent_token: Optional[str] = Header(None, alias="Agent-Token")) -> dict:
    token = agent_token
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()

    if token:
        team = get_team_by_token(token)
        if team is None:
            raise HTTPException(
                status_code=401,
                detail={"code": -1, "message": "Invalid token", "data": None},
            )
        return team

    team = _team_from_cookie(request)
    if team:
        # Admin viewing as another team: use selected_team_id for operations
        default_team = get_or_create_default_team()
        if team["id"] == default_team["id"]:
            selected_id = request.cookies.get("selected_team_id")
            if selected_id and selected_id != default_team["id"]:
                selected_team = get_team_by_token_or_id(selected_id)
                if selected_team:
                    return selected_team
        return team

    raise HTTPException(
        status_code=401,
        detail={"code": -1, "message": "Missing Agent-Token header", "data": None},
    )


async def require_admin(request: Request, agent_token: Optional[str] = Header(None, alias="Agent-Token")) -> dict:
    token = agent_token
    if not token:
        auth = request.headers.get("authorization", "")
        if auth.lower().startswith("bearer "):
            token = auth[7:].strip()

    if token:
        team = get_team_by_token(token)
        if team is None:
            raise HTTPException(
                status_code=401,
                detail={"code": -1, "message": "Invalid token", "data": None},
            )
    else:
        team = _team_from_cookie(request)
        if team is None:
            raise HTTPException(
                status_code=401,
                detail={"code": -1, "message": "Missing authentication token", "data": None},
            )

    default_team = get_or_create_default_team()
    if team["id"] != default_team["id"]:
        raise HTTPException(
            status_code=403,
            detail={"code": -1, "message": "Admin privileges required", "data": None},
        )
    return team
