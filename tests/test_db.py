# tests/test_db.py
import pytest
from pathlib import Path
from benchmark_platform.db import (
    init_db, create_team, list_teams, get_team_by_token,
    get_or_create_default_team, mark_flag_solved,
    get_team_solved_count, is_hint_viewed, mark_hint_viewed,
    get_team_progress, reset_team_progress, _set_db_path,
    upsert_instance, get_instance_by_benchmark_id, get_running_instances,
    get_expired_instances, delete_instance,
    get_instance_timeout_config, set_instance_timeout_config,
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


def test_upsert_instance_insert():
    upsert_instance(
        instance_id="id-1",
        benchmark_id="XBEN-001-24",
        challenge_code="uuid-1",
        runtime_path="runtime/XBEN-001-24/uuid-1",
        ports=[8081, 8082],
        status="stopped",
    )
    row = get_instance_by_benchmark_id("XBEN-001-24")
    assert row is not None
    assert row["challenge_code"] == "uuid-1"
    assert row["status"] == "stopped"
    assert row["ports"] == "[8081, 8082]"


def test_upsert_instance_update():
    upsert_instance(
        instance_id="id-1",
        benchmark_id="XBEN-001-24",
        challenge_code="uuid-1",
        runtime_path="runtime/XBEN-001-24/uuid-1",
        ports=[8081],
        status="stopped",
    )
    upsert_instance(
        instance_id="id-1",
        benchmark_id="XBEN-001-24",
        challenge_code="uuid-2",
        runtime_path="runtime/XBEN-001-24/uuid-2",
        ports=[9091],
        status="running",
        started_at="2026-05-14T00:00:00Z",
        expires_at="2026-05-14T01:00:00Z",
    )
    row = get_instance_by_benchmark_id("XBEN-001-24")
    assert row["challenge_code"] == "uuid-2"
    assert row["status"] == "running"
    assert row["ports"] == "[9091]"


def test_get_running_instances():
    upsert_instance("id-1", "XBEN-001-24", "c1", "p1", [80], "running",
                    started_at="2026-05-14T00:00:00Z", expires_at="2026-05-14T01:00:00Z")
    upsert_instance("id-2", "XBEN-002-24", "c2", "p2", [81], "stopped")
    rows = get_running_instances()
    assert len(rows) == 1
    assert rows[0]["benchmark_id"] == "XBEN-001-24"


def test_get_expired_instances():
    upsert_instance("id-1", "XBEN-001-24", "c1", "p1", [80], "running",
                    started_at="2026-05-14T00:00:00Z", expires_at="2020-01-01T00:00:00Z")
    upsert_instance("id-2", "XBEN-002-24", "c2", "p2", [81], "running",
                    started_at="2026-05-14T00:00:00Z", expires_at="2099-01-01T00:00:00Z")
    rows = get_expired_instances()
    assert len(rows) == 1
    assert rows[0]["benchmark_id"] == "XBEN-001-24"


def test_delete_instance():
    upsert_instance("id-1", "XBEN-001-24", "c1", "p1", [80], "stopped")
    delete_instance("XBEN-001-24")
    assert get_instance_by_benchmark_id("XBEN-001-24") is None


def test_get_instance_timeout_config_defaults():
    config = get_instance_timeout_config()
    assert config == {1: 3600, 2: 7200, 3: 14400}


def test_set_instance_timeout_config():
    set_instance_timeout_config({1: 1800, 2: 3600, 3: 7200})
    config = get_instance_timeout_config()
    assert config == {1: 1800, 2: 3600, 3: 7200}
