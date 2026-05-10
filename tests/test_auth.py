# tests/test_auth.py
import pytest
from unittest.mock import patch
from fastapi import HTTPException
from benchmark_platform.auth import get_current_team
from benchmark_platform.db import init_db, create_team, _set_db_path


@pytest.fixture(autouse=True)
def tmp_db(tmp_path):
    db_path = tmp_path / "test.db"
    _set_db_path(db_path)
    init_db()
    yield


@pytest.mark.asyncio
async def test_no_token_returns_default_team():
    team = await get_current_team(agent_token=None)
    assert team["name"] == "default"


@pytest.mark.asyncio
async def test_valid_token_returns_team():
    created = create_team("TestTeam")
    team = await get_current_team(agent_token=created["token"])
    assert team["name"] == "TestTeam"
    assert team["id"] == created["id"]


@pytest.mark.asyncio
async def test_invalid_token_raises_401():
    with pytest.raises(HTTPException) as exc_info:
        await get_current_team(agent_token="bad_token_value")
    assert exc_info.value.status_code == 401
