# benchmark_platform/web/store.py
from __future__ import annotations

import json
import re
import shutil
import zipfile
import tempfile
import urllib.request
from pathlib import Path


GITHUB_RELEASE_URL = "https://github.com/{repo}/releases/download/{tag}/{asset}"
PROXY_RELEASE_URL = "https://gh-proxy.com/https://github.com/{repo}/releases/download/{tag}/{asset}"
MANIFEST_URL = "https://github.com/{repo}/releases/download/{tag}/manifest.json"
PROXY_MANIFEST_URL = "https://gh-proxy.com/https://github.com/{repo}/releases/download/{tag}/manifest.json"
STORE_META_FILE = ".store_meta"
_UUID_RE = re.compile(r'^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$')


class ChallengeStore:
    def __init__(self, challenges_dir: Path, repo: str = "wgpsec/benchmark-challenges", tag: str = "latest", quiz_dir: Path | None = None):
        self.challenges_dir = challenges_dir
        self.quiz_dir = quiz_dir
        self.repo = repo
        self.tag = tag

    def get_local_challenges(self) -> list[dict]:
        """Scan local challenges_dir, return all present challenges (skip runtime UUID instances)."""
        results = []
        if not self.challenges_dir.is_dir():
            return results
        for category_dir in sorted(self.challenges_dir.iterdir()):
            if not category_dir.is_dir() or category_dir.name.startswith('.'):
                continue
            # Skip runtime instance dirs (benchmark_id at top level with UUID subdirs)
            if _UUID_RE.match(category_dir.name):
                continue
            for challenge_dir in sorted(category_dir.iterdir()):
                if not challenge_dir.is_dir() or challenge_dir.name.startswith('.'):
                    continue
                if _UUID_RE.match(challenge_dir.name):
                    continue
                if not (challenge_dir / "docker-compose.yml").exists():
                    continue
                ch = {
                    "category": category_dir.name,
                    "name": challenge_dir.name,
                    "description": "",
                    "difficulty": "",
                    "flag_count": 1,
                    "size": 0,
                    "asset": "",
                    "downloaded": True,
                    "has_update": False,
                    "source": "local",
                    "tags": [],
                }
                benchmark_json = challenge_dir / "benchmark.json"
                if benchmark_json.exists():
                    try:
                        meta = json.loads(benchmark_json.read_text())
                        ch["description"] = meta.get("description", "")
                        ch["difficulty"] = meta.get("difficulty", "")
                        ch["flag_count"] = meta.get("flag_count", 1)
                        ch["tags"] = meta.get("tags", [])
                        level = meta.get("level", 0)
                        if not ch["difficulty"] and level:
                            ch["difficulty"] = {1: "easy", 2: "medium", 3: "hard"}.get(level, "")
                    except (json.JSONDecodeError, OSError):
                        pass
                meta_path = challenge_dir / STORE_META_FILE
                if meta_path.exists():
                    try:
                        store_meta = json.loads(meta_path.read_text())
                        ch["size"] = store_meta.get("size", 0)
                    except (json.JSONDecodeError, OSError):
                        pass
                results.append(ch)
        return results

    def get_local_quizzes(self) -> list[dict]:
        """Scan local quiz_dir, return all present quiz benchmarks."""
        results = []
        if not self.quiz_dir or not self.quiz_dir.is_dir():
            return results
        for quiz_subdir in sorted(self.quiz_dir.iterdir()):
            if not quiz_subdir.is_dir() or quiz_subdir.name.startswith('.'):
                continue
            benchmark_json = quiz_subdir / "benchmark.json"
            if not benchmark_json.exists():
                continue
            try:
                meta = json.loads(benchmark_json.read_text())
            except (json.JSONDecodeError, OSError):
                continue
            if meta.get("win_condition") != "mcq":
                continue
            ch = {
                "category": "quiz",
                "name": quiz_subdir.name,
                "description": meta.get("description", ""),
                "difficulty": meta.get("difficulty", ""),
                "flag_count": len(meta.get("questions", [])),
                "size": 0,
                "asset": "",
                "downloaded": True,
                "has_update": False,
                "source": "local",
                "tags": meta.get("tags", []),
                "win_condition": "mcq",
            }
            meta_path = quiz_subdir / STORE_META_FILE
            if meta_path.exists():
                try:
                    store_meta = json.loads(meta_path.read_text())
                    ch["size"] = store_meta.get("size", 0)
                except (json.JSONDecodeError, OSError):
                    pass
            results.append(ch)
        return results

    def get_remote_challenges(self) -> list[dict]:
        """Fetch remote manifest and annotate with local download status."""
        proxy_url = PROXY_MANIFEST_URL.format(repo=self.repo, tag=self.tag)
        direct_url = MANIFEST_URL.format(repo=self.repo, tag=self.tag)
        raw = self._fetch_url(proxy_url, direct_url)
        manifest = json.loads(raw)
        challenges = manifest.get("challenges", [])
        for ch in challenges:
            is_quiz = self._is_quiz(ch)
            ch["downloaded"] = self._is_quiz_downloaded(ch["name"]) if is_quiz else self.is_downloaded(ch["category"], ch["name"])
            ch["has_update"] = self._quiz_has_update(ch["name"], ch.get("size", 0)) if is_quiz else self.has_update(ch["category"], ch["name"], ch.get("size", 0))
            ch["source"] = "remote"
            if is_quiz:
                ch["win_condition"] = "mcq"
        return challenges

    def merge_challenges(self, local: list[dict], remote: list[dict]) -> list[dict]:
        """Merge remote into local, remote takes priority for overlapping entries."""
        remote_keys = {(ch["category"], ch["name"]) for ch in remote}
        local_only = [ch for ch in local if (ch["category"], ch["name"]) not in remote_keys]
        return remote + local_only

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

    def _is_quiz(self, ch: dict) -> bool:
        return ch.get("win_condition") == "mcq" or ch.get("category") == "quiz"

    def _is_quiz_downloaded(self, name: str) -> bool:
        if not self.quiz_dir:
            return False
        return (self.quiz_dir / name / "benchmark.json").exists()

    def _quiz_has_update(self, name: str, remote_size: int) -> bool:
        if not self.quiz_dir:
            return False
        meta_path = self.quiz_dir / name / STORE_META_FILE
        if not meta_path.exists():
            return False
        try:
            meta = json.loads(meta_path.read_text())
            return meta.get("size", 0) != remote_size and remote_size > 0
        except (json.JSONDecodeError, OSError):
            return False

    def download_challenge(self, category: str, name: str, asset: str, size: int = 0, win_condition: str = "") -> Path:
        proxy_url = PROXY_RELEASE_URL.format(repo=self.repo, tag=self.tag, asset=asset)
        direct_url = GITHUB_RELEASE_URL.format(repo=self.repo, tag=self.tag, asset=asset)
        is_quiz = win_condition == "mcq" or category == "quiz"
        if is_quiz and self.quiz_dir:
            dest = self.quiz_dir / name
        else:
            dest = self.challenges_dir / category / name

        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp_path = Path(tmp.name)

        try:
            self._download_url(proxy_url, direct_url, tmp_path)
            if dest.exists():
                shutil.rmtree(dest)
            self._extract_zip(tmp_path, dest)
            self._write_meta(dest, size)
        finally:
            tmp_path.unlink(missing_ok=True)

        return dest

    def delete_challenge(self, category: str, name: str, win_condition: str = "") -> None:
        is_quiz = win_condition == "mcq" or category == "quiz"
        if is_quiz and self.quiz_dir:
            dest = self.quiz_dir / name
        else:
            dest = self.challenges_dir / category / name
        if dest.exists():
            shutil.rmtree(dest)

    def _fetch_url(self, proxy_url: str, direct_url: str, timeout: int = 15) -> str:
        """Fetch URL content as string, try proxy first then fallback to direct."""
        try:
            with urllib.request.urlopen(proxy_url, timeout=timeout) as resp:
                return resp.read().decode()
        except Exception:
            pass
        with urllib.request.urlopen(direct_url, timeout=30) as resp:
            return resp.read().decode()

    def _download_url(self, proxy_url: str, direct_url: str, dest_path: Path) -> None:
        """Download file to dest_path, try proxy first then fallback to direct."""
        try:
            urllib.request.urlretrieve(proxy_url, dest_path)
            return
        except Exception:
            pass
        urllib.request.urlretrieve(direct_url, dest_path)

    def _extract_zip(self, zip_path: Path, dest: Path) -> None:
        dest.mkdir(parents=True, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as zf:
            zf.extractall(dest)

    def import_challenge(self, zip_bytes: bytes, filename: str) -> tuple[str, str]:
        """Import a local zip file. Filename should be 'category--name.zip'. Returns (category, name)."""
        stem = filename.rsplit(".", 1)[0] if "." in filename else filename
        if "--" in stem:
            category, name = stem.split("--", 1)
        else:
            category, name = "custom", stem

        dest = self.challenges_dir / category / name
        with tempfile.NamedTemporaryFile(suffix=".zip", delete=False) as tmp:
            tmp.write(zip_bytes)
            tmp_path = Path(tmp.name)

        try:
            if dest.exists():
                shutil.rmtree(dest)
            self._extract_zip(tmp_path, dest)
            self._write_meta(dest, len(zip_bytes))
        finally:
            tmp_path.unlink(missing_ok=True)

        return category, name

    def _write_meta(self, dest: Path, size: int) -> None:
        meta_path = dest / STORE_META_FILE
        meta_path.write_text(json.dumps({"size": size}))
