"""MCQ quiz engine: load, serve, and evaluate knowledge benchmarks."""
from __future__ import annotations

import json
from pathlib import Path

from benchmark_platform.models.benchmark import Benchmark, WinCondition


class QuizStore:
    def __init__(self, quiz_dirs: list[Path]) -> None:
        self.benchmarks: list[Benchmark] = []
        self._by_id: dict[str, Benchmark] = {}
        for d in quiz_dirs:
            if d.exists():
                self._load_dir(d)

    def _load_dir(self, base: Path) -> None:
        for child in sorted(base.iterdir()):
            meta_path = child / "benchmark.json"
            if not meta_path.exists():
                continue
            with open(meta_path, encoding="utf-8") as f:
                data = json.load(f)
            if data.get("win_condition") != "mcq":
                continue
            bm = Benchmark.model_validate(data)
            self.benchmarks.append(bm)
            self._by_id[bm.id] = bm

    def _get(self, benchmark_id: str) -> Benchmark:
        if benchmark_id not in self._by_id:
            raise KeyError(f"Quiz benchmark {benchmark_id} not found")
        return self._by_id[benchmark_id]

    def get_questions(self, benchmark_id: str) -> list[dict]:
        bm = self._get(benchmark_id)
        return [{"id": q.id, "text": q.text, "choices": q.choices} for q in bm.questions]

    def evaluate(self, benchmark_id: str, answers: dict[str, int]) -> dict:
        bm = self._get(benchmark_id)
        answer_map = {q.id: q.answer for q in bm.questions}
        details = []
        correct_count = 0
        for q in bm.questions:
            if q.id not in answers:
                continue
            is_correct = answers[q.id] == answer_map[q.id]
            if is_correct:
                correct_count += 1
            entry = {"id": q.id, "correct": is_correct}
            if not is_correct:
                entry["your_answer"] = answers[q.id]
                entry["correct_answer"] = answer_map[q.id]
            details.append(entry)
        per_question_score = bm.points // len(bm.questions) if bm.questions else 0
        return {
            "correct": correct_count,
            "total": len(details),
            "score": correct_count * per_question_score,
            "max_score": bm.points,
            "details": details,
        }

    def list_benchmarks(self) -> list[dict]:
        return [
            {
                "id": bm.id,
                "name": bm.name,
                "description": bm.description,
                "category": bm.category,
                "question_count": len(bm.questions),
                "points": bm.points,
                "level": bm.level,
                "tags": bm.tags,
            }
            for bm in self.benchmarks
        ]
