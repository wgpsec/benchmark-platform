"""In-memory submission record store with optional JSONL persistence."""
import json
from dataclasses import asdict, dataclass
from pathlib import Path


@dataclass
class SubmissionRecord:
    timestamp: str
    challenge_code: str
    benchmark_id: str
    challenge_name: str
    flag_id: str | None
    flag_value: str
    correct: bool
    points: int


class SubmissionStore:
    def __init__(self, log_path: Path | None = None) -> None:
        self._records: list[SubmissionRecord] = []
        self._log_path = log_path

    def add(self, record: SubmissionRecord) -> None:
        self._records.insert(0, record)
        if self._log_path:
            self._log_path.parent.mkdir(parents=True, exist_ok=True)
            with open(self._log_path, "a", encoding="utf-8") as f:
                f.write(json.dumps(asdict(record), ensure_ascii=False) + "\n")

    def query(
        self,
        correct: bool | None = None,
        limit: int = 50,
        offset: int = 0,
    ) -> list[SubmissionRecord]:
        filtered = self._records
        if correct is not None:
            filtered = [r for r in filtered if r.correct == correct]
        return filtered[offset : offset + limit]

    @property
    def total_count(self) -> int:
        return len(self._records)

    @property
    def correct_count(self) -> int:
        return sum(1 for r in self._records if r.correct)

    @property
    def incorrect_count(self) -> int:
        return sum(1 for r in self._records if not r.correct)
