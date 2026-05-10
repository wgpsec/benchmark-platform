"""PrebuildManager – pre-build Docker images for challenges to avoid cold-start delays."""

import subprocess
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from pathlib import Path

from benchmark_platform.base import Challenge


@dataclass
class ChallengeStatus:
    code: str
    benchmark_id: str
    name: str
    status: str = "pending"  # pending | building | cached | failed
    log_lines: list[str] = field(default_factory=list)


class PrebuildManager:
    """Manages parallel docker compose build tasks for all challenges."""

    def __init__(self, challenges: list[Challenge]) -> None:
        self._challenges = challenges
        self._statuses: dict[str, ChallengeStatus] = {}
        self._stop_flag = threading.Event()
        self._running = False
        self._executor: ThreadPoolExecutor | None = None

        for c in challenges:
            bm = c.get_benchmark()
            self._statuses[c.challenge_code] = ChallengeStatus(
                code=c.challenge_code,
                benchmark_id=c.get_benchmark_id(),
                name=bm.name,
            )

    # ── Public API ──────────────────────────────────────────────────────

    def check_cached(self) -> None:
        """Check which images are already cached (built/pulled). Runs in parallel."""
        def _check_one(challenge: Challenge) -> None:
            cs = self._statuses[challenge.challenge_code]
            path = Challenge.get_base_path(challenge.get_benchmark_id(), challenge.challenge_code)
            if not (path / "docker-compose.yml").exists():
                cs.status = "failed"
                cs.log_lines.append("docker-compose.yml not found")
                return

            try:
                # Get list of images from compose config
                res = subprocess.run(
                    ["docker", "compose", "config", "--images"],
                    cwd=path, capture_output=True, text=True, timeout=15,
                )
                if res.returncode != 0:
                    cs.status = "pending"
                    return

                images = [img.strip() for img in res.stdout.strip().splitlines() if img.strip()]
                if not images:
                    cs.status = "pending"
                    return

                # Check if all images exist locally
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

        with ThreadPoolExecutor(max_workers=4) as executor:
            list(executor.map(_check_one, self._challenges))

    def start(self, concurrency: int = 1) -> None:
        """Start building images for all pending challenges."""
        if self._running:
            return
        self._stop_flag.clear()
        self._running = True

        # Mark non-cached as pending
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
        for c in self._challenges:
            cs = self._statuses[c.challenge_code]
            result.append({
                "code": cs.code,
                "benchmark_id": cs.benchmark_id,
                "name": cs.name,
                "status": cs.status,
                "log_lines": cs.log_lines[-200:],  # limit to last 200 lines
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

    # ── Internal ────────────────────────────────────────────────────────

    def _run_builds(self, concurrency: int) -> None:
        """Run docker compose build for each pending challenge."""
        pending = [
            c for c in self._challenges
            if self._statuses[c.challenge_code].status == "pending"
        ]

        with ThreadPoolExecutor(max_workers=concurrency) as executor:
            futures = {}
            for challenge in pending:
                if self._stop_flag.is_set():
                    break
                future = executor.submit(self._build_one, challenge)
                futures[future] = challenge

            for future in as_completed(futures):
                # just consume the futures
                pass

        self._running = False

    def _build_one(self, challenge: Challenge) -> None:
        """Build images for a single challenge."""
        cs = self._statuses[challenge.challenge_code]

        if self._stop_flag.is_set():
            cs.status = "pending"
            cs.log_lines.append("-- skipped (stopped) --")
            return

        cs.status = "building"
        cs.log_lines.append(f"--- Building {cs.benchmark_id} ---")

        path = Challenge.get_base_path(challenge.get_benchmark_id(), challenge.challenge_code)
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
