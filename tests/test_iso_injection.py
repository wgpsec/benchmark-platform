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


def test_inject_iso_mount_into_compose(tmp_path):
    """ISO bind mount should be appended to dockur service volumes."""
    compose_data = {
        "services": {
            "dc": {
                "image": "dockurr/windows",
                "volumes": ["dc-data:/storage"],
            },
            "web": {
                "build": {"context": "./src/web"},
                "ports": ["80:80"],
            },
        }
    }
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(yaml.dump(compose_data))

    iso_path = tmp_path / "win2022.iso"
    iso_path.write_bytes(b"fake iso content")

    ChallengeManager._inject_windows_iso(compose_path, str(iso_path))

    result = yaml.safe_load(compose_path.read_text())
    dc_volumes = result["services"]["dc"]["volumes"]
    assert f"{iso_path}:/storage/custom.iso:ro" in dc_volumes
    assert len(result["services"]["web"].get("volumes", [])) == 0


def test_inject_iso_skips_non_dockur(tmp_path):
    """Non-dockur services should not get ISO mount."""
    compose_data = {
        "services": {
            "web": {
                "image": "nginx:latest",
                "volumes": ["/data:/usr/share/nginx/html"],
            },
        }
    }
    compose_path = tmp_path / "docker-compose.yml"
    compose_path.write_text(yaml.dump(compose_data))

    iso_path = tmp_path / "win2022.iso"
    iso_path.write_bytes(b"fake iso content")

    ChallengeManager._inject_windows_iso(compose_path, str(iso_path))

    result = yaml.safe_load(compose_path.read_text())
    assert result["services"]["web"]["volumes"] == ["/data:/usr/share/nginx/html"]
