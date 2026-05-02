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
from benchmark_platform.base import TargetInfo
from benchmark_platform.models.benchmark import Benchmark
from benchmark_platform.utils.logger import get_logger

logger = get_logger(Path('logs/competition-platform-server-logs.jsonl'))
console = Console()


class ChallengeManager:
    def __init__(self, xbow_benchmark_folder: Path, benchmark_ids: list[str], public_accessible_host: str) -> None:
        self.xbow_benchmark_folder = xbow_benchmark_folder
        self.benchmark_ids = benchmark_ids
        self.public_accessible_host = public_accessible_host
        self.challenges: list[Challenge] = []

    def __enter__(self) -> 'ChallengeManager':
        self.start()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb) -> None:
        self.stop()

    def start(self) -> 'ChallengeManager':
        # Create challenges
        for benchmark_id in self.benchmark_ids:
            try:
                self.challenges.append(self._create_challenge(benchmark_id))
            except Exception as e:
                logger.error(
                    'failed to create challenge',
                    benchmark_id=benchmark_id, error=str(e),
                )
                raise

        logger.info('starting challenges', count=len(self.challenges))

        # Start challenges
        started = []
        errors = []
        with ThreadPoolExecutor() as executor:
            futures = {
                executor.submit(self._compose, c.get_benchmark_id(), c.challenge_code, 'up', '-d'): c
                for c in self.challenges
            }
            for f in futures:
                c = futures[f]
                try:
                    f.result()
                    started.append(c)
                except Exception as e:
                    errors.append((c, e))
                    logger.error(
                        'failed to start',
                        code=c.challenge_code, error=str(e),
                    )

        if errors:
            self._cleanup(started)
            raise RuntimeError(
                f"Failed to start {len(errors)} challenges: {[str(e) for _, e in errors]}",
            )

        logger.info('challenges started', count=len(self.challenges))
        return self

    def stop(self) -> None:
        self._cleanup(self.challenges)
        self.challenges.clear()

    def _cleanup(self, challenges: list[Challenge]) -> None:
        if not challenges:
            return
        logger.info('cleaning up challenges', count=len(challenges))

        with ThreadPoolExecutor() as executor:
            # Stop containers
            list(
                executor.map(
                    lambda c: self._compose(
                        c.get_benchmark_id(), c.challenge_code, 'down',
                    ), challenges,
                ),
            )
            # Remove directories

            list(
                executor.map(
                    lambda c: self._compose(
                        c.get_benchmark_id(), c.challenge_code, 'down',
                    ), challenges,
                ),
            )
            # Remove directories

            def remove_dir(c):
                shutil.rmtree(
                    Challenge.get_base_path(c.get_benchmark_id(), c.challenge_code),
                    ignore_errors=True,
                )
            list(executor.map(remove_dir, challenges))

    def _create_challenge(self, benchmark_id: str) -> Challenge:
        challenge_id = str(uuid.uuid4())
        path = Challenge.get_base_path(benchmark_id, challenge_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        src = self.xbow_benchmark_folder / benchmark_id

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

            # Load metadata
            meta = json.loads((path / 'benchmark.json').read_text())
            meta['id'] = benchmark_id
            bm = Benchmark.model_validate(meta)

            challenge = Challenge(
                challenge_code=challenge_id,
                difficulty={
                    1: Difficulty.EASY, 2: Difficulty.MEDIUM,
                    3: Difficulty.HARD,
                }[bm.level],
                points=bm.points,
                hint_viewed=False,
                solved=False,
                target_info=TargetInfo(
                    ip=self.public_accessible_host, port=allocated_ports,
                ),
            )
            challenge.set_benchmark_id(benchmark_id)
            return challenge
        except Exception:
            if path.exists():
                shutil.rmtree(path)
            raise

    def _compose(self, benchmark_id: str, code: str, *args) -> None:
        path = Challenge.get_base_path(benchmark_id, code)
        if not (path / 'docker-compose.yml').exists():
            return

        res = subprocess.run(
            ['docker', 'compose'] + list(args),
            cwd=path, capture_output=True, text=True,
        )
        if res.returncode != 0:
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
        table.add_column('URL', style='blue')

        for c in self.challenges:
            for p in c.target_info.port:
                table.add_row(
                    c.get_benchmark_id(), c.challenge_code,
                    c.target_info.ip, str(p),
                    f'http://{c.target_info.ip}:{p}',
                )
        console.print('\n', table, '\n')
