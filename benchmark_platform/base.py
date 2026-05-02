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


class Challenge(BaseModel):
    challenge_code: str
    difficulty: Difficulty
    points: int
    hint_viewed: bool
    solved: bool
    target_info: TargetInfo
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

    def get_expected_answer(self) -> str:
        env_path = Challenge.get_base_path(
            self.get_benchmark_id(), self.challenge_code,
        ) / '.env'
        data = dotenv.dotenv_values(env_path)
        if 'FLAG' not in data:
            raise ValueError(f"FLAG not found in {env_path}")
        return str(data['FLAG'])

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
