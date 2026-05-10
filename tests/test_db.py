# tests/test_db.py
import pytest
from pathlib import Path
from benchmark_platform.db import (
    init_db, create_team, list_teams, get_team_by_token,
    get_or_create_default_team, mark_flag_solved,
    get_team_solved_count, is_hint_viewed, mark_hint_viewed,
    get_team_progress, reset_team_progress, _set_db_path,
)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path):
    """Use a temporary DB for each test."""
    db_path = tmp_path / "test.db"
    _set_db_path(db_path)
    init_db()
    yield db_path


def test_create_team():
    team = create_team("AlphaTeam")
    assert team["name"] == "AlphaTeam"
    assert len(team["token"]) == 32
    assert "id" in team


def test_create_team_duplicate_name():
    create_team("AlphaTeam")
    with pytest.raises(ValueError, match="already exists"):
        create_team("AlphaTeam")


def test_list_teams_empty():
    teams = list_teams()
    assert teams == []


def test_list_teams_with_data():
    create_team("Team1")
    create_team("Team2")
    teams = list_teams()
    assert len(teams) == 2


def test_get_team_by_token():
    team = create_team("AlphaTeam")
    found = get_team_by_token(team["token"])
    assert found is not None
    assert found["name"] == "AlphaTeam"


def test_get_team_by_token_invalid():
    assert get_team_by_token("nonexistent") is None


def test_get_or_create_default_team():
    t1 = get_or_create_default_team()
    t2 = get_or_create_default_team()
    assert t1["id"] == t2["id"]
    assert t1["name"] == "default"


def test_mark_flag_solved():
    team = create_team("Team1")
    mark_flag_solved(team["id"], "XBEN-001-24", "flag1")
    assert get_team_solved_count(team["id"], "XBEN-001-24") == 1


def test_mark_flag_solved_idempotent():
    team = create_team("Team1")
    mark_flag_solved(team["id"], "XBEN-001-24", "flag1")
    mark_flag_solved(team["id"], "XBEN-001-24", "flag1")
    assert get_team_solved_count(team["id"], "XBEN-001-24") == 1


def test_hint_viewed():
    team = create_team("Team1")
    assert is_hint_viewed(team["id"], "XBEN-001-24") is False
    mark_hint_viewed(team["id"], "XBEN-001-24")
    assert is_hint_viewed(team["id"], "XBEN-001-24") is True


def test_get_team_progress():
    team = create_team("Team1")
    mark_flag_solved(team["id"], "XBEN-001-24", "flag1")
    mark_flag_solved(team["id"], "XBEN-001-24", "flag2")
    mark_flag_solved(team["id"], "XBEN-002-24", "default")
    progress = get_team_progress(team["id"])
    assert progress["XBEN-001-24"]["flag1"] is True
    assert progress["XBEN-001-24"]["flag2"] is True
    assert progress["XBEN-002-24"]["default"] is True


def test_reset_team_progress():
    team = create_team("Team1")
    mark_flag_solved(team["id"], "XBEN-001-24", "flag1")
    mark_hint_viewed(team["id"], "XBEN-001-24")
    assert get_team_solved_count(team["id"], "XBEN-001-24") == 1
    assert is_hint_viewed(team["id"], "XBEN-001-24") is True
    reset_team_progress(team["id"])
    assert get_team_solved_count(team["id"], "XBEN-001-24") == 0
    assert is_hint_viewed(team["id"], "XBEN-001-24") is False
