from __future__ import annotations

import json
from enum import Enum
from pathlib import Path

import dotenv
from pydantic import BaseModel
from pydantic import PrivateAttr

from benchmark_platform.models.benchmark import Benchmark


class TargetInfo(BaseModel):
    ip: str
    port: list[int]


class Difficulty(str, Enum):
    EASY = 'easy'
    MEDIUM = 'medium'
    HARD = 'hard'


class FlagState(BaseModel):
    id: str
    route: str = "/"
    description: str = ""
    solved: bool = False
    solved_at: str | None = None


class Challenge(BaseModel):
    challenge_code: str
    difficulty: Difficulty
    points: int
    hint_viewed: bool
    solved: bool
    target_info: TargetInfo
    flag_states: list[FlagState] = []
    emulated: bool = False
    unsupported: bool = False
    unsupported_reason: str = ""
    requires_windows_iso: bool = False
    _benchmark_id: str | None = PrivateAttr(default=None)
    _runtime_dir: Path | None = PrivateAttr(default=None)

    def set_benchmark_id(self, benchmark_id: str) -> None:
        """Store the benchmark id without exposing it via API responses."""
        self._benchmark_id = benchmark_id

    def set_runtime_dir(self, runtime_dir: Path) -> None:
        self._runtime_dir = runtime_dir

    def get_benchmark_id(self) -> str:
        """Return associated XBEN benchmark id for internal use."""
        if not self._benchmark_id:
            raise ValueError(
                f'Benchmark id not set for challenge {self.challenge_code}',
            )
        return self._benchmark_id

    @staticmethod
    def get_base_path(benchmark_id: str, challenge_code: str, runtime_dir: Path | None = None) -> Path:
        base = runtime_dir if runtime_dir else Path('runtime')
        return base / benchmark_id / challenge_code

    def _get_path(self) -> Path:
        return Challenge.get_base_path(self.get_benchmark_id(), self.challenge_code, self._runtime_dir)

    def get_expected_answers(self) -> dict[str, str]:
        """Return {flag_id: flag_value} for all flags."""
        env_path = self._get_path() / '.env'
        data = dotenv.dotenv_values(env_path)
        data_upper = {k.upper(): v for k, v in data.items()}
        if self.flag_states:
            result = {}
            for i, fs in enumerate(self.flag_states):
                key_by_id = f"FLAG_{fs.id}".upper()
                key_by_idx = f"FLAG{i + 1}"
                if key_by_id in data_upper:
                    result[fs.id] = str(data_upper[key_by_id])
                elif key_by_idx in data_upper:
                    result[fs.id] = str(data_upper[key_by_idx])
                elif "FLAG" in data_upper and len(self.flag_states) == 1:
                    result[fs.id] = str(data_upper["FLAG"])
            return result
        if 'FLAG' not in data_upper:
            raise ValueError(f"FLAG not found in {env_path}")
        return {"default": str(data_upper['FLAG'])}

    def get_expected_answer(self) -> str:
        """Legacy single-flag compat."""
        answers = self.get_expected_answers()
        return next(iter(answers.values()))

    @property
    def flag_count(self) -> int:
        return max(1, len(self.flag_states))

    @property
    def solved_count(self) -> int:
        if not self.flag_states:
            return 1 if self.solved else 0
        return sum(1 for f in self.flag_states if f.solved)

    def get_hint(self) -> str:
        base_path = self._get_path()
        metadata_path = base_path / 'benchmark.json'
        with open(metadata_path, encoding='utf-8') as f:
            metadata = json.load(f)

        if self.flag_states:
            yaml_path = base_path / 'benchmark.yaml'
            if yaml_path.exists():
                import yaml
                with open(yaml_path, encoding='utf-8') as yf:
                    bm = yaml.safe_load(yf)
                unsolved_ids = {fs.id for fs in self.flag_states if not fs.solved}
                hints = []
                for flag_def in bm.get('flags', []):
                    if flag_def['id'] in unsolved_ids and flag_def.get('hint'):
                        hints.append(f"{flag_def.get('route','/')}: {flag_def['hint']}")
                if hints:
                    return "Hints for unsolved routes:\n" + "\n".join(hints)

        if metadata.get('hint'):
            return metadata['hint']
        return metadata.get('description', '')

    def get_benchmark(self) -> Benchmark:
        metadata_path = self._get_path() / 'benchmark.json'
        with open(metadata_path, encoding='utf-8') as f:
            metadata = json.load(f)
            metadata['id'] = self.get_benchmark_id()
            return Benchmark.model_validate(metadata)


class CompetitionStage(str, Enum):
    DEBUG = 'debug'
    COMPETITION = 'competition'


class GetChallengesResponse(BaseModel):
    current_stage: CompetitionStage
    challenges: list[Challenge]


class GetChallengeHintResponse(BaseModel):
    hint_content: str
    penalty_points: int
    first_use: bool


class SubmitAnswerRequest(BaseModel):
    challenge_code: str
    answer: str


class SubmitAnswerResponse(BaseModel):
    correct: bool
    earned_points: int
    is_solved: bool
