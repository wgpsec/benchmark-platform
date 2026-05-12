from __future__ import annotations

import json
import re
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
from benchmark_platform.db import get_level_gate_config, get_team_progress

logger = get_logger(Path('logs/competition-platform-server-logs.jsonl'))
console = Console()


class ChallengeManager:
    def __init__(
        self,
        benchmark_folders: list[Path],
        benchmark_ids: list[str],
        public_accessible_host: str,
        no_level_gate: bool = False,
        runtime_dir: Path | None = None,
    ) -> None:
        self.benchmark_folders = benchmark_folders
        self.benchmark_ids = benchmark_ids
        self.public_accessible_host = public_accessible_host
        self.no_level_gate = no_level_gate
        self.runtime_dir = runtime_dir or Path('runtime')
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
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

    def reload(self) -> tuple[int, list[str]]:
        """Discover and load newly added challenges without affecting running instances.

        Returns (added_count, error_list).
        """
        existing_ids = {c.get_benchmark_id() for c in self.challenges}
        discovered = self._discover_challenges()
        new_discoveries = [
            (folder, bid) for folder, bid in discovered
            if bid not in existing_ids
        ]

        if not new_discoveries:
            return 0, []

        added = 0
        errors = []
        for folder, benchmark_id in new_discoveries:
            try:
                challenge = self._create_challenge(folder, benchmark_id)
                self.challenges.append(challenge)
                self._instance_status[challenge.challenge_code] = "stopped"
                added += 1
            except Exception as e:
                errors.append(f"{benchmark_id}: {e}")
                logger.error("failed to load new challenge",
                             benchmark_id=benchmark_id, error=str(e))

        if added:
            logger.info("hot-reloaded new challenges", added=added, errors=len(errors))

        return added, errors

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
                if entry.name.startswith('.'):
                    continue
                if (entry / "benchmark.json").exists():
                    if self.benchmark_ids and entry.name not in self.benchmark_ids:
                        continue
                    result.append((folder, entry.name))
                else:
                    for sub in sorted(entry.iterdir()):
                        if not sub.is_dir():
                            continue
                        if sub.name.startswith('.'):
                            continue
                        if not (sub / "benchmark.json").exists():
                            continue
                        if self.benchmark_ids and sub.name not in self.benchmark_ids:
                            continue
                        result.append((entry, sub.name))
        return result

    def _create_challenge(self, benchmark_folder: Path, benchmark_id: str) -> Challenge:
        challenge_id = str(uuid.uuid4())
        path = Challenge.get_base_path(benchmark_id, challenge_id, self.runtime_dir)
        path.parent.mkdir(parents=True, exist_ok=True)
        src = benchmark_folder / benchmark_id

        try:
            shutil.copytree(src, path)

            # Generate dynamic flags
            self._inject_dynamic_flags(path)

            # Remap ports
            compose_path = path / 'docker-compose.yml'
            with open(compose_path) as f:
                data = yaml.safe_load(f)

            allocated_ports = []
            for svc_name, svc in data.get('services', {}).items():
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
                if 'build' in svc and 'image' not in svc:
                    svc['image'] = f"{benchmark_id}-{svc_name}".lower()

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

            import platform as _platform
            host_is_arm = _platform.machine() in ('arm64', 'aarch64')
            is_emulated = host_is_arm and any(
                svc.get('platform', '').endswith('amd64')
                for svc in data.get('services', {}).values()
            )

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
                emulated=is_emulated,
            )
            challenge.set_benchmark_id(benchmark_id)
            challenge.set_runtime_dir(self.runtime_dir)
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
        path = Challenge.get_base_path(challenge.get_benchmark_id(), challenge.challenge_code, self.runtime_dir)
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
                    Challenge.get_base_path(c.get_benchmark_id(), c.challenge_code, self.runtime_dir),
                    ignore_errors=True,
                )
            list(executor.map(remove_dir, challenges))

    _FLAG_RE = re.compile(r'^(FLAG(?:_\w+|[0-9]*))\s*=\s*["\']?([^"\'\n]+)["\']?', re.MULTILINE)
    _TEXT_EXTENSIONS = {
        '.py', '.js', '.ts', '.go', '.rb', '.php', '.java', '.sh', '.bash',
        '.sql', '.html', '.htm', '.xml', '.json', '.yaml', '.yml', '.toml',
        '.env', '.txt', '.md', '.cfg', '.ini', '.conf', '.tpl', '.tmpl',
        '.jsx', '.tsx', '.vue', '.css', '.csv',
    }

    def _inject_dynamic_flags(self, path: Path) -> None:
        """Generate dynamic flags and replace all occurrences in the runtime copy."""
        env_path = path / '.env'
        flag_map: dict[str, str] = {}

        # Collect static flags from .env
        if env_path.exists():
            content = env_path.read_text(encoding='utf-8')
            for m in self._FLAG_RE.finditer(content):
                old_flag = m.group(2).strip()
                if old_flag and old_flag not in flag_map:
                    flag_map[old_flag] = f'flag{{{uuid.uuid4()}}}'

        # Collect static flags from benchmark.json canaries
        bm_path = path / 'benchmark.json'
        if bm_path.exists():
            try:
                meta = json.loads(bm_path.read_text(encoding='utf-8'))
                for canary in meta.get('canaries', []):
                    if canary and canary not in flag_map:
                        flag_map[canary] = f'flag{{{uuid.uuid4()}}}'
            except (json.JSONDecodeError, OSError):
                pass

        # If still no flags found, scan source files for FLAG{...} pattern
        if not flag_map:
            flag_literal_re = re.compile(r'FLAG\{[^}]+\}')
            for fpath in path.rglob('*'):
                if not fpath.is_file() or fpath.suffix.lower() not in self._TEXT_EXTENSIONS:
                    continue
                try:
                    text = fpath.read_text(encoding='utf-8')
                except (UnicodeDecodeError, OSError):
                    continue
                for m in flag_literal_re.finditer(text):
                    val = m.group(0)
                    if val not in flag_map:
                        flag_map[val] = f'flag{{{uuid.uuid4()}}}'

        if not flag_map:
            flag_map['FLAG{placeholder}'] = f'flag{{{uuid.uuid4()}}}'

        # Rewrite .env with dynamic values
        new_env_lines = []
        if env_path.exists():
            for line in env_path.read_text(encoding='utf-8').splitlines():
                m = self._FLAG_RE.match(line)
                if m:
                    old_val = m.group(2).strip()
                    new_val = flag_map.get(old_val, f'flag{{{uuid.uuid4()}}}')
                    new_env_lines.append(f'{m.group(1)}="{new_val}"')
                else:
                    new_env_lines.append(line)
        else:
            new_val = next(iter(flag_map.values()))
            new_env_lines.append(f'FLAG="{new_val}"')
        env_path.write_text('\n'.join(new_env_lines) + '\n', encoding='utf-8')

        # Replace flag strings across all text files in runtime copy
        self._replace_flags_in_dir(path, flag_map)

    def _replace_flags_in_dir(self, path: Path, flag_map: dict[str, str]) -> None:
        """Replace old flag strings with new ones across all text files."""
        if not flag_map:
            return
        for fpath in path.rglob('*'):
            if not fpath.is_file():
                continue
            if fpath.suffix.lower() not in self._TEXT_EXTENSIONS:
                continue
            try:
                content = fpath.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue
            replaced = content
            for old_flag, new_flag in flag_map.items():
                replaced = replaced.replace(old_flag, new_flag)
            if replaced != content:
                fpath.write_text(replaced, encoding='utf-8')

    def _compose(self, benchmark_id: str, code: str, *args) -> None:
        path = Challenge.get_base_path(benchmark_id, code, self.runtime_dir)
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

    def get_current_level(self, team_id: str = None) -> int:
        """Return the highest unlocked level based on solved challenges and gate config."""
        if not self.challenges:
            return 1
        config = get_level_gate_config()
        mode = config["mode"]
        threshold = config["threshold"]

        team_progress = get_team_progress(team_id) if team_id else None

        levels = sorted(set(self.get_level_for_challenge(c) for c in self.challenges))
        for level in levels:
            at_level = [c for c in self.challenges if self.get_level_for_challenge(c) == level]
            if team_progress is not None:
                solved_flags = sum(
                    len(team_progress.get(c.get_benchmark_id(), {})) for c in at_level
                )
            else:
                solved_flags = sum(c.solved_count for c in at_level)
            total_flags = sum(c.flag_count for c in at_level)
            if total_flags == 0:
                continue
            if mode == "all":
                if solved_flags < total_flags:
                    return level
            elif mode == "percentage":
                if (solved_flags * 100 // total_flags) < threshold:
                    return level
            elif mode == "count":
                if solved_flags < threshold:
                    return level
        return levels[-1]

    def is_level_unlocked(self, level: int, team_id: str = None) -> bool:
        """Check if a level is accessible. Always True when no_level_gate is set."""
        if self.no_level_gate:
            return True
        return level <= self.get_current_level(team_id)
