"""Deployment UI visibility profile helper."""

import os


def get_ui_visibility() -> dict[str, object]:
    ui_profile = os.getenv("BENCHMARK_PLATFORM_UI_PROFILE", "open_source")
    if ui_profile == "hide_branding":
        return {
            "ui_profile": "hide_branding",
            "show_public_links": False,
            "show_import_actions": False,
            "show_authoring_docs": False,
        }

    return {
        "ui_profile": "open_source",
        "show_public_links": True,
        "show_import_actions": True,
        "show_authoring_docs": True,
    }
