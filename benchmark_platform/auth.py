# benchmark_platform/auth.py
"""FastAPI dependency for Agent-Token authentication."""

from typing import Optional

from fastapi import Header, HTTPException

from benchmark_platform.db import get_or_create_default_team, get_team_by_token


async def get_current_team(agent_token: Optional[str] = Header(None, alias="Agent-Token")) -> dict:
    if agent_token is None:
        raise HTTPException(
            status_code=401,
            detail={"code": -1, "message": "Missing Agent-Token header", "data": None},
        )
    team = get_team_by_token(agent_token)
    if team is None:
        raise HTTPException(
            status_code=401,
            detail={"code": -1, "message": "Invalid Agent-Token", "data": None},
        )
    return team


async def require_admin(agent_token: Optional[str] = Header(None, alias="Agent-Token")) -> dict:
    if agent_token is None:
        raise HTTPException(
            status_code=401,
            detail={"code": -1, "message": "Missing Agent-Token header", "data": None},
        )
    team = get_team_by_token(agent_token)
    if team is None:
        raise HTTPException(
            status_code=401,
            detail={"code": -1, "message": "Invalid Agent-Token", "data": None},
        )
    default_team = get_or_create_default_team()
    if team["id"] != default_team["id"]:
        raise HTTPException(
            status_code=403,
            detail={"code": -1, "message": "Admin privileges required", "data": None},
        )
    return team
