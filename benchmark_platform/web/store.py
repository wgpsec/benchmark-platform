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
STORE_META_FILE = ".store_meta"


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

    def has_update(self, category: str, name: str, remote_size: int) -> bool:
        meta_path = self.challenges_dir / category / name / STORE_META_FILE
        if not meta_path.exists():
            return False
        try:
            meta = json.loads(meta_path.read_text())
            return meta.get("size", 0) != remote_size and remote_size > 0
        except (json.JSONDecodeError, OSError):
            return False

    def download_challenge(self, category: str, name: str, asset: str, size: int = 0) -> Path:
        url = GITHUB_RELEASE_URL.format(repo=self.repo, tag=self.tag, asset=asset)
        dest = self.challenges_dir / category / name

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            urllib.request.urlretrieve(url, tmp_path)
            if dest.exists():
                shutil.rmtree(dest)
            self._extract_zip(tmp_path, dest)
            self._write_meta(dest, size)
        finally:
            tmp_path.unlink(missing_ok=True)

        return dest

    def delete_challenge(self, category: str, name: str) -> None:
        dest = self.challenges_dir / category / name
        if dest.exists():
            shutil.rmtree(dest)

    def _extract_zip(self, zip_path: Path, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest)

    def _write_meta(self, dest: Path, size: int) -> None:
        meta_path = dest / STORE_META_FILE
        meta_path.write_text(json.dumps({"size": size}))
