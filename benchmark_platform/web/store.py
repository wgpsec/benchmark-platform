# benchmark_platform/web/store.py
from __future__ import annotations

import json
import shutil
import zipfile
import tempfile
import urllib.request
from pathlib import Path


GITHUB_RELEASE_URL = "https://github.com/{repo}/releases/download/{tag}/{asset}"
MANIFEST_URL = "https://github.com/{repo}/releases/download/{tag}/manifest.json"


class ChallengeStore:
    def __init__(self, challenges_dir: Path, repo: str = "wgpsec/benchmark-challenges", tag: str = "latest"):
        self.challenges_dir = challenges_dir
        self.repo = repo
        self.tag = tag

    def fetch_manifest(self) -> dict:
        url = MANIFEST_URL.format(repo=self.repo, tag=self.tag)
        with urllib.request.urlopen(url, timeout=30) as resp:
            raw = resp.read().decode()
        return self._parse_manifest(raw)

    def _parse_manifest(self, raw: str) -> dict:
        return json.loads(raw)

    def is_downloaded(self, category: str, name: str) -> bool:
        target = self.challenges_dir / category / name / "docker-compose.yml"
        return target.exists()

    def download_challenge(self, category: str, name: str, asset: str) -> Path:
        url = GITHUB_RELEASE_URL.format(repo=self.repo, tag=self.tag, asset=asset)
        dest = self.challenges_dir / category / name

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            urllib.request.urlretrieve(url, tmp_path)
            self._extract_zip(tmp_path, dest)
        finally:
            tmp_path.unlink(missing_ok=True)

        return dest

    def _extract_zip(self, zip_path: Path, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest)
