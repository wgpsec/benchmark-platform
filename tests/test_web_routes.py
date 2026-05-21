"""Tests that web page routes return 200."""
import re

import pytest
from fastapi.testclient import TestClient

from benchmark_platform.db import _set_db_path, init_db
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
