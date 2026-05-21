"""Tests for quiz API endpoints."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benchmark_platform.db import _set_db_path, init_db, get_or_create_default_team
from benchmark_platform.server import app
from benchmark_platform.quiz import QuizStore
from benchmark_platform.web.auth_middleware import _COOKIE_NAME, create_session_cookie
from benchmark_platform.web.submission_store import SubmissionStore

QUIZ_DIR = Path(__file__).parent.parent / "challenges" / "quiz"


@pytest.fixture(autouse=True)
def setup_db(tmp_path):
    _set_db_path(tmp_path / "test.db")
    init_db()


def _setup_app():
    app.state.manager = None
    app.state.submission_store = SubmissionStore()
    app.state.quiz_store = QuizStore([QUIZ_DIR])


def _auth_client(team_id="default", role="admin", team_name="Default") -> TestClient:
    client = TestClient(app)
    client.cookies.set(_COOKIE_NAME, create_session_cookie(team_id, role, team_name))
    return client


def test_quiz_list_returns_benchmarks():
    _setup_app()
    client = _auth_client()
    r = client.get("/api/v1/quiz")
    assert r.status_code == 200
    data = r.json()
    assert len(data) >= 1
    assert data[0]["id"] == "SAMPLE-QUIZ-001"
    assert data[0]["question_count"] == 3


def test_quiz_get_questions_without_answers():
    _setup_app()
    client = _auth_client()
    r = client.get("/api/v1/quiz/SAMPLE-QUIZ-001")
    assert r.status_code == 200
    data = r.json()
    assert len(data["questions"]) == 3
    for q in data["questions"]:
        assert "answer" not in q
        assert "text" in q
        assert "choices" in q


def test_quiz_submit_scores_correctly():
    _setup_app()
    team = get_or_create_default_team()
    client = _auth_client(team_id=team["id"])
    r = client.post("/api/v1/quiz/SAMPLE-QUIZ-001/submit", json={
        "answers": {"q1": 0, "q2": 1, "q3": 1}
    })
    assert r.status_code == 200
    data = r.json()
    assert data["correct"] == 3
    assert data["total"] == 3


def test_quiz_submit_prevents_resubmission():
    _setup_app()
    team = get_or_create_default_team()
    client = _auth_client(team_id=team["id"])
    # First submit q1 correctly
    client.post("/api/v1/quiz/SAMPLE-QUIZ-001/submit", json={"answers": {"q1": 0}})
    # Try to change q1 answer
    r = client.post("/api/v1/quiz/SAMPLE-QUIZ-001/submit", json={"answers": {"q1": 2}})
    assert r.status_code == 200
    data = r.json()
    q1_detail = next(d for d in data["details"] if d["id"] == "q1")
    assert q1_detail["correct"] is True  # original correct answer preserved


def test_quiz_nonexistent_returns_404():
    _setup_app()
    client = _auth_client()
    r = client.get("/api/v1/quiz/NONEXISTENT")
    assert r.status_code == 404


def test_quiz_web_page_returns_200():
    _setup_app()
    client = _auth_client()
    r = client.get("/web/quiz")
    assert r.status_code == 200
    assert "知识评测" in r.text


def test_quiz_detail_page_returns_200():
    _setup_app()
    client = _auth_client()
    r = client.get("/web/quiz/SAMPLE-QUIZ-001")
    assert r.status_code == 200
    assert "What does CVE stand for?" in r.text
    assert "SAMPLE-QUIZ-001" in r.text


def test_scoreboard_has_tab_navigation():
    _setup_app()
    client = _auth_client()
    r = client.get("/web/scoreboard")
    assert r.status_code == 200
    assert "tab=combined" in r.text
    assert "tab=ctf" in r.text
    assert "tab=mcq" in r.text


def test_scoreboard_mcq_tab():
    _setup_app()
    client = _auth_client()
    r = client.get("/web/scoreboard?tab=mcq")
    assert r.status_code == 200
    assert "MCQ" in r.text


def test_full_quiz_flow():
    """End-to-end: list -> get questions -> submit -> verify score."""
    _setup_app()
    team = get_or_create_default_team()
    client = _auth_client(team_id=team["id"])

    # List
    r = client.get("/api/v1/quiz")
    assert r.status_code == 200
    benchmarks = r.json()
    assert len(benchmarks) >= 1
    bid = benchmarks[0]["id"]

    # Get questions
    r = client.get(f"/api/v1/quiz/{bid}")
    assert r.status_code == 200
    questions = r.json()["questions"]
    assert len(questions) == 3

    # Submit correct answers
    r = client.post(f"/api/v1/quiz/{bid}/submit", json={
        "answers": {"q1": 0, "q2": 1, "q3": 1}
    })
    assert r.status_code == 200
    result = r.json()
    assert result["correct"] == 3
    assert result["score"] > 0

    # Re-submit should not change results
    r = client.post(f"/api/v1/quiz/{bid}/submit", json={
        "answers": {"q1": 2}
    })
    assert r.status_code == 200
    result2 = r.json()
    q1 = next(d for d in result2["details"] if d["id"] == "q1")
    assert q1["correct"] is True  # original correct answer preserved
