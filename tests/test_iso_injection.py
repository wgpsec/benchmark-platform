"""Tests for Windows ISO detection and injection."""
import tempfile
from pathlib import Path

import yaml

from benchmark_platform.utils.challenge import ChallengeManager


def _write_compose(path: Path, services: dict) -> None:
    """Write a docker-compose.yml with given services dict."""
    (path / "docker-compose.yml").write_text(yaml.dump({"services": services}))


def test_detect_requires_windows_iso():
    """Challenge with dockurr/windows image should set requires_windows_iso=True."""
    compose_data = {
        "services": {
            "dc": {"image": "dockurr/windows", "environment": ["VERSION=2022"]},
            "web": {"build": {"context": "./src/web"}, "ports": ["80:80"]},
        }
    }
    result = ChallengeManager._detect_requires_windows_iso(compose_data)
    assert result is True


def test_detect_no_windows_iso():
    """Challenge without dockur image should not require ISO."""
    compose_data = {
        "services": {
            "web": {"build": {"context": "./src/web"}, "ports": ["80:80"]},
            "db": {"image": "mysql:8.0"},
        }
    }
    result = ChallengeManager._detect_requires_windows_iso(compose_data)
    assert result is False


def test_detect_case_insensitive():
    """Detection should be case-insensitive for dockur substring."""
    compose_data = {
        "services": {
            "vm": {"image": "Dockur/Windows"},
        }
    }
    result = ChallengeManager._detect_requires_windows_iso(compose_data)
    assert result is True
