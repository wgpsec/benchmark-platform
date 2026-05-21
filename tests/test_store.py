# tests/test_store.py
import json
import zipfile
import tempfile
from pathlib import Path
from unittest.mock import patch, MagicMock
from benchmark_platform.web.store import ChallengeStore


def test_get_remote_challenges_parses_manifest_and_marks_download_state(tmp_path):
    raw = json.dumps({
        "version": "2026-05-11",
        "challenges": [
            {"name": "XBEN-001-24", "category": "xbow", "asset": "xbow--XBEN-001-24.zip", "description": "SSH Injection", "difficulty": "easy", "size": 123}
        ]
    })
    store = ChallengeStore(challenges_dir=tmp_path, repo="wgpsec/benchmark-challenges", tag="latest")
    with patch.object(store, "_fetch_url", return_value=raw):
        manifest = store.get_remote_challenges()
    assert len(manifest) == 1
    assert manifest[0]["name"] == "XBEN-001-24"
    assert manifest[0]["downloaded"] is False
    assert manifest[0]["has_update"] is False
    assert manifest[0]["source"] == "remote"


def test_is_downloaded(tmp_path):
    store = ChallengeStore(challenges_dir=tmp_path, repo="wgpsec/benchmark-challenges", tag="latest")
    assert store.is_downloaded("xbow", "XBEN-001-24") is False
    (tmp_path / "xbow" / "XBEN-001-24").mkdir(parents=True)
    (tmp_path / "xbow" / "XBEN-001-24" / "docker-compose.yml").touch()
    assert store.is_downloaded("xbow", "XBEN-001-24") is True


def test_extract_zip(tmp_path):
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        zf.writestr("docker-compose.yml", "version: '3'")
        zf.writestr("app/main.py", "print('hello')")

    store = ChallengeStore(challenges_dir=tmp_path, repo="wgpsec/benchmark-challenges", tag="latest")
    dest = tmp_path / "xbow" / "XBEN-001-24"
    store._extract_zip(zip_path, dest)

    assert (dest / "docker-compose.yml").exists()
    assert (dest / "app" / "main.py").exists()
