"""Tests for deployment UI visibility profiles."""

from benchmark_platform.web.ui_visibility import get_ui_visibility


def test_default_profile_is_open_source_when_env_is_unset(monkeypatch):
    monkeypatch.delenv("BENCHMARK_PLATFORM_UI_PROFILE", raising=False)

    assert get_ui_visibility() == {
        "ui_profile": "open_source",
        "show_public_links": True,
        "show_import_actions": True,
        "show_authoring_docs": True,
    }


def test_hide_branding_profile_hides_deployment_specific_ui(monkeypatch):
    monkeypatch.setenv("BENCHMARK_PLATFORM_UI_PROFILE", "hide_branding")

    assert get_ui_visibility() == {
        "ui_profile": "hide_branding",
        "show_public_links": False,
        "show_import_actions": False,
        "show_authoring_docs": False,
    }


def test_unknown_profile_falls_back_to_open_source(monkeypatch):
    monkeypatch.setenv("BENCHMARK_PLATFORM_UI_PROFILE", "enterprise")

    assert get_ui_visibility() == {
        "ui_profile": "open_source",
        "show_public_links": True,
        "show_import_actions": True,
        "show_authoring_docs": True,
    }
