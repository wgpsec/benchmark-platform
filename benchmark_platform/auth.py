# benchmark_platform/auth.py
"""FastAPI dependency for Agent-Token authentication."""

from typing import Optional

from fastapi import Header, HTTPException

from benchmark_platform.db import get_or_create_default_team, get_team_by_token


async def get_current_team(agent_token: Optional[str] = Header(None, alias="Agent-Token")) -> dict:
    if agent_token is None:
        return get_or_create_default_team()
    team = get_team_by_token(agent_token)
    if team is None:
        raise HTTPException(
            status_code=401,
            detail={"code": -1, "message": "Invalid Agent-Token", "data": None},
        )
    return team
