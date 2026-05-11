"""PrebuildManager – pre-build Docker images for challenges to avoid cold-start delays."""
from __future__ import annotations

import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

import yaml

from benchmark_platform.base import Challenge


@dataclass
class ChallengeStatus:
    code: str
    benchmark_id: str
    name: str
    source_path: Path = field(repr=False)
    status: str = "pending"  # pending | building | cached | failed
    log_lines: list[str] = field(default_factory=list)


class PrebuildManager:
    """Manages parallel docker compose build tasks for all challenges.

    Builds from SOURCE directories with stable image names (benchmark_id-service)
    so images persist across server restarts.
    """

    def __init__(self, challenges: list[Challenge], benchmark_folders: list[Path] | None = None) -> None:
        self._challenges = challenges
        self._statuses: dict[str, ChallengeStatus] = {}
        self._stop_flag = threading.Event()
        self._running = False
        self._executor: ThreadPoolExecutor | None = None

        # Build a mapping from benchmark_id → source path
        self._source_paths: dict[str, Path] = {}
        if benchmark_folders:
            for folder in benchmark_folders:
                if not folder.is_dir():
                    continue
                for entry in sorted(folder.iterdir()):
                    if not entry.is_dir():
                        continue
                    if (entry / "docker-compose.yml").exists():
                        self._source_paths[entry.name] = entry
                    else:
                        for sub in sorted(entry.iterdir()):
                            if sub.is_dir() and (sub / "docker-compose.yml").exists():
                                self._source_paths[sub.name] = sub

        seen_benchmarks: set[str] = set()
        for c in challenges:
            bm_id = c.get_benchmark_id()
            if bm_id in seen_benchmarks:
                continue
            seen_benchmarks.add(bm_id)

            bm = c.get_benchmark()
            source_path = self._source_paths.get(bm_id)
            if source_path is None:
                source_path = Path("challenges") / bm_id

            self._statuses[bm_id] = ChallengeStatus(
                code=bm_id,
                benchmark_id=bm_id,
                name=bm.name,
                source_path=source_path,
            )

    # ── Public API ──────────────────────────────────────────────────────

    def check_cached(self) -> None:
        """Check which images are already cached (built/pulled). Runs in parallel."""
        def _check_one(cs: ChallengeStatus) -> None:
            path = cs.source_path
            if not (path / "docker-compose.yml").exists():
                cs.status = "failed"
                cs.log_lines.append("docker-compose.yml not found")
                return

            try:
                images = self._get_expected_images(path, cs.benchmark_id)
                if not images:
                    cs.status = "pending"
                    return

                all_exist = True
                for img in images:
                    inspect = subprocess.run(
                        ["docker", "image", "inspect", img],
                        capture_output=True, text=True, timeout=10,
                    )
                    if inspect.returncode != 0:
                        all_exist = False
                        break

                cs.status = "cached" if all_exist else "pending"
            except Exception as e:
                cs.status = "pending"
                cs.log_lines.append(f"check error: {e}")

        statuses = list(self._statuses.values())
        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(_check_one, statuses))

    def start(self, concurrency: int = 1) -> None:
        """Start building images for all pending challenges."""
        if self._running:
            return
        self._stop_flag.clear()
        self._running = True

        for cs in self._statuses.values():
            if cs.status not in ("cached",):
                cs.status = "pending"
                cs.log_lines.clear()

        thread = threading.Thread(target=self._run_builds, args=(concurrency,), daemon=True)
        thread.start()

    def stop(self) -> None:
        """Signal remaining builds to be skipped."""
        self._stop_flag.set()

    def get_status(self) -> list[dict]:
        """Return status list for all challenges."""
        result = []
        for cs in self._statuses.values():
            result.append({
                "code": cs.code,
                "benchmark_id": cs.benchmark_id,
                "name": cs.name,
                "status": cs.status,
                "log_lines": cs.log_lines[-200:],
            })
        return result

    @property
    def is_running(self) -> bool:
        return self._running

    @property
    def cached_count(self) -> int:
        return sum(1 for cs in self._statuses.values() if cs.status == "cached")

    @property
    def total_count(self) -> int:
        return len(self._statuses)

    def remove_images(self, code: str) -> tuple[bool, str]:
        """Remove Docker images for a single challenge. Returns (success, message)."""
        cs = self._statuses.get(code)
        if not cs:
            return False, "Challenge not found"

        path = cs.source_path
        if not (path / "docker-compose.yml").exists():
            return False, "docker-compose.yml not found"

        try:
            images = self._get_expected_images(path, cs.benchmark_id)
            if not images:
                return False, "No images found"

            removed = []
            for img in images:
                rmi = subprocess.run(
                    ["docker", "rmi", "-f", img],
                    capture_output=True, text=True, timeout=30,
                )
                if rmi.returncode == 0:
                    removed.append(img)

            cs.status = "pending"
            cs.log_lines.clear()
            return True, f"已删除 {len(removed)} 个镜像"
        except Exception as e:
            return False, str(e)

    def remove_all_images(self) -> tuple[int, int]:
        """Remove images for all cached challenges. Returns (removed_count, failed_count)."""
        removed = 0
        failed = 0
        for cs in self._statuses.values():
            if cs.status != "cached":
                continue
            ok, _ = self.remove_images(cs.code)
            if ok:
                removed += 1
            else:
                failed += 1
        return removed, failed

    # ── Internal ────────────────────────────────────────────────────────

    def _get_expected_images(self, path: Path, benchmark_id: str) -> list[str]:
        """Get expected image names for a challenge based on buildable services."""
        compose_path = path / "docker-compose.yml"
        try:
            with open(compose_path) as f:
                data = yaml.safe_load(f)
            images = []
            for svc_name, svc in data.get("services", {}).items():
                if "build" not in svc:
                    continue
                if "image" in svc:
                    images.append(svc["image"])
                else:
                    images.append(f"{benchmark_id}-{svc_name}".lower())
            return images
        except Exception:
            return []

    def _run_builds(self, concurrency: int) -> None:
        """Run docker compose build for each pending challenge."""
        pending = [
            cs for cs in self._statuses.values()
            if cs.status == "pending"
        ]

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {}
            for cs in pending:
                if self._stop_flag.is_set():
                    break
                future = executor.submit(self._build_one, cs)
                futures[future] = cs

            for future in as_completed(futures):
                pass

        self._running = False

    def _build_one(self, cs: ChallengeStatus) -> None:
        """Build images for a single challenge from its source directory."""
        if self._stop_flag.is_set():
            cs.status = "pending"
            cs.log_lines.append("-- skipped (stopped) --")
            return

        cs.status = "building"
        cs.log_lines.append(f"--- Building {cs.benchmark_id} ---")

        path = cs.source_path
        if not (path / "docker-compose.yml").exists():
            cs.status = "failed"
            cs.log_lines.append("ERROR: docker-compose.yml not found")
            return

        # Read env vars from .env for FLAG
        env_file = path / ".env"
        env = dict(subprocess.os.environ)
        if env_file.exists():
            import dotenv
            env_vars = dotenv.dotenv_values(env_file)
            env.update({k: v for k, v in env_vars.items() if v is not None})

        # Use benchmark_id as project name for stable image naming
        env["COMPOSE_PROJECT_NAME"] = cs.benchmark_id.lower()

        try:
            proc = subprocess.Popen(
                ["docker", "compose", "build"],
                cwd=path,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                env=env,
            )

            for line in iter(proc.stdout.readline, ""):
                if self._stop_flag.is_set():
                    proc.terminate()
                    cs.status = "pending"
                    cs.log_lines.append("-- terminated (stopped) --")
                    return
                cs.log_lines.append(line.rstrip("\n"))

            proc.wait()

            if proc.returncode == 0:
                cs.status = "cached"
                cs.log_lines.append("--- Build complete ---")
            else:
                cs.status = "failed"
                cs.log_lines.append(f"--- Build failed (exit code {proc.returncode}) ---")
        except Exception as e:
            cs.status = "failed"
            cs.log_lines.append(f"ERROR: {e}")
