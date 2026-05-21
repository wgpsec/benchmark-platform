"""Tests that web page routes return 200."""
import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from benchmark_platform.db import _get_conn, _set_db_path, create_team, init_db, upsert_instance
from benchmark_platform.server import app
from benchmark_platform.web.auth_middleware import _COOKIE_NAME, create_session_cookie
from benchmark_platform.web.submission_store import SubmissionStore


@pytest.fixture(autouse=True)
def clear_ui_profile(monkeypatch, tmp_path):
    monkeypatch.delenv("BENCHMARK_PLATFORM_UI_PROFILE", raising=False)
    _set_db_path(tmp_path / "benchmark.db")
    init_db()


def _init_app_state():
    """Set minimal app.state so routes don't crash."""
    app.state.manager = None
    app.state.submission_store = SubmissionStore()


def _admin_client() -> TestClient:
    client = TestClient(app)
    client.cookies.set(
        _COOKIE_NAME,
        create_session_cookie("default", "admin", "Default Team"),
    )
    return client


def test_dashboard_returns_200():
    _init_app_state()
    client = _admin_client()
    r = client.get("/web/dashboard")
    assert r.status_code == 200
    assert "仪表盘" in r.text


def test_about_page_returns_200_for_admin():
    _init_app_state()
    client = _admin_client()
    r = client.get("/web/about")
    assert r.status_code == 200
    assert "关于我们" in r.text
    assert "Benchmark Platform" in r.text


def test_about_page_shows_repository_links_and_ecosystem_content():
    _init_app_state()
    client = _admin_client()
    r = client.get("/web/about")
    assert r.status_code == 200
    assert "https://github.com/wgpsec/benchmark-platform" in r.text
    assert "https://github.com/wgpsec/benchmark-challenges" in r.text
    assert "AboutSecurity" in r.text
    assert "context1337" in r.text
    assert "tchkiller" in r.text
    assert "PoJun" in r.text


def test_about_page_shows_contact_section():
    _init_app_state()
    client = _admin_client()
    r = client.get("/web/about")
    assert r.status_code == 200
    assert "如需定制化部署、赛事支持或合作交流，可通过以下方式联系。" in r.text
    assert "mailto:" in r.text
    assert "/static/images/wgpsec-wechat-qrcode.png" in r.text


def test_challenges_returns_200():
    _init_app_state()
    client = _admin_client()
    r = client.get("/web/challenges")
    assert r.status_code == 200


def test_history_returns_200():
    _init_app_state()
    client = _admin_client()
    r = client.get("/web/history")
    assert r.status_code == 200


def test_status_returns_200():
    _init_app_state()
    client = _admin_client()
    r = client.get("/web/status")
    assert r.status_code == 200


def test_root_redirects_to_dashboard():
    _init_app_state()
    client = TestClient(app, follow_redirects=False)
    r = client.get("/")
    assert r.status_code == 307
    assert "/web/dashboard" in r.headers["location"]


def test_store_page_shows_open_source_controls_by_default():
    _init_app_state()
    client = _admin_client()
    r = client.get("/web/store")
    assert r.status_code == 200
    assert "https://github.com/wgpsec/benchmark-challenges" in r.text
    assert re.search(r">\s*导入\s*<", r.text)
    assert "docs/challenge-spec.md" in r.text


def test_store_page_hides_branding_controls(monkeypatch):
    monkeypatch.setenv("BENCHMARK_PLATFORM_UI_PROFILE", "hide_branding")
    _init_app_state()
    client = _admin_client()
    r = client.get("/web/store")
    assert r.status_code == 200
    assert "https://github.com/wgpsec/benchmark-challenges" not in r.text
    assert not re.search(r">\s*导入\s*<", r.text)
    assert "docs/challenge-spec.md" not in r.text


def test_dashboard_hides_sidebar_branding_in_hide_branding_profile(monkeypatch):
    monkeypatch.setenv("BENCHMARK_PLATFORM_UI_PROFILE", "hide_branding")
    _init_app_state()
    client = _admin_client()
    r = client.get("/web/dashboard")
    assert r.status_code == 200
    assert "https://github.com/wgpsec/benchmark-platform" not in r.text
    assert "powered by wgpsec" not in r.text


def _seed_analytics_data():
    team_fast = create_team("fast-team")
    team_slow = create_team("slow-team")
    started_fast = datetime(2026, 5, 21, 10, 0, 0, tzinfo=timezone.utc)
    started_slow = started_fast + timedelta(minutes=5)
    solved_fast = started_fast + timedelta(minutes=10)
    solved_slow = started_slow + timedelta(minutes=20)
    upsert_instance(
        instance_id="inst-fast",
        benchmark_id="XBEN-001-24",
        challenge_code="xbow/XBEN-001-24",
        runtime_path="/tmp/fast",
        ports=[],
        status="running",
        team_id=team_fast["id"],
        started_at=started_fast.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    upsert_instance(
        instance_id="inst-slow",
        benchmark_id="XBEN-001-24",
        challenge_code="xbow/XBEN-001-24-2",
        runtime_path="/tmp/slow",
        ports=[],
        status="running",
        team_id=team_slow["id"],
        started_at=started_slow.strftime("%Y-%m-%dT%H:%M:%SZ"),
    )
    conn = _get_conn()
    conn.execute(
        "INSERT INTO team_progress (team_id, benchmark_id, flag_id, solved, solved_at) VALUES (?, ?, ?, 1, ?)",
        (team_fast["id"], "XBEN-001-24", "flag1", solved_fast.strftime("%Y-%m-%dT%H:%M:%SZ")),
    )
    conn.execute(
        "INSERT INTO team_progress (team_id, benchmark_id, flag_id, solved, solved_at) VALUES (?, ?, ?, 1, ?)",
        (team_slow["id"], "XBEN-001-24", "flag1", solved_slow.strftime("%Y-%m-%dT%H:%M:%SZ")),
    )
    conn.commit()


def test_analytics_page_shows_average_solve_time_stats():
    _init_app_state()
    _seed_analytics_data()
    client = _admin_client()
    r = client.get("/web/analytics")
    assert r.status_code == 200
    assert "XBEN-001-24" in r.text
    assert "15m 0s" in r.text
    assert "fast-team" in r.text


def test_dashboard_sidebar_shows_analytics_entry_for_admin():
    _init_app_state()
    client = _admin_client()
    r = client.get("/web/dashboard")
    assert r.status_code == 200
    assert "赛事统计" in r.text
    assert '/web/analytics' in r.text


def test_dashboard_sidebar_shows_about_entry_for_admin():
    _init_app_state()
    client = _admin_client()
    r = client.get("/web/dashboard")
    assert r.status_code == 200
    assert "关于我们" in r.text
    assert "/web/about" in r.text
