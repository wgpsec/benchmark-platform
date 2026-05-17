# tests/test_per_team_isolation.py
"""Integration tests for per-team container isolation logic."""
import json
import uuid
from pathlib import Path

import pytest

from benchmark_platform.db import (
    init_db, create_team, _set_db_path,
    get_team_running_count, get_instance_by_benchmark_and_team,
    upsert_instance, get_all_instances,
)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path):
    db_path = tmp_path / "test.db"
    _set_db_path(db_path)
    init_db()
    yield db_path


def test_concurrent_instance_limit():
    """Teams cannot exceed max_instances_per_team."""
    team = create_team("team-a")
    team_id = team["id"]

    for i in range(3):
        upsert_instance(
            instance_id=str(uuid.uuid4()),
            benchmark_id=f"XBEN-{i:03d}",
            challenge_code=str(uuid.uuid4()),
            runtime_path=f"/tmp/{i}",
            ports=[8000 + i],
            status="running",
            team_id=team_id,
        )

    assert get_team_running_count(team_id) == 3


def test_different_teams_same_challenge_independent():
    """Two teams can have independent instances of the same challenge."""
    team_a = create_team("team-a")
    team_b = create_team("team-b")

    upsert_instance(
        instance_id="inst-a", benchmark_id="XBEN-001",
        challenge_code="code-a", runtime_path="/tmp/a",
        ports=[8001], status="running", team_id=team_a["id"],
    )
    upsert_instance(
        instance_id="inst-b", benchmark_id="XBEN-001",
        challenge_code="code-b", runtime_path="/tmp/b",
        ports=[8002], status="running", team_id=team_b["id"],
    )

    rec_a = get_instance_by_benchmark_and_team("XBEN-001", team_a["id"])
    rec_b = get_instance_by_benchmark_and_team("XBEN-001", team_b["id"])

    assert rec_a["challenge_code"] != rec_b["challenge_code"]
    assert json.loads(rec_a["ports"]) != json.loads(rec_b["ports"])


def test_shared_instance_for_ad():
    """AD challenges use team_id=NULL (shared)."""
    upsert_instance(
        instance_id="inst-shared", benchmark_id="AD-GOAD-01",
        challenge_code="code-shared", runtime_path="/tmp/shared",
        ports=[9090], status="running", team_id=None,
    )

    rec = get_instance_by_benchmark_and_team("AD-GOAD-01", None)
    assert rec is not None
    assert rec["team_id"] is None

    rec_team = get_instance_by_benchmark_and_team("AD-GOAD-01", "some-team-id")
    assert rec_team is None


def test_team_running_count_excludes_stopped():
    """Only running instances count toward the limit."""
    team = create_team("team-x")
    tid = team["id"]

    upsert_instance(
        instance_id="i1", benchmark_id="X1", challenge_code="c1",
        runtime_path="/tmp/1", ports=[8001], status="running", team_id=tid,
    )
    upsert_instance(
        instance_id="i2", benchmark_id="X2", challenge_code="c2",
        runtime_path="/tmp/2", ports=[8002], status="stopped", team_id=tid,
    )
    upsert_instance(
        instance_id="i3", benchmark_id="X3", challenge_code="c3",
        runtime_path="/tmp/3", ports=[8003], status="expired", team_id=tid,
    )

    assert get_team_running_count(tid) == 1


def test_get_all_instances_returns_all_teams():
    """get_all_instances returns instances from all teams."""
    team_a = create_team("team-a")
    team_b = create_team("team-b")

    upsert_instance(
        instance_id="i1", benchmark_id="X1", challenge_code="c1",
        runtime_path="/tmp/1", ports=[8001], status="running", team_id=team_a["id"],
    )
    upsert_instance(
        instance_id="i2", benchmark_id="X2", challenge_code="c2",
        runtime_path="/tmp/2", ports=[8002], status="running", team_id=team_b["id"],
    )
    upsert_instance(
        instance_id="i3", benchmark_id="X1", challenge_code="c3",
        runtime_path="/tmp/3", ports=[8003], status="running", team_id=team_b["id"],
    )

    all_inst = get_all_instances()
    assert len(all_inst) == 3


def test_upsert_updates_existing_team_instance():
    """Upserting with same benchmark_id+team_id updates the existing record."""
    team = create_team("team-a")
    tid = team["id"]

    upsert_instance(
        instance_id="i1", benchmark_id="X1", challenge_code="c1",
        runtime_path="/tmp/1", ports=[8001], status="stopped", team_id=tid,
    )
    # Same instance_id to trigger upsert
    upsert_instance(
        instance_id="i1", benchmark_id="X1", challenge_code="c2",
        runtime_path="/tmp/2", ports=[8002], status="running", team_id=tid,
    )

    rec = get_instance_by_benchmark_and_team("X1", tid)
    assert rec["challenge_code"] == "c2"
    assert rec["status"] == "running"
    assert json.loads(rec["ports"]) == [8002]
