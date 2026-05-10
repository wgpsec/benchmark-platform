import json
import shutil
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import portpicker
import yaml
from rich.console import Console
from rich.table import Table

from benchmark_platform.base import Challenge
from benchmark_platform.base import Difficulty
from benchmark_platform.base import FlagState
from benchmark_platform.base import TargetInfo
from benchmark_platform.models.benchmark import Benchmark
from benchmark_platform.utils.logger import get_logger

logger = get_logger(Path('logs/competition-platform-server-logs.jsonl'))
console = Console()


class ChallengeManager:
    def __init__(
        self,
        benchmark_folders: list[Path],
        benchmark_ids: list[str],
        public_accessible_host: str,
        no_level_gate: bool = False,
    ) -> None:
        self.benchmark_folders = benchmark_folders
        self.benchmark_ids = benchmark_ids
        self.public_accessible_host = public_accessible_host
        self.no_level_gate = no_level_gate  # level gate enforcement not yet implemented; all challenges are always visible
        self.challenges: list[Challenge] = []
        self._instance_status: dict[str, str] = {}  # challenge_code → "stopped"|"running"

    def __enter__(self) -> 'ChallengeManager':
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    def start(self) -> 'ChallengeManager':
        discovered = self._discover_challenges()
        if not discovered:
            logger.warning("no challenges found in any benchmark folder")
            return self

        errors = []
        for folder, benchmark_id in discovered:
            try:
                challenge = self._create_challenge(folder, benchmark_id)
                self.challenges.append(challenge)
                self._instance_status[challenge.challenge_code] = "stopped"
            except Exception as e:
                errors.append((benchmark_id, e))
                logger.error("failed to prepare challenge",
                             benchmark_id=benchmark_id, error=str(e))

        if errors:
            self.stop()
            raise RuntimeError(
                f"Failed to prepare {len(errors)} challenges: "
                f"{[f'{bid}: {e}' for bid, e in errors]}"
            )
        logger.info("challenges prepared (not yet started)",
                    count=len(self.challenges))
        return self

    def stop(self) -> None:
        self._cleanup(self.challenges)
        self.challenges.clear()
        self._instance_status.clear()

    def _discover_challenges(self) -> list[tuple[Path, str]]:
        """Return (folder, benchmark_id) for every challenge in all benchmark_folders."""
        result: list[tuple[Path, str]] = []
        for folder in self.benchmark_folders:
            if not folder.is_dir():
                logger.warning("benchmark folder not found, skipping",
                               folder=str(folder))
                continue
            for entry in sorted(folder.iterdir()):
                if not entry.is_dir():
                    continue
                if not (entry / "benchmark.json").exists():
                    continue
                if self.benchmark_ids and entry.name not in self.benchmark_ids:
                    continue
                result.append((folder, entry.name))
        return result

    def _create_challenge(self, benchmark_folder: Path, benchmark_id: str) -> Challenge:
        challenge_id = str(uuid.uuid4())
        path = Challenge.get_base_path(benchmark_id, challenge_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        src = benchmark_folder / benchmark_id

        try:
            shutil.copytree(src, path)

            # Remap ports
            compose_path = path / 'docker-compose.yml'
            with open(compose_path) as f:
                data = yaml.safe_load(f)

            allocated_ports = []
            for svc in data.get('services', {}).values():
                new_ports = []
                for p in svc.get('ports', []):
                    if isinstance(p, str) and ':' in p:
                        host_port = portpicker.pick_unused_port()
                        allocated_ports.append(host_port)
                        parts = p.split(':')
                        new_ports.append(f"{host_port}:{parts[-1]}")
                    else:
                        new_ports.append(p)
                svc['ports'] = new_ports

            with open(compose_path, 'w') as f:
                yaml.dump(data, f)

            meta = json.loads((path / 'benchmark.json').read_text())
            meta['id'] = benchmark_id
            bm = Benchmark.model_validate(meta)

            flag_states = []
            bm_yaml_path = path / 'benchmark.yaml'
            if bm_yaml_path.exists():
                bm_yaml = yaml.safe_load(bm_yaml_path.read_text(encoding='utf-8'))
                for flag_def in bm_yaml.get('flags', []):
                    flag_states.append(FlagState(
                        id=flag_def['id'],
                        route=flag_def.get('route', '/'),
                        description=flag_def.get('description', ''),
                    ))

            _level_map = {1: Difficulty.EASY, 2: Difficulty.MEDIUM, 3: Difficulty.HARD}
            if bm.level not in _level_map:
                raise ValueError(f"Unknown level {bm.level!r} in benchmark {benchmark_id!r}")

            challenge = Challenge(
                challenge_code=challenge_id,
                difficulty=_level_map[bm.level],
                points=bm.points,
                hint_viewed=False,
                solved=False,
                target_info=TargetInfo(
                    ip=self.public_accessible_host, port=allocated_ports,
                ),
                flag_states=flag_states,
            )
            challenge.set_benchmark_id(benchmark_id)
            return challenge
        except Exception:
            if path.exists():
                shutil.rmtree(path)
            raise

    def start_challenge_instance(self, challenge_code: str) -> list[str]:
        """Start docker containers for one challenge. Return entrypoint list."""
        challenge = self._find_by_code(challenge_code)
        self._compose(challenge.get_benchmark_id(), challenge_code, 'up', '-d')
        self._instance_status[challenge_code] = "running"
        return [
            f"{self.public_accessible_host}:{p}"
            for p in challenge.target_info.port
        ]

    def stop_challenge_instance(self, challenge_code: str) -> None:
        """Stop docker containers for one challenge."""
        challenge = self._find_by_code(challenge_code)
        self._compose(challenge.get_benchmark_id(), challenge_code, 'down')
        self._instance_status[challenge_code] = "stopped"

    def get_instance_status(self, challenge_code: str) -> str:
        challenge = self._find_by_code(challenge_code)
        status = self._instance_status.get(challenge_code, "stopped")
        if status != "running":
            return status
        return self._check_container_health(challenge)

    def _check_container_health(self, challenge: Challenge) -> str:
        path = Challenge.get_base_path(challenge.get_benchmark_id(), challenge.challenge_code)
        if not (path / 'docker-compose.yml').exists():
            return "running"
        try:
            res = subprocess.run(
                ['docker', 'compose', 'ps', '--format', 'json'],
                cwd=path, capture_output=True, text=True, timeout=5,
            )
            if res.returncode != 0:
                return "running"
            import json as _json
            for line in res.stdout.strip().splitlines():
                info = _json.loads(line)
                health = info.get("Health", "")
                if health == "unhealthy":
                    return "unhealthy"
        except Exception:
            pass
        return "running"

    def _find_by_code(self, challenge_code: str) -> Challenge:
        for c in self.challenges:
            if c.challenge_code == challenge_code:
                return c
        raise KeyError(f"Challenge {challenge_code!r} not found")

    def _cleanup(self, challenges: list[Challenge]) -> None:
        if not challenges:
            return
        logger.info('cleaning up challenges', count=len(challenges))
        with ThreadPoolExecutor() as executor:
            list(executor.map(
                lambda c: self._compose(c.get_benchmark_id(), c.challenge_code, 'down'),
                challenges,
            ))
            def remove_dir(c):
                shutil.rmtree(
                    Challenge.get_base_path(c.get_benchmark_id(), c.challenge_code),
                    ignore_errors=True,
                )
            list(executor.map(remove_dir, challenges))

    def _compose(self, benchmark_id: str, code: str, *args) -> None:
        path = Challenge.get_base_path(benchmark_id, code)
        if not (path / 'docker-compose.yml').exists():
            return
        cmd = ['docker', 'compose'] + list(args)
        logger.info("docker compose", action="compose", cmd=" ".join(cmd), cwd=str(path))
        res = subprocess.run(
            cmd,
            cwd=path, capture_output=True, text=True,
        )
        if res.returncode != 0:
            logger.error("docker compose failed", action="compose",
                         cmd=" ".join(cmd), stderr=res.stderr[:500], stdout=res.stdout[:200])
            raise RuntimeError(f"Docker compose failed: {res.stderr}")

    def print_summary_table(self) -> None:
        if not self.challenges:
            return
        table = Table(
            title='Challenges Summary',
            show_header=True, header_style='bold magenta',
        )
        table.add_column('Benchmark ID', style='purple')
        table.add_column('Challenge Code', style='cyan', no_wrap=True)
        table.add_column('IP', style='green')
        table.add_column('Port', style='yellow')
        table.add_column('Status', style='blue')

        for c in self.challenges:
            status = self._instance_status.get(c.challenge_code, 'stopped')
            for p in c.target_info.port:
                table.add_row(
                    c.get_benchmark_id(), c.challenge_code,
                    c.target_info.ip, str(p), status,
                )
        console.print('\n', table, '\n')

    def get_level_for_challenge(self, challenge: Challenge) -> int:
        """Return the level (1/2/3) for a challenge based on its difficulty."""
        level_map = {Difficulty.EASY: 1, Difficulty.MEDIUM: 2, Difficulty.HARD: 3}
        return level_map[challenge.difficulty]

    def get_current_level(self) -> int:
        """Return the highest unlocked level based on solved challenges."""
        if not self.challenges:
            return 1
        levels = sorted(set(self.get_level_for_challenge(c) for c in self.challenges))
        for level in levels:
            at_level = [c for c in self.challenges if self.get_level_for_challenge(c) == level]
            if not all(c.solved for c in at_level):
                return level
        return levels[-1]

    def is_level_unlocked(self, level: int) -> bool:
        """Check if a level is accessible. Always True when no_level_gate is set."""
        if self.no_level_gate:
            return True
        return level <= self.get_current_level()
