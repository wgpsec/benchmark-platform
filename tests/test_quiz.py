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
