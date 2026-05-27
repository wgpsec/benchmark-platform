"""Branding configuration — loads from branding.json (gitignored) with fallback defaults."""
from __future__ import annotations

import json
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = _PROJECT_ROOT / "branding.json"

_FALLBACK = {
    "brand_name": "浑象",
    "brand_edition": "开源版",
    "brand_subtitle": "AI 时代的安全能力评测基座",
}

_cache: dict[str, str] | None = None


def _load() -> dict[str, str]:
    if _CONFIG_PATH.exists():
        with open(_CONFIG_PATH, encoding="utf-8") as f:
            return json.load(f)
    return {}


def get_branding() -> dict[str, str]:
    global _cache
    if _cache is not None:
        return _cache

    cfg = _load()
    name = cfg.get("brand_name", _FALLBACK["brand_name"])
    edition = cfg.get("brand_edition", _FALLBACK["brand_edition"])
    subtitle = cfg.get("brand_subtitle", _FALLBACK["brand_subtitle"])

    _cache = {
        "brand_name": name,
        "brand_edition": edition,
        "brand_title": f"{name} - {edition}",
        "brand_subtitle": subtitle,
    }
    return _cache
