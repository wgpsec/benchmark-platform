from __future__ import annotations

import json
import re
import shutil
import subprocess
import time
import uuid
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
    get_instance_by_benchmark_id, upsert_instance,
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
        self._instance_status: dict[str, str] = {}  # challenge_code → "stopped"|"running"|"starting"|"stopping"
        self._instance_logs: dict[str, list[str]] = {}  # benchmark_id → log lines
        self._code_aliases: dict[str, str] = {}  # old_challenge_code → benchmark_id
        self._team_instances: dict[tuple[str, str], str] = {}  # (benchmark_id, team_id) → challenge_code
        self.max_instances_per_team: int = 3
        self._reaper_stop = threading.Event()
        self._reaper_thread: threading.Thread | None = None

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
                challenge = self._load_challenge_metadata(folder, benchmark_id)
                self.challenges.append(challenge)
                self._instance_status[challenge.challenge_code] = "stopped"
            except Exception as e:
                errors.append((benchmark_id, e))
                logger.error("failed to load challenge metadata",
                             benchmark_id=benchmark_id, error=str(e))

        if errors:
            self.stop()
            raise RuntimeError(
                f"Failed to load {len(errors)} challenges: "
                f"{[f'{bid}: {e}' for bid, e in errors]}"
            )
        logger.info("challenges loaded (metadata only)",
                    count=len(self.challenges))

        self._recover_running_instances()
        self._cleanup_orphan_runtimes(seen)
        self._start_reaper()

        # Load max_instances_per_team from settings
        from benchmark_platform.db import get_setting
        try:
            self.max_instances_per_team = int(get_setting("max_instances_per_team", "3"))
        except (ValueError, TypeError):
            self.max_instances_per_team = 3

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
        self._reaper_stop.set()
        if self._reaper_thread is not None:
            self._reaper_thread.join(timeout=5)
            self._reaper_thread = None
        self.stop_all_instances()
        self.challenges.clear()
        self._instance_status.clear()
        self._team_instances.clear()
        self._prune_orphan_volumes()

    def _start_reaper(self) -> None:
        """Start the background reaper thread for expired instances."""
        if self._reaper_thread is not None:
            return
        self._reaper_stop.clear()
        self._reaper_thread = threading.Thread(target=self._reaper_loop, daemon=True)
        self._reaper_thread.start()
        logger.info("instance reaper started")

    def _reaper_loop(self) -> None:
        """Periodically check for and clean up expired instances."""
        from benchmark_platform.db import get_expired_instances
        while not self._reaper_stop.is_set():
            try:
                expired = get_expired_instances()
                for record in expired:
                    benchmark_id = record["benchmark_id"]
                    challenge_code = record["challenge_code"]
                    team_id = record["team_id"]
                    runtime_path = Path(record["runtime_path"])
                    logger.info("reaping expired instance",
                                benchmark_id=benchmark_id,
                                team_id=team_id,
                                challenge_code=challenge_code)
                    try:
                        if runtime_path.exists():
                            self._compose_at_path(runtime_path, 'down', '-v', '--remove-orphans')
                        from benchmark_platform.db import update_instance_status_by_team
                        update_instance_status_by_team(benchmark_id, team_id, "expired")
                        self._instance_status[challenge_code] = "stopped"
                        key = (benchmark_id, team_id if team_id else "__shared__")
                        self._team_instances.pop(key, None)
                    except Exception as e:
                        logger.error("reaper failed for instance",
                                     benchmark_id=benchmark_id, error=str(e))
            except Exception as e:
                logger.error("reaper loop error", error=str(e))
            self._reaper_stop.wait(30)

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
                    if self._is_mcq(entry / "benchmark.json"):
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
                        if self._is_mcq(sub / "benchmark.json"):
                            continue
                        result.append((entry, sub.name))
        return result

    @staticmethod
    def _is_mcq(meta_path: Path) -> bool:
        """Return True if the benchmark.json indicates an MCQ quiz (no Docker needed)."""
        try:
            data = json.loads(meta_path.read_text(encoding="utf-8"))
            return data.get("win_condition") == "mcq"
        except Exception:
            return False

    @staticmethod
    def _detect_requires_windows_iso(compose_data: dict) -> bool:
        """Check if any service uses a dockur/windows image."""
        for svc in compose_data.get("services", {}).values():
            image = svc.get("image", "")
            if "dockur" in image.lower():
                return True
        return False

    def _load_challenge_metadata(self, benchmark_folder: Path, benchmark_id: str) -> Challenge:
        """Load challenge metadata without creating a runtime instance."""
        src = benchmark_folder / benchmark_id
        meta = json.loads((src / 'benchmark.json').read_text(encoding='utf-8'))
        meta['id'] = benchmark_id
        bm = Benchmark.model_validate(meta)

        flag_states = []
        bm_yaml_path = src / 'benchmark.yaml'
        if bm_yaml_path.exists():
            bm_yaml = yaml.safe_load(bm_yaml_path.read_text(encoding='utf-8'))
            for flag_def in bm_yaml.get('flags', []):
                flag_states.append(FlagState(
                    id=flag_def['id'],
                    route=flag_def.get('route', '/'),
                    description=flag_def.get('description', ''),
                ))

        _level_map = {1: Difficulty.EASY, 2: Difficulty.MEDIUM, 3: Difficulty.HARD, 4: Difficulty.AD}
        if bm.level not in _level_map:
            raise ValueError(f"Unknown level {bm.level!r} in benchmark {benchmark_id!r}")

        import platform as _platform
        host_is_arm = _platform.machine() in ('arm64', 'aarch64')

        compose_path = src / 'docker-compose.yml'
        with open(compose_path) as f:
            data = yaml.safe_load(f)

        is_emulated = host_is_arm and any(
            svc.get('platform', '').endswith('amd64')
            for svc in data.get('services', {}).values()
        )

        is_unsupported = False
        unsupported_reason = ""
        if bm.requires:
            if bm.requires.arch == "x86_64" and host_is_arm:
                is_unsupported = True
                unsupported_reason = "需要 x86_64 架构"
            elif bm.requires.arch == "aarch64" and not host_is_arm:
                is_unsupported = True
                unsupported_reason = "需要 ARM64 架构"
            if bm.requires.kvm and not Path('/dev/kvm').exists():
                is_unsupported = True
                unsupported_reason = "需要 KVM 虚拟化支持 (/dev/kvm)"
            if bm.requires.arch == "x86_64" and host_is_arm and bm.requires.kvm:
                unsupported_reason = "需要 x86_64 架构 + KVM 虚拟化"

        requires_win_iso = self._detect_requires_windows_iso(data)

        challenge = Challenge(
            challenge_code=benchmark_id,  # Use benchmark_id as stable code
            difficulty=_level_map[bm.level],
            points=bm.points,
            hint_viewed=False,
            solved=False,
            target_info=TargetInfo(ip=self.public_accessible_host, port=[]),
            flag_states=flag_states,
            emulated=is_emulated,
            unsupported=is_unsupported,
            unsupported_reason=unsupported_reason,
            requires_windows_iso=requires_win_iso,
        )
        challenge.set_benchmark_id(benchmark_id)
        challenge.set_runtime_dir(self.runtime_dir)
        challenge._cached_benchmark = bm
        challenge._source_dir = src
        return challenge

    def _recover_running_instances(self) -> None:
        """On startup, recover instances that DB says are running, clean stale ones."""
        from benchmark_platform.db import get_running_instances, delete_instance, get_all_instances
        for record in get_all_instances():
            if record["status"] == "starting":
                runtime_path = Path(record["runtime_path"])
                if runtime_path.exists():
                    shutil.rmtree(runtime_path, ignore_errors=True)
                delete_instance(record["id"])

        for record in get_running_instances():
            benchmark_id = record["benchmark_id"]
            team_id = record["team_id"]
            challenge_code = record["challenge_code"]
            runtime_path = Path(record["runtime_path"])

            if not runtime_path.exists() or not self._is_docker_running(runtime_path):
                self._cleanup_stale_record(record)
                continue

            self._instance_status[challenge_code] = "running"
            if team_id:
                self._team_instances[(benchmark_id, team_id)] = challenge_code
            else:
                self._team_instances[(benchmark_id, "__shared__")] = challenge_code

            logger.info("recovered running instance",
                        benchmark_id=benchmark_id, team_id=team_id,
                        challenge_code=challenge_code)

    @classmethod
    def _inject_windows_iso(cls, compose_path: Path, iso_path: str) -> None:
        """Append ISO bind mount to dockur services in the compose file."""
        with open(compose_path) as f:
            data = yaml.safe_load(f)

        injected = False
        for svc_name, svc in data.get("services", {}).items():
            image = svc.get("image", "")
            if "dockur" in image.lower():
                volumes = svc.setdefault("volumes", [])
                mount = f"{iso_path}:/storage/custom.iso:ro"
                if mount not in volumes:
                    volumes.append(mount)
                    injected = True

        with open(compose_path, 'w') as f:
            yaml.dump(data, f)

        logger.info("inject_windows_iso", compose_path=str(compose_path),
                    iso_path=iso_path, injected=injected)

    @classmethod
    def _inject_oem_flags(cls, runtime_path: Path) -> None:
        """Write dynamic flags into OEM/flags.env so Windows VM can read them."""
        import dotenv
        env_path = runtime_path / '.env'
        if not env_path.exists():
            return
        env_vars = dotenv.dotenv_values(env_path)
        oem_dirs = list(runtime_path.glob('src/*/oem'))
        if not oem_dirs:
            oem_dirs = list(runtime_path.glob('*/oem'))
        for oem_dir in oem_dirs:
            flags_file = oem_dir / 'flags.env'
            lines = []
            for k, v in env_vars.items():
                if k.upper().startswith('FLAG'):
                    lines.append(f"{k}={v}")
            if lines:
                flags_file.write_text('\n'.join(lines) + '\n', encoding='utf-8')
                logger.info("inject_oem_flags", path=str(flags_file), count=len(lines))

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
                svc.pop('container_name', None)
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

            _level_map = {1: Difficulty.EASY, 2: Difficulty.MEDIUM, 3: Difficulty.HARD, 4: Difficulty.AD}
            if bm.level not in _level_map:
                raise ValueError(f"Unknown level {bm.level!r} in benchmark {benchmark_id!r}")

            import platform as _platform
            host_is_arm = _platform.machine() in ('arm64', 'aarch64')
            is_emulated = host_is_arm and any(
                svc.get('platform', '').endswith('amd64')
                for svc in data.get('services', {}).values()
            )

            is_unsupported = False
            unsupported_reason = ""
            if bm.requires:
                if bm.requires.arch == "x86_64" and host_is_arm:
                    is_unsupported = True
                    unsupported_reason = "需要 x86_64 架构"
                elif bm.requires.arch == "aarch64" and not host_is_arm:
                    is_unsupported = True
                    unsupported_reason = "需要 ARM64 架构"
                if bm.requires.kvm and not Path('/dev/kvm').exists():
                    is_unsupported = True
                    unsupported_reason = "需要 KVM 虚拟化支持 (/dev/kvm)"
                if bm.requires.arch == "x86_64" and host_is_arm and bm.requires.kvm:
                    unsupported_reason = "需要 x86_64 架构 + KVM 虚拟化"

            requires_win_iso = self._detect_requires_windows_iso(data)

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
                unsupported=is_unsupported,
                unsupported_reason=unsupported_reason,
                requires_windows_iso=requires_win_iso,
            )
            challenge.set_benchmark_id(benchmark_id)
            challenge.set_runtime_dir(self.runtime_dir)
            return challenge
        except Exception:
            if path.exists():
                shutil.rmtree(path)
            raise

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

    def _cleanup_stale_record(self, record: dict) -> None:
        """Docker is dead but DB says running -- clean up."""
        runtime_path = Path(record["runtime_path"])
        if runtime_path.exists():
            try:
                subprocess.run(
                    ['docker', 'compose', 'down', '-v', '--remove-orphans'],
                    cwd=runtime_path, capture_output=True, text=True, timeout=30,
                )
            except Exception:
                pass
            shutil.rmtree(runtime_path, ignore_errors=True)
        from benchmark_platform.db import update_instance_status_by_team
        update_instance_status_by_team(record["benchmark_id"], record.get("team_id"), "stopped")
        logger.info("cleaned stale instance",
                    benchmark_id=record["benchmark_id"],
                    team_id=record.get("team_id"),
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
            for team_dir in entry.iterdir():
                if not team_dir.is_dir():
                    continue
                for instance_dir in team_dir.iterdir():
                    if not instance_dir.is_dir():
                        continue
                    try:
                        subprocess.run(
                            ['docker', 'compose', 'down', '-v', '--remove-orphans'],
                            cwd=instance_dir, capture_output=True, text=True, timeout=30,
                        )
                    except Exception:
                        pass
            shutil.rmtree(entry, ignore_errors=True)
        self._prune_orphan_networks()

    def _prune_orphan_networks(self) -> None:
        """Remove dangling Docker networks that are no longer attached to containers."""
        try:
            res = subprocess.run(
                ['docker', 'network', 'prune', '-f'],
                capture_output=True, text=True, timeout=30,
            )
            if res.stdout.strip():
                logger.info("pruned orphan docker networks", output=res.stdout.strip()[:200])
        except Exception as e:
            logger.warning("failed to prune docker networks", error=str(e))

    def _prune_orphan_volumes(self) -> None:
        """Remove dangling Docker volumes not referenced by any container."""
        try:
            res = subprocess.run(
                ['docker', 'volume', 'prune', '-f'],
                capture_output=True, text=True, timeout=60,
            )
            if res.stdout.strip():
                logger.info("pruned orphan docker volumes", output=res.stdout.strip()[:200])
        except Exception as e:
            logger.warning("failed to prune docker volumes", error=str(e))

    def start_challenge_instance(self, challenge_code: str, team_id: str | None = None) -> list[str] | None:
        """Start docker containers for one challenge (per-team isolation).

        For AD challenges, uses a shared instance.
        For other challenges, creates a per-team instance.
        Returns entrypoint list, or None if starting asynchronously (caller gets 202).
        """
        challenge = self._find_by_code(challenge_code)
        if challenge.unsupported:
            raise RuntimeError(f"无法启动: {challenge.unsupported_reason}")
        benchmark_id = challenge.get_benchmark_id()

        # AD challenges use shared instance
        if challenge.difficulty == Difficulty.AD:
            return self._start_shared_instance(challenge)

        # If no team_id provided, fall back to legacy behavior
        if not team_id:
            team_id = "__legacy__"

        # Concurrent limit check
        from benchmark_platform.db import get_team_running_count
        running_count = get_team_running_count(team_id)
        if running_count >= self.max_instances_per_team:
            raise RuntimeError(f"已达到最大同时运行实例数 ({self.max_instances_per_team})，请先停止其他赛题")

        # Check existing instance for this team+challenge
        existing_code = self._team_instances.get((benchmark_id, team_id))
        if existing_code:
            status = self._instance_status.get(existing_code, "stopped")
            if status in ("running", "unhealthy"):
                ports = self._get_instance_ports(benchmark_id, team_id)
                return [f"{self.public_accessible_host}:{p}" for p in ports]
            if status == "starting":
                return None

        # Clean up old non-running instance if exists
        from benchmark_platform.db import get_instance_by_benchmark_and_team, delete_instance
        record = get_instance_by_benchmark_and_team(benchmark_id, team_id)
        if record and record["status"] not in ("running", "unhealthy"):
            old_runtime = Path(record["runtime_path"])
            if old_runtime.exists():
                shutil.rmtree(old_runtime, ignore_errors=True)
            delete_instance(record["id"])

        # Create new per-team instance
        src_folder = self._find_source_folder(benchmark_id)
        instance_code = str(uuid.uuid4())
        runtime_path = self._get_runtime_path_for_instance(benchmark_id, instance_code, team_id)
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        src = src_folder / benchmark_id
        shutil.copytree(src, runtime_path)

        # Inject unique flags for this team
        self._inject_dynamic_flags(runtime_path)

        # Remap ports and strip container_name to avoid conflicts
        compose_path = runtime_path / 'docker-compose.yml'
        with open(compose_path) as f:
            data = yaml.safe_load(f)

        allocated_ports = []
        for svc_name, svc in data.get('services', {}).items():
            svc.pop('container_name', None)
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

        # Handle Windows ISO
        if challenge.requires_windows_iso:
            from benchmark_platform.db import get_setting
            iso_path = get_setting("win2022_iso_path", "")
            if not iso_path:
                shutil.rmtree(runtime_path, ignore_errors=True)
                raise RuntimeError("请先在系统设置中配置 Windows Server 2022 ISO 路径")
            if not Path(iso_path).is_file():
                shutil.rmtree(runtime_path, ignore_errors=True)
                raise RuntimeError(f"Windows ISO 文件不存在: {iso_path}")
            self._inject_windows_iso(compose_path, iso_path)
            self._inject_oem_flags(runtime_path)

        # Register instance
        self._team_instances[(benchmark_id, team_id)] = instance_code
        self._instance_status[instance_code] = "starting"

        upsert_instance(
            instance_id=str(uuid.uuid4()),
            benchmark_id=benchmark_id,
            challenge_code=instance_code,
            runtime_path=str(runtime_path),
            ports=allocated_ports,
            status="starting",
            team_id=team_id,
        )

        # Start compose
        if challenge.requires_windows_iso:
            threading.Thread(
                target=self._async_team_compose_start,
                args=(challenge, benchmark_id, instance_code, team_id, allocated_ports),
                daemon=True,
            ).start()
            return None

        try:
            self._compose_at_path(runtime_path, 'up', '-d')
        except Exception:
            self._instance_status[instance_code] = "stopped"
            from benchmark_platform.db import update_instance_status_by_team
            update_instance_status_by_team(benchmark_id, team_id, "stopped")
            raise

        self._instance_status[instance_code] = "running"
        self._finalize_team_start(challenge, benchmark_id, instance_code, team_id, allocated_ports)
        return [f"{self.public_accessible_host}:{p}" for p in allocated_ports]

    def _start_shared_instance(self, challenge: Challenge) -> list[str] | None:
        """Start a shared instance for AD challenges (no per-team isolation)."""
        benchmark_id = challenge.get_benchmark_id()

        # Check existing shared instance
        existing_code = self._team_instances.get((benchmark_id, "__shared__"))
        if existing_code:
            status = self._instance_status.get(existing_code, "stopped")
            if status in ("running", "unhealthy"):
                ports = self._get_instance_ports(benchmark_id, None)
                return [f"{self.public_accessible_host}:{p}" for p in ports]
            if status == "starting":
                return None

        # Clean up old stopped shared instance if exists
        from benchmark_platform.db import get_instance_by_benchmark_and_team, delete_instance
        record = get_instance_by_benchmark_and_team(benchmark_id, None)
        if record and record["status"] not in ("running", "unhealthy"):
            old_runtime = Path(record["runtime_path"])
            if old_runtime.exists():
                shutil.rmtree(old_runtime, ignore_errors=True)
            delete_instance(record["id"])

        # Create new shared instance
        src_folder = self._find_source_folder(benchmark_id)
        instance_code = str(uuid.uuid4())
        runtime_path = self._get_runtime_path_for_instance(benchmark_id, instance_code, "shared")
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        src = src_folder / benchmark_id
        shutil.copytree(src, runtime_path)

        # Inject unique flags
        self._inject_dynamic_flags(runtime_path)

        # Remap ports and strip container_name to avoid conflicts
        compose_path = runtime_path / 'docker-compose.yml'
        with open(compose_path) as f:
            data = yaml.safe_load(f)

        allocated_ports = []
        for svc_name, svc in data.get('services', {}).items():
            svc.pop('container_name', None)
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

        # Handle Windows ISO
        if challenge.requires_windows_iso:
            from benchmark_platform.db import get_setting
            iso_path = get_setting("win2022_iso_path", "")
            if not iso_path:
                shutil.rmtree(runtime_path, ignore_errors=True)
                raise RuntimeError("请先在系统设置中配置 Windows Server 2022 ISO 路径")
            if not Path(iso_path).is_file():
                shutil.rmtree(runtime_path, ignore_errors=True)
                raise RuntimeError(f"Windows ISO 文件不存在: {iso_path}")
            self._inject_windows_iso(compose_path, iso_path)
            self._inject_oem_flags(runtime_path)

        # Register shared instance
        self._team_instances[(benchmark_id, "__shared__")] = instance_code
        self._instance_status[instance_code] = "starting"

        upsert_instance(
            instance_id=str(uuid.uuid4()),
            benchmark_id=benchmark_id,
            challenge_code=instance_code,
            runtime_path=str(runtime_path),
            ports=allocated_ports,
            status="starting",
            team_id=None,
        )

        # Start compose
        if challenge.requires_windows_iso:
            threading.Thread(
                target=self._async_team_compose_start,
                args=(challenge, benchmark_id, instance_code, None, allocated_ports),
                daemon=True,
            ).start()
            return None

        try:
            self._compose_at_path(runtime_path, 'up', '-d')
        except Exception:
            self._instance_status[instance_code] = "stopped"
            from benchmark_platform.db import update_instance_status_by_team
            update_instance_status_by_team(benchmark_id, None, "stopped")
            raise

        self._instance_status[instance_code] = "running"
        self._finalize_team_start(challenge, benchmark_id, instance_code, None, allocated_ports)
        return [f"{self.public_accessible_host}:{p}" for p in allocated_ports]

    def _async_team_compose_start(self, challenge: Challenge, benchmark_id: str,
                                   instance_code: str, team_id: str | None,
                                   ports: list[int]) -> None:
        """Background thread for per-team compose up (AD/Windows)."""
        from benchmark_platform.db import update_instance_status_by_team
        runtime_path = self._get_runtime_path_for_instance(benchmark_id, instance_code, team_id or "shared")
        try:
            self._compose_at_path(runtime_path, 'up', '-d', timeout=self._COMPOSE_TIMEOUT_WINDOWS)
            self._instance_status[instance_code] = "running"
            self._finalize_team_start(challenge, benchmark_id, instance_code, team_id, ports)
        except Exception as e:
            logger.error("async compose start failed", benchmark_id=benchmark_id, team_id=team_id, error=str(e))
            self._instance_logs.setdefault(benchmark_id, []).append(f"ERROR: {e}")
            self._instance_status[instance_code] = "stopped"
            update_instance_status_by_team(benchmark_id, team_id, "stopped")

    def _finalize_team_start(self, challenge: Challenge, benchmark_id: str,
                              instance_code: str, team_id: str | None,
                              ports: list[int]) -> None:
        """Record per-team instance as running in DB after successful compose up."""
        from benchmark_platform.db import update_instance_status_by_team
        timeout_config = get_instance_timeout_config()
        level = self.get_level_for_challenge(challenge)
        timeout_secs = timeout_config.get(level, 7200)
        now = datetime.now(timezone.utc)
        started_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        expires_at = (now + timedelta(seconds=timeout_secs)).strftime("%Y-%m-%dT%H:%M:%SZ")
        update_instance_status_by_team(benchmark_id, team_id, "running",
                                       started_at=started_at, expires_at=expires_at)

    def stop_challenge_instance(self, challenge_code: str, team_id: str | None = None) -> None:
        """Stop docker containers for one challenge (per-team isolation).

        If team_id is provided, verifies ownership before stopping.
        """
        instance_code, benchmark_id, owner_team_id = self._resolve_instance(challenge_code, team_id)
        if team_id and owner_team_id and owner_team_id != team_id:
            raise PermissionError("无权停止其他队伍的实例")
        self._instance_status[instance_code] = "stopping"
        runtime_path = self._get_runtime_path_for_instance(benchmark_id, instance_code, owner_team_id or "shared")
        if runtime_path.exists():
            self._compose_at_path(runtime_path, 'down', '-v', '--remove-orphans')
        self._instance_status[instance_code] = "stopped"
        from benchmark_platform.db import update_instance_status_by_team
        update_instance_status_by_team(benchmark_id, owner_team_id, "stopped")

    def _resolve_instance(self, challenge_code: str, team_id: str | None) -> tuple[str, str, str | None]:
        """Find (instance_code, benchmark_id, owner_team_id) for a challenge/team pair."""
        # If challenge_code is a benchmark_id and team_id is given
        if team_id:
            existing = self._team_instances.get((challenge_code, team_id))
            if existing:
                return existing, challenge_code, team_id
        # Search all team_instances for this code
        for (bid, tid), code in self._team_instances.items():
            if code == challenge_code:
                real_team = tid if tid != "__shared__" else None
                return code, bid, real_team
        # Fallback: shared
        existing = self._team_instances.get((challenge_code, "__shared__"))
        if existing:
            return existing, challenge_code, None
        raise KeyError(f"Instance {challenge_code!r} not found")

    def _get_instance_ports(self, benchmark_id: str, team_id: str | None) -> list[int]:
        """Get ports from DB for a benchmark+team instance."""
        from benchmark_platform.db import get_instance_by_benchmark_and_team
        record = get_instance_by_benchmark_and_team(benchmark_id, team_id)
        if record:
            return json.loads(record["ports"])
        return []

    def _get_runtime_path_for_instance(self, benchmark_id: str, instance_code: str, team_id: str | None) -> Path:
        """Compute the runtime path for a per-team instance."""
        dir_name = team_id if team_id else "shared"
        return Challenge.get_base_path(benchmark_id, instance_code, self.runtime_dir, team_id=dir_name)

    def _compose_at_path(self, runtime_path: Path, *args, timeout: int | None = None) -> None:
        """Run docker compose at a specific runtime path."""
        if not (runtime_path / 'docker-compose.yml').exists():
            return
        compose_timeout = timeout or self._COMPOSE_TIMEOUT
        cmd = ['docker', 'compose'] + list(args)
        logger.info("docker compose", action="compose", cmd=" ".join(cmd), cwd=str(runtime_path))

        # Extract benchmark_id from path for logging
        # Path structure: runtime/<benchmark_id>/<team_id>/<instance_code>
        # or legacy: runtime/<benchmark_id>/<instance_code>
        parts = runtime_path.parts
        runtime_idx = None
        for i, part in enumerate(parts):
            if part == self.runtime_dir.name:
                runtime_idx = i
                break
        if runtime_idx is not None and runtime_idx + 1 < len(parts):
            benchmark_id = parts[runtime_idx + 1]
        else:
            benchmark_id = runtime_path.parent.parent.name if len(parts) > 3 else runtime_path.parent.name

        self._instance_logs[benchmark_id] = []
        logs = self._instance_logs[benchmark_id]

        start_time = time.monotonic()
        proc = subprocess.Popen(cmd, cwd=runtime_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
        try:
            while True:
                line = proc.stdout.readline()
                if not line and proc.poll() is not None:
                    break
                if line:
                    logs.append(line.rstrip('\n'))
                    if len(logs) > 500:
                        del logs[:len(logs) - 500]
                if time.monotonic() - start_time > compose_timeout:
                    proc.terminate()
                    proc.wait(timeout=10)
                    raise RuntimeError(f"Docker compose timed out after {compose_timeout}s")
        except RuntimeError:
            raise
        except Exception:
            proc.kill()
            raise

        if proc.returncode != 0:
            output = '\n'.join(logs[-20:])
            if 'could not find an available, non-overlapping IPv4 address pool' in output:
                self._prune_orphan_networks()
                # Retry once
                self._instance_logs[benchmark_id] = []
                logs = self._instance_logs[benchmark_id]
                start_time = time.monotonic()
                proc = subprocess.Popen(cmd, cwd=runtime_path, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
                while True:
                    line = proc.stdout.readline()
                    if not line and proc.poll() is not None:
                        break
                    if line:
                        logs.append(line.rstrip('\n'))
                        if len(logs) > 500:
                            del logs[:len(logs) - 500]
                    if time.monotonic() - start_time > compose_timeout:
                        proc.terminate()
                        proc.wait(timeout=10)
                        raise RuntimeError(f"Docker compose timed out after {compose_timeout}s (retry)")
                if proc.returncode == 0:
                    return
            raise RuntimeError(f"Docker compose failed: {output[:500]}")

    def get_team_instance_status(self, benchmark_id: str, team_id: str) -> str:
        """Get status for a team's challenge instance."""
        challenge = self._find_by_code(benchmark_id)
        if challenge.difficulty == Difficulty.AD:
            code = self._team_instances.get((benchmark_id, "__shared__"))
        else:
            code = self._team_instances.get((benchmark_id, team_id))
        if not code:
            return "stopped"
        status = self._instance_status.get(code, "stopped")
        if status != "running":
            return status
        runtime_path = self._get_runtime_path_for_instance(
            benchmark_id, code, team_id if challenge.difficulty != Difficulty.AD else "shared"
        )
        return self._check_health_at_path(runtime_path)

    def get_team_instance_ports(self, benchmark_id: str, team_id: str) -> list[int]:
        """Get ports for a team's challenge instance."""
        challenge = self._find_by_code(benchmark_id)
        if challenge.difficulty == Difficulty.AD:
            return self._get_instance_ports(benchmark_id, None)
        return self._get_instance_ports(benchmark_id, team_id)

    def get_team_instance_timestamps(self, benchmark_id: str, team_id: str) -> tuple[str | None, str | None]:
        """Get (started_at, expires_at) timestamps for a team's challenge instance."""
        from benchmark_platform.db import get_instance_by_benchmark_and_team
        challenge = self._find_by_code(benchmark_id)
        lookup_team = team_id if challenge.difficulty != Difficulty.AD else None
        record = get_instance_by_benchmark_and_team(benchmark_id, lookup_team)
        if record and record["status"] == "running":
            return record["started_at"], record["expires_at"]
        return None, None

    def get_team_instance_flags(self, benchmark_id: str, team_id: str) -> dict[str, str]:
        """Read flags from a team's runtime .env file."""
        import dotenv
        challenge = self._find_by_code(benchmark_id)
        if challenge.difficulty == Difficulty.AD:
            code = self._team_instances.get((benchmark_id, "__shared__"))
            lookup_team = "shared"
        else:
            code = self._team_instances.get((benchmark_id, team_id))
            lookup_team = team_id
        if not code:
            return {}
        runtime_path = self._get_runtime_path_for_instance(benchmark_id, code, lookup_team)
        if not runtime_path.exists():
            return {}
        env_path = runtime_path / '.env'
        if not env_path.exists():
            return {}
        data = dotenv.dotenv_values(env_path)
        data_upper = {k.upper(): v for k, v in data.items()}
        if challenge.flag_states:
            result = {}
            for i, fs in enumerate(challenge.flag_states):
                key_by_id = f"FLAG_{fs.id}".upper()
                key_by_idx = f"FLAG{i + 1}"
                if key_by_id in data_upper:
                    result[fs.id] = str(data_upper[key_by_id])
                elif key_by_idx in data_upper:
                    result[fs.id] = str(data_upper[key_by_idx])
                elif "FLAG" in data_upper and len(challenge.flag_states) == 1:
                    result[fs.id] = str(data_upper["FLAG"])
            return result
        if 'FLAG' not in data_upper:
            return {}
        return {"default": str(data_upper['FLAG'])}

    def _check_health_at_path(self, runtime_path: Path) -> str:
        """Check container health at a specific runtime path."""
        if not runtime_path.exists() or not (runtime_path / 'docker-compose.yml').exists():
            return "running"
        try:
            res = subprocess.run(
                ['docker', 'compose', 'ps', '--format', 'json'],
                cwd=runtime_path, capture_output=True, text=True, timeout=5,
            )
            if res.returncode != 0:
                return "running"
            for line in res.stdout.strip().splitlines():
                info = json.loads(line)
                if info.get("Health") == "unhealthy":
                    return "unhealthy"
        except Exception:
            pass
        return "running"

    def stop_all_instances(self, team_id: str | None = None) -> int:
        """Stop all running instances, optionally filtered by team_id."""
        stopped = 0
        for (bid, tid), code in list(self._team_instances.items()):
            if team_id and tid != team_id:
                continue
            if self._instance_status.get(code) not in ("running", "unhealthy", "starting"):
                continue
            real_team = tid if tid != "__shared__" else None
            try:
                runtime_path = self._get_runtime_path_for_instance(bid, code, tid if tid != "__shared__" else "shared")
                if runtime_path.exists():
                    self._compose_at_path(runtime_path, 'down', '-v', '--remove-orphans')
                self._instance_status[code] = "stopped"
                from benchmark_platform.db import update_instance_status_by_team
                update_instance_status_by_team(bid, real_team, "stopped")
                stopped += 1
            except Exception as e:
                logger.error("stop_all failed for instance", benchmark_id=bid, team_id=tid, error=str(e))
        return stopped

    def get_instance_status(self, challenge_code: str) -> str:
        """Legacy: get status for a challenge_code (checks all teams)."""
        # Check direct match in _instance_status
        if challenge_code in self._instance_status:
            return self._instance_status[challenge_code]
        # Check if it's a benchmark_id with any running instance
        for (bid, tid), code in self._team_instances.items():
            if bid == challenge_code:
                status = self._instance_status.get(code, "stopped")
                if status in ("running", "unhealthy", "starting"):
                    return status
        return "stopped"

    def get_instance_timestamps(self, challenge_code: str) -> tuple[str | None, str | None]:
        """Return (started_at, expires_at) for a challenge instance."""
        challenge = self._find_by_code(challenge_code)
        record = get_instance_by_benchmark_id(challenge.get_benchmark_id())
        if record and record["status"] == "running":
            return record["started_at"], record["expires_at"]
        return None, None

    def _find_source_folder(self, benchmark_id: str) -> Path:
        """Find the source folder for a benchmark_id from benchmark_folders."""
        for folder in self.benchmark_folders:
            if (folder / benchmark_id).is_dir():
                return folder
            for entry in folder.iterdir():
                if entry.is_dir() and not entry.name.startswith('.'):
                    if (entry / benchmark_id / 'benchmark.json').exists():
                        return entry
        raise FileNotFoundError(f"Source folder for {benchmark_id} not found")

    def _find_by_code(self, challenge_code: str) -> Challenge:
        """Find challenge metadata by benchmark_id or challenge_code."""
        for c in self.challenges:
            if c.challenge_code == challenge_code:
                return c
            if c.get_benchmark_id() == challenge_code:
                return c
        raise KeyError(f"Challenge {challenge_code!r} not found")

    _FLAG_RE = re.compile(r'^(FLAG(?:_\w+|[0-9]*))\s*=\s*["\']?([^"\'\n]+)["\']?', re.MULTILINE)
    _TEXT_EXTENSIONS = {
        '.py', '.js', '.ts', '.go', '.rb', '.php', '.java', '.sh', '.bash',
        '.sql', '.html', '.htm', '.xml', '.json', '.yaml', '.yml', '.toml',
        '.env', '.txt', '.md', '.cfg', '.ini', '.conf', '.tpl', '.tmpl',
        '.jsx', '.tsx', '.vue', '.css', '.csv',
        '.ldif',
    }
    _TEXT_FILENAMES = {
        'Dockerfile', 'Makefile', 'Procfile', 'Gemfile', 'Rakefile',
        'Vagrantfile', 'Brewfile', 'flag',
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

    _COMPOSE_TIMEOUT = 300  # 5 minutes
    _COMPOSE_TIMEOUT_WINDOWS = 1800  # 30 minutes for Windows ISO challenges

    def get_instance_logs(self, benchmark_id: str, offset: int = 0) -> tuple[list[str], int]:
        """Return (log_lines_from_offset, total_line_count) for a benchmark."""
        logs = self._instance_logs.get(benchmark_id, [])
        total = len(logs)
        if offset >= total:
            return [], total
        return logs[offset:], total

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
        level_map = {Difficulty.EASY: 1, Difficulty.MEDIUM: 2, Difficulty.HARD: 3, Difficulty.AD: 4}
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
