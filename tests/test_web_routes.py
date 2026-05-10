"""Tests that web page routes return 200."""
from fastapi.testclient import TestClient

from benchmark_platform.server import app
from benchmark_platform.web.submission_store import SubmissionStore


def _init_app_state():
    """Set minimal app.state so routes don't crash."""
    app.state.manager = None
    app.state.submission_store = SubmissionStore()


def test_dashboard_returns_200():
    _init_app_state()
    client = TestClient(app)
    r = client.get("/web/dashboard")
    assert r.status_code == 200
    assert "仪表盘" in r.text


def test_challenges_returns_200():
    _init_app_state()
    client = TestClient(app)
    r = client.get("/web/challenges")
    assert r.status_code == 200


def test_history_returns_200():
    _init_app_state()
    client = TestClient(app)
    r = client.get("/web/history")
    assert r.status_code == 200


def test_status_returns_200():
    _init_app_state()
    client = TestClient(app)
    r = client.get("/web/status")
    assert r.status_code == 200


def test_root_redirects_to_dashboard():
    _init_app_state()
    client = TestClient(app, follow_redirects=False)
    r = client.get("/")
    assert r.status_code == 307
    assert "/web/dashboard" in r.headers["location"]
