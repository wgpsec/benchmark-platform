"""Tests for MCQ quiz functionality."""
import pytest


def test_win_condition_has_mcq():
    from benchmark_platform.models.benchmark import WinCondition
    assert WinCondition.MCQ == "mcq"
    assert WinCondition.FLAG == "flag"


def test_question_model_validates():
    from benchmark_platform.models.benchmark import Question
    q = Question(id="q1", text="What is 2+2?", choices=["3", "4", "5", "6"], answer=1)
    assert q.id == "q1"
    assert q.choices[q.answer] == "4"


from pathlib import Path

SAMPLE_QUIZ_DIR = Path(__file__).parent.parent / "quiz" / "sample-quiz"


def test_quiz_store_loads_benchmarks():
    from benchmark_platform.quiz import QuizStore
    store = QuizStore([SAMPLE_QUIZ_DIR.parent])
    assert len(store.benchmarks) == 1
    bm = store.benchmarks[0]
    assert bm.id == "SAMPLE-QUIZ-001"
    assert bm.win_condition == "mcq"
    assert len(bm.questions) == 3


def test_quiz_store_get_questions_strips_answers():
    from benchmark_platform.quiz import QuizStore
    store = QuizStore([SAMPLE_QUIZ_DIR.parent])
    questions = store.get_questions("SAMPLE-QUIZ-001")
    for q in questions:
        assert "answer" not in q


def test_quiz_store_evaluate_answers():
    from benchmark_platform.quiz import QuizStore
    store = QuizStore([SAMPLE_QUIZ_DIR.parent])
    result = store.evaluate("SAMPLE-QUIZ-001", {"q1": 0, "q2": 1, "q3": 0})
    assert result["correct"] == 2
    assert result["total"] == 3
    assert result["details"][0]["correct"] is True
    assert result["details"][2]["correct"] is False
    assert result["details"][2]["correct_answer"] == 1


def test_quiz_store_get_nonexistent_raises():
    from benchmark_platform.quiz import QuizStore
    store = QuizStore([SAMPLE_QUIZ_DIR.parent])
    with pytest.raises(KeyError):
        store.get_questions("NONEXISTENT")
