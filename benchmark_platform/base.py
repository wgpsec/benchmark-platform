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
    _benchmark_id: str | None = PrivateAttr(default=None)

    def set_benchmark_id(self, benchmark_id: str) -> None:
        """Store the benchmark id without exposing it via API responses."""
        self._benchmark_id = benchmark_id

    def get_benchmark_id(self) -> str:
        """Return associated XBEN benchmark id for internal use."""
        if not self._benchmark_id:
            raise ValueError(
                f'Benchmark id not set for challenge {self.challenge_code}',
            )
        return self._benchmark_id

    @staticmethod
    def get_base_path(benchmark_id: str, challenge_code: str) -> Path:
        return Path('challenges') / benchmark_id / challenge_code

    def get_expected_answers(self) -> dict[str, str]:
        """Return {flag_id: flag_value} for all flags."""
        env_path = Challenge.get_base_path(
            self.get_benchmark_id(), self.challenge_code,
        ) / '.env'
        data = dotenv.dotenv_values(env_path)
        if self.flag_states:
            result = {}
            for i, fs in enumerate(self.flag_states):
                key_by_id = f"FLAG_{fs.id}"
                key_by_idx = f"FLAG{i + 1}"
                if key_by_id in data:
                    result[fs.id] = str(data[key_by_id])
                elif key_by_idx in data:
                    result[fs.id] = str(data[key_by_idx])
                elif "FLAG" in data and len(self.flag_states) == 1:
                    result[fs.id] = str(data["FLAG"])
            return result
        if 'FLAG' not in data:
            raise ValueError(f"FLAG not found in {env_path}")
        return {"default": str(data['FLAG'])}

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
        metadata_path = Challenge.get_base_path(
            self.get_benchmark_id(), self.challenge_code,
        ) / 'benchmark.json'
        with open(metadata_path, encoding='utf-8') as f:
            metadata = json.load(f)
            return metadata.get('description', '')

    def get_benchmark(self) -> Benchmark:
        metadata_path = Challenge.get_base_path(self.get_benchmark_id(), self.challenge_code) / 'benchmark.json'
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
