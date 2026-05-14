from __future__ import annotations

import json
import re
import shutil
import subprocess
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path
import threading

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
from benchmark_platform.db import (
    get_level_gate_config, get_team_progress,
    get_instance_by_benchmark_id, upsert_instance, update_instance_status,
    get_instance_timeout_config,
)

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

        seen: set[str] = set()
        unique: list[tuple[Path, str]] = []
        for folder, bid in discovered:
            if bid not in seen:
                seen.add(bid)
                unique.append((folder, bid))
            else:
                logger.warning("duplicate benchmark_id skipped",
                               benchmark_id=bid, folder=str(folder))
        discovered = unique

        errors = []
        for folder, benchmark_id in discovered:
            try:
                challenge = self._reconcile_or_create(folder, benchmark_id)
                self.challenges.append(challenge)
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

        self._cleanup_orphan_runtimes(seen)
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

    def _reconcile_or_create(self, benchmark_folder: Path, benchmark_id: str) -> Challenge:
        """Check DB for existing instance, reconcile with Docker, or create new."""
        record = get_instance_by_benchmark_id(benchmark_id)

        if record and record["status"] == "running":
            runtime_path = Path(record["runtime_path"])
            if runtime_path.exists() and self._is_docker_running(runtime_path):
                challenge = self._restore_challenge(benchmark_id, record)
                self._instance_status[challenge.challenge_code] = "running"
                timeout_config = get_instance_timeout_config()
                level = self.get_level_for_challenge(challenge)
                timeout_secs = timeout_config.get(level, 7200)
                now = datetime.now(timezone.utc)
                expires_at = (now + timedelta(seconds=timeout_secs)).strftime("%Y-%m-%dT%H:%M:%SZ")
                update_instance_status(benchmark_id, "running",
                                       started_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                       expires_at=expires_at)
                logger.info("recovered running instance",
                            benchmark_id=benchmark_id,
                            challenge_code=record["challenge_code"])
                return challenge
            else:
                self._cleanup_stale_record(record)

        if record and record["status"] in ("stopped", "expired"):
            runtime_path = Path(record["runtime_path"])
            if runtime_path.exists():
                shutil.rmtree(runtime_path, ignore_errors=True)

        challenge = self._create_challenge(benchmark_folder, benchmark_id)
        self._instance_status[challenge.challenge_code] = "stopped"
        upsert_instance(
            instance_id=str(uuid.uuid4()),
            benchmark_id=benchmark_id,
            challenge_code=challenge.challenge_code,
            runtime_path=str(Challenge.get_base_path(benchmark_id, challenge.challenge_code, self.runtime_dir)),
            ports=challenge.target_info.port,
            status="stopped",
        )
        return challenge

    def _is_docker_running(self, runtime_path: Path) -> bool:
        """Check if docker compose services are running in the given path."""
        compose_file = runtime_path / 'docker-compose.yml'
        if not compose_file.exists():
            return False
        try:
            res = subprocess.run(
                ['docker', 'compose', 'ps', '--format', 'json'],
                cwd=runtime_path, capture_output=True, text=True, timeout=10,
            )
            if res.returncode != 0:
                return False
            for line in res.stdout.strip().splitlines():
                info = json.loads(line)
                state = info.get("State", "")
                if state == "running":
                    return True
            return False
        except Exception:
            return False

    def _restore_challenge(self, benchmark_id: str, record: dict) -> Challenge:
        """Rebuild a Challenge object from a DB record and its runtime directory."""
        runtime_path = Path(record["runtime_path"])
        challenge_code = record["challenge_code"]
        ports = json.loads(record["ports"])

        meta = json.loads((runtime_path / 'benchmark.json').read_text())
        meta['id'] = benchmark_id
        bm = Benchmark.model_validate(meta)

        flag_states = []
        bm_yaml_path = runtime_path / 'benchmark.yaml'
        if bm_yaml_path.exists():
            bm_yaml = yaml.safe_load(bm_yaml_path.read_text(encoding='utf-8'))
            for flag_def in bm_yaml.get('flags', []):
                flag_states.append(FlagState(
                    id=flag_def['id'],
                    route=flag_def.get('route', '/'),
                    description=flag_def.get('description', ''),
                ))

        _level_map = {1: Difficulty.EASY, 2: Difficulty.MEDIUM, 3: Difficulty.HARD}
        import platform as _platform
        host_is_arm = _platform.machine() in ('arm64', 'aarch64')

        compose_path = runtime_path / 'docker-compose.yml'
        with open(compose_path) as f:
            data = yaml.safe_load(f)
        is_emulated = host_is_arm and any(
            svc.get('platform', '').endswith('amd64')
            for svc in data.get('services', {}).values()
        )

        challenge = Challenge(
            challenge_code=challenge_code,
            difficulty=_level_map[bm.level],
            points=bm.points,
            hint_viewed=False,
            solved=False,
            target_info=TargetInfo(ip=self.public_accessible_host, port=ports),
            flag_states=flag_states,
            emulated=is_emulated,
        )
        challenge.set_benchmark_id(benchmark_id)
        challenge.set_runtime_dir(self.runtime_dir)
        return challenge

    def _cleanup_stale_record(self, record: dict) -> None:
        """Docker is dead but DB says running -- clean up."""
        runtime_path = Path(record["runtime_path"])
        if runtime_path.exists():
            try:
                subprocess.run(
                    ['docker', 'compose', 'down'],
                    cwd=runtime_path, capture_output=True, text=True, timeout=30,
                )
            except Exception:
                pass
            shutil.rmtree(runtime_path, ignore_errors=True)
        update_instance_status(record["benchmark_id"], "stopped")
        logger.info("cleaned stale instance",
                    benchmark_id=record["benchmark_id"],
                    challenge_code=record["challenge_code"])

    def _cleanup_orphan_runtimes(self, known_benchmark_ids: set[str]) -> None:
        """Remove runtime directories that have no matching discovered benchmark_id."""
        if not self.runtime_dir.exists():
            return
        for entry in self.runtime_dir.iterdir():
            if not entry.is_dir():
                continue
            if entry.name in known_benchmark_ids:
                continue
            if entry.name.startswith('.'):
                continue
            logger.info("cleaning orphan runtime directory", path=str(entry))
            compose_dirs = [d for d in entry.iterdir() if d.is_dir()]
            for d in compose_dirs:
                try:
                    subprocess.run(
                        ['docker', 'compose', 'down'],
                        cwd=d, capture_output=True, text=True, timeout=30,
                    )
                except Exception:
                    pass
            shutil.rmtree(entry, ignore_errors=True)

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
    _TEXT_FILENAMES = {
        'Dockerfile', 'Makefile', 'Procfile', 'Gemfile', 'Rakefile',
        'Vagrantfile', 'Brewfile',
    }

    def _is_text_file(self, fpath: Path) -> bool:
        return fpath.suffix.lower() in self._TEXT_EXTENSIONS or fpath.name in self._TEXT_FILENAMES

    _FLAG_LITERAL_RE = re.compile(r'[Ff][Ll][Aa][Gg]\{[^}]+\}')

    def _inject_dynamic_flags(self, path: Path) -> None:
        """Inject dynamic flags using canaries as the single source of truth.

        Algorithm:
        1. Read canaries from benchmark.json (preferred, authoritative)
        2. If canaries empty, fall back to .env + source scan (backward compat)
        3. Generate a dynamic flag{uuid} for each real flag
        4. Scan ALL text files for flag literals (FLAG{...} / flag{...})
        5. Literals matching a real flag → replaced with corresponding dynamic flag
        6. Other flag literals → replaced with random fake flags (not submittable)
        7. Rewrite .env with dynamic flag values
        """
        bm_path = path / 'benchmark.json'
        meta = json.loads(bm_path.read_text(encoding='utf-8'))
        canaries = [c for c in meta.get('canaries', []) if c]

        if canaries:
            real_flag_map: dict[str, str] = {}
            for canary in canaries:
                real_flag_map[canary] = f'flag{{{uuid.uuid4()}}}'
        else:
            logger.warning(
                "benchmark.json canaries 为空，使用 fallback 逻辑",
                path=str(bm_path),
            )
            real_flag_map = self._fallback_collect_flags(path)

        if not real_flag_map:
            real_flag_map['FLAG{placeholder}'] = f'flag{{{uuid.uuid4()}}}'

        fake_flag_map: dict[str, str] = {}
        for fpath in path.rglob('*'):
            if not fpath.is_file() or not self._is_text_file(fpath):
                continue
            try:
                text = fpath.read_text(encoding='utf-8')
            except (UnicodeDecodeError, OSError):
                continue
            for m in self._FLAG_LITERAL_RE.finditer(text):
                val = m.group(0)
                if val not in real_flag_map and val not in fake_flag_map:
                    fake_flag_map[val] = f'flag{{{uuid.uuid4()}}}'

        combined_map = {**real_flag_map, **fake_flag_map}
        self._rewrite_env_file(path, real_flag_map, list(real_flag_map.keys()))
        self._replace_flags_in_dir(path, combined_map, skip_env=True)

    def _fallback_collect_flags(self, path: Path) -> dict[str, str]:
        """Backward-compat: collect flags from .env and source scan."""
        flag_map: dict[str, str] = {}
        env_path = path / '.env'
        if env_path.exists():
            content = env_path.read_text(encoding='utf-8')
            for m in self._FLAG_RE.finditer(content):
                old_flag = m.group(2).strip()
                if old_flag and old_flag not in flag_map:
                    flag_map[old_flag] = f'flag{{{uuid.uuid4()}}}'
        if not flag_map:
            for fpath in path.rglob('*'):
                if not fpath.is_file() or not self._is_text_file(fpath):
                    continue
                try:
                    text = fpath.read_text(encoding='utf-8')
                except (UnicodeDecodeError, OSError):
                    continue
                for m in self._FLAG_LITERAL_RE.finditer(text):
                    val = m.group(0)
                    if val not in flag_map:
                        flag_map[val] = f'flag{{{uuid.uuid4()}}}'
        return flag_map

    def _rewrite_env_file(
        self, path: Path, real_flag_map: dict[str, str], canaries: list[str],
    ) -> None:
        """Rewrite .env so FLAG variables carry the dynamic flag values."""
        env_path = path / '.env'
        primary_flag = real_flag_map[canaries[0]]

        if env_path.exists():
            lines = env_path.read_text(encoding='utf-8').splitlines()
            new_lines = []
            flag_idx = 0
            for line in lines:
                m = self._FLAG_RE.match(line)
                if m:
                    var_name = m.group(1)
                    if flag_idx < len(canaries):
                        dynamic_val = real_flag_map[canaries[flag_idx]]
                        flag_idx += 1
                    else:
                        dynamic_val = primary_flag
                    new_lines.append(f'{var_name}="{dynamic_val}"')
                else:
                    new_lines.append(line)
            env_path.write_text('\n'.join(new_lines) + '\n', encoding='utf-8')
        else:
            env_path.write_text(f'FLAG="{primary_flag}"\n', encoding='utf-8')

    def _replace_flags_in_dir(self, path: Path, flag_map: dict[str, str], skip_env: bool = False) -> None:
        """Replace old flag strings with new ones across all text files."""
        if not flag_map:
            return
        env_path = path / '.env'
        for fpath in path.rglob('*'):
            if not fpath.is_file():
                continue
            if not self._is_text_file(fpath):
                continue
            if skip_env and fpath == env_path:
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
