# MCQ Knowledge Benchmark Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add MCQ (multiple-choice question) knowledge benchmark support to the platform, with dedicated API, Web UI, and multi-tab scoreboard.

**Architecture:** Extend `WinCondition` enum with `MCQ` type. New `benchmark_platform/quiz.py` module handles loading, serving, and evaluating MCQ benchmarks. Reuse `team_progress` table for answer storage. Separate `/web/quiz` page and `/api/v1/quiz/` endpoints. Scoreboard gains tab navigation for CTF/MCQ/Combined views.

**Tech Stack:** FastAPI, SQLite (existing), Jinja2 + Tailwind + HTMX (existing patterns), Pydantic models.

---

## File Structure

| File | Responsibility |
|------|---------------|
| `benchmark_platform/models/benchmark.py` | Add `MCQ` to `WinCondition`, add `Question` model |
| `benchmark_platform/quiz.py` | Quiz engine: load, serve, evaluate MCQ benchmarks |
| `benchmark_platform/server.py` | Mount quiz API routes |
| `benchmark_platform/web/routes.py` | Add `/web/quiz` and `/web/quiz/{benchmark_id}` page routes |
| `benchmark_platform/web/templates/components/sidebar.html` | Add "知识评测" nav entry |
| `benchmark_platform/web/templates/components/topbar.html` | Already has `quiz` entry (added earlier) |
| `benchmark_platform/web/templates/pages/quiz_list.html` | Quiz benchmark list page |
| `benchmark_platform/web/templates/pages/quiz_detail.html` | Answer page for a single benchmark |
| `benchmark_platform/web/templates/pages/scoreboard_admin.html` | Add tab navigation |
| `benchmark_platform/web/templates/partials/scoreboard_table.html` | Support filtered scoring |
| `tests/test_quiz.py` | Tests for quiz module |
| `tests/test_quiz_api.py` | Tests for quiz API endpoints |
| `challenges/quiz/sample-quiz/benchmark.json` | Sample MCQ benchmark for testing |

---

### Task 1: Data Model — WinCondition and Question Model

**Files:**
- Modify: `benchmark_platform/models/benchmark.py`
- Test: `tests/test_quiz.py`

- [ ] **Step 1: Write failing test for MCQ model**

```python
# tests/test_quiz.py
"""Tests for MCQ quiz functionality."""
import json
from pathlib import Path

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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_quiz.py::test_win_condition_has_mcq tests/test_quiz.py::test_question_model_validates -v`
Expected: FAIL with `ImportError` or `AttributeError` (MCQ/Question not defined)

- [ ] **Step 3: Implement WinCondition and Question model**

In `benchmark_platform/models/benchmark.py`, change `WinCondition` and add `Question`:

```python
class WinCondition(str, Enum):
    FLAG = 'flag'
    MCQ = 'mcq'


class Question(BaseModel):
    id: str = Field(..., description='Unique question identifier within benchmark')
    text: str = Field(..., description='Question text')
    choices: list[str] = Field(..., description='List of answer choices (typically 4)')
    answer: int = Field(..., description='0-based index of correct choice')
```

Also add `questions` and `category` fields to `Benchmark`:

```python
class Benchmark(BaseModel):
    # ... existing fields ...
    category: str = Field(default="", description='Evaluation category (e.g. security_knowledge)')
    questions: list[Question] = Field(default_factory=list, description='MCQ questions (only for win_condition=mcq)')
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_quiz.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add benchmark_platform/models/benchmark.py tests/test_quiz.py
git commit -m "feat: add MCQ win_condition and Question model"
```

---

### Task 2: Quiz Engine — Load and Evaluate

**Files:**
- Create: `benchmark_platform/quiz.py`
- Create: `challenges/quiz/sample-quiz/benchmark.json`
- Test: `tests/test_quiz.py`

- [ ] **Step 1: Create sample quiz benchmark for testing**

```json
{
  "id": "SAMPLE-QUIZ-001",
  "name": "Sample Security Quiz",
  "description": "A sample quiz for testing",
  "level": 1,
  "win_condition": "mcq",
  "tags": ["test"],
  "canaries": [],
  "category": "security_knowledge",
  "questions": [
    {
      "id": "q1",
      "text": "What does CVE stand for?",
      "choices": [
        "Common Vulnerabilities and Exposures",
        "Critical Vulnerability Evaluation",
        "Cyber Vulnerability Entry",
        "Common Virus Exploits"
      ],
      "answer": 0
    },
    {
      "id": "q2",
      "text": "Which port does HTTPS use by default?",
      "choices": ["80", "443", "8080", "22"],
      "answer": 1
    },
    {
      "id": "q3",
      "text": "What type of attack is SQL injection?",
      "choices": ["DoS", "Injection", "XSS", "CSRF"],
      "answer": 1
    }
  ]
}
```

Save to `challenges/quiz/sample-quiz/benchmark.json`.

- [ ] **Step 2: Write failing tests for quiz engine**

```python
# Append to tests/test_quiz.py

from pathlib import Path

SAMPLE_QUIZ_DIR = Path(__file__).parent.parent / "challenges" / "quiz" / "sample-quiz"


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
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `python -m pytest tests/test_quiz.py::test_quiz_store_loads_benchmarks -v`
Expected: FAIL with `ImportError: cannot import name 'QuizStore'`

- [ ] **Step 4: Implement QuizStore**

Create `benchmark_platform/quiz.py`:

```python
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
        return [
            {"id": q.id, "text": q.text, "choices": q.choices}
            for q in bm.questions
        ]

    def evaluate(self, benchmark_id: str, answers: dict[str, int]) -> dict:
        bm = self._get(benchmark_id)
        answer_map = {q.id: q.answer for q in bm.questions}
        details = []
        correct_count = 0
        for q in bm.questions:
            if q.id not in answers:
                continue
            user_answer = answers[q.id]
            is_correct = user_answer == answer_map[q.id]
            if is_correct:
                correct_count += 1
            entry = {"id": q.id, "correct": is_correct}
            if not is_correct:
                entry["your_answer"] = user_answer
                entry["correct_answer"] = answer_map[q.id]
            details.append(entry)
        total_answered = len(details)
        per_question_score = bm.points // len(bm.questions) if bm.questions else 0
        return {
            "correct": correct_count,
            "total": total_answered,
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
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_quiz.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add benchmark_platform/quiz.py challenges/quiz/sample-quiz/benchmark.json tests/test_quiz.py
git commit -m "feat: add QuizStore engine for MCQ benchmarks"
```

---

### Task 3: Quiz API Endpoints

**Files:**
- Modify: `benchmark_platform/server.py`
- Create: `tests/test_quiz_api.py`

- [ ] **Step 1: Write failing tests for quiz API**

```python
# tests/test_quiz_api.py
"""Tests for quiz API endpoints."""
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from benchmark_platform.db import _set_db_path, init_db, get_or_create_default_team
from benchmark_platform.server import app
from benchmark_platform.quiz import QuizStore
from benchmark_platform.web.auth_middleware import _COOKIE_NAME, create_session_cookie

QUIZ_DIR = Path(__file__).parent.parent / "challenges" / "quiz"


@pytest.fixture(autouse=True)
def setup_db(tmp_path):
    _set_db_path(tmp_path / "test.db")
    init_db()


def _setup_app():
    app.state.manager = None
    app.state.submission_store = None
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
    get_or_create_default_team()
    client = _auth_client()
    r = client.post("/api/v1/quiz/SAMPLE-QUIZ-001/submit", json={
        "answers": {"q1": 0, "q2": 1, "q3": 1}
    })
    assert r.status_code == 200
    data = r.json()
    assert data["correct"] == 3
    assert data["total"] == 3


def test_quiz_submit_prevents_resubmission():
    _setup_app()
    get_or_create_default_team()
    client = _auth_client()
    client.post("/api/v1/quiz/SAMPLE-QUIZ-001/submit", json={"answers": {"q1": 0}})
    r = client.post("/api/v1/quiz/SAMPLE-QUIZ-001/submit", json={"answers": {"q1": 2}})
    assert r.status_code == 200
    data = r.json()
    q1_detail = next(d for d in data["details"] if d["id"] == "q1")
    assert q1_detail["correct"] is True  # original answer preserved


def test_quiz_nonexistent_returns_404():
    _setup_app()
    client = _auth_client()
    r = client.get("/api/v1/quiz/NONEXISTENT")
    assert r.status_code == 404
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_quiz_api.py::test_quiz_list_returns_benchmarks -v`
Expected: FAIL (no route registered)

- [ ] **Step 3: Implement quiz API routes in server.py**

Add to `benchmark_platform/server.py` after existing route registrations:

```python
from benchmark_platform.quiz import QuizStore

# --- Quiz API ---

class QuizSubmitRequest(PydanticBaseModel):
    answers: dict[str, int]


@app.get("/api/v1/quiz")
async def quiz_list(request: Request):
    store: QuizStore = request.app.state.quiz_store
    if store is None:
        return []
    return store.list_benchmarks()


@app.get("/api/v1/quiz/{benchmark_id}")
async def quiz_get(benchmark_id: str, request: Request):
    store: QuizStore = request.app.state.quiz_store
    if store is None:
        raise HTTPException(404, "Quiz store not initialized")
    try:
        questions = store.get_questions(benchmark_id)
    except KeyError:
        raise HTTPException(404, f"Quiz {benchmark_id} not found")
    bm_info = next((b for b in store.list_benchmarks() if b["id"] == benchmark_id), {})
    return {"benchmark_id": benchmark_id, **bm_info, "questions": questions}


@app.post("/api/v1/quiz/{benchmark_id}/submit")
async def quiz_submit(benchmark_id: str, payload: QuizSubmitRequest, team: dict = Depends(get_current_team)):
    store: QuizStore = request.app.state.quiz_store
    if store is None:
        raise HTTPException(503, "Quiz store not initialized")
    try:
        store._get(benchmark_id)
    except KeyError:
        raise HTTPException(404, f"Quiz {benchmark_id} not found")

    # Filter out already-answered questions
    from benchmark_platform.db import get_team_progress
    progress = get_team_progress(team["id"], benchmark_id)
    already_answered = {p["flag_id"] for p in progress}
    new_answers = {qid: ans for qid, ans in payload.answers.items() if qid not in already_answered}

    # Evaluate new answers
    result = store.evaluate(benchmark_id, new_answers)

    # Persist to team_progress
    for detail in result["details"]:
        mark_flag_solved(team["id"], benchmark_id, detail["id"]) if detail["correct"] else None
        # Record wrong answers too (to prevent re-submission)
        from benchmark_platform.db import _get_conn
        conn = _get_conn()
        conn.execute(
            "INSERT OR IGNORE INTO team_progress (team_id, benchmark_id, flag_id, solved, solved_at) VALUES (?, ?, ?, ?, ?)",
            (team["id"], benchmark_id, detail["id"], 1 if detail["correct"] else 0,
             __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat()),
        )
        conn.commit()

    # Return full result including previously answered
    all_answers = {**{qid: ans for qid, ans in payload.answers.items() if qid in already_answered}, **new_answers}
    full_result = store.evaluate(benchmark_id, payload.answers)
    # Override with stored correct for already-answered
    for detail in full_result["details"]:
        if detail["id"] in already_answered:
            stored = next((p for p in progress if p["flag_id"] == detail["id"]), None)
            if stored:
                detail["correct"] = bool(stored["solved"])
    full_result["correct"] = sum(1 for d in full_result["details"] if d["correct"])
    return full_result
```

- [ ] **Step 4: Initialize quiz_store in app startup**

In `server.py`, after `app.state` initialization, add:

```python
_quiz_dirs = [Path("challenges/quiz")]
app.state.quiz_store = None  # initialized lazily or in CLI
```

And in the CLI `serve` command (or wherever `app.state.manager` is set), add:

```python
app.state.quiz_store = QuizStore(_quiz_dirs)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_quiz_api.py -v`
Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add benchmark_platform/server.py tests/test_quiz_api.py
git commit -m "feat: add quiz API endpoints (list, get, submit)"
```

---

### Task 4: Web UI — Quiz List Page

**Files:**
- Modify: `benchmark_platform/web/routes.py`
- Create: `benchmark_platform/web/templates/pages/quiz_list.html`
- Modify: `benchmark_platform/web/templates/components/sidebar.html`

- [ ] **Step 1: Add quiz page route**

In `benchmark_platform/web/routes.py`, add:

```python
@web_router.get("/quiz")
async def page_quiz(request: Request):
    quiz_store = getattr(request.app.state, "quiz_store", None)
    team_id = _get_selected_team_id(request)
    benchmarks = []
    if quiz_store:
        for bm_info in quiz_store.list_benchmarks():
            from benchmark_platform.db import get_team_progress
            progress = get_team_progress(team_id, bm_info["id"])
            answered = len(progress)
            correct = sum(1 for p in progress if p["solved"])
            benchmarks.append({
                **bm_info,
                "answered": answered,
                "correct": correct,
                "accuracy": round(correct / answered * 100) if answered > 0 else 0,
            })
    return _render(request, "pages/quiz_list.html", {"page": "quiz", "benchmarks": benchmarks})
```

- [ ] **Step 2: Create quiz list template**

Create `benchmark_platform/web/templates/pages/quiz_list.html`:

```html
{% extends "base.html" %}
{% block title %}知识评测{% endblock %}
{% block content %}
<div class="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-4">
  {% for bm in benchmarks %}
  <div class="bg-white rounded-xl border border-gray-100 p-5 hover:shadow-sm transition-shadow">
    <div class="flex items-start justify-between mb-3">
      <h3 class="text-[14px] font-semibold text-gray-900">{{ bm.name }}</h3>
      <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[10px] font-medium bg-blue-50 text-blue-600">
        {{ bm.category | replace('_', ' ') | title }}
      </span>
    </div>
    <p class="text-[12px] text-gray-500 mb-4 line-clamp-2">{{ bm.description }}</p>
    <div class="flex items-center justify-between">
      <div class="text-[11px] text-gray-400">
        {{ bm.question_count }} 题
        {% if bm.answered > 0 %}
        · 已答 {{ bm.answered }}/{{ bm.question_count }}
        · 正确率 {{ bm.accuracy }}%
        {% endif %}
      </div>
      <a href="/web/quiz/{{ bm.id }}"
         class="inline-flex items-center px-3 py-1.5 rounded-lg text-[12px] font-medium
                {% if bm.answered == bm.question_count %}bg-gray-100 text-gray-600{% else %}bg-gray-900 text-white hover:bg-gray-800{% endif %}">
        {% if bm.answered == bm.question_count %}查看结果{% elif bm.answered > 0 %}继续答题{% else %}开始答题{% endif %}
      </a>
    </div>
  </div>
  {% endfor %}
  {% if not benchmarks %}
  <div class="col-span-full text-center py-12 text-[13px] text-gray-400">暂无知识评测题目</div>
  {% endif %}
</div>
{% endblock %}
```

- [ ] **Step 3: Add sidebar entry**

In `benchmark_platform/web/templates/components/sidebar.html`, after the "排行榜" link (line 61), add:

```html
    <a href="/web/quiz"
       class="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap
              {% if page == 'quiz' %}bg-gray-900 text-white{% else %}text-gray-600 hover:bg-gray-50 cursor-pointer{% endif %}">
      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M4.26 10.147a60.438 60.438 0 0 0-.491 6.347A48.62 48.62 0 0 1 12 20.904a48.62 48.62 0 0 1 8.232-4.41 60.46 60.46 0 0 0-.491-6.347m-15.482 0a50.636 50.636 0 0 0-2.658-.813A59.906 59.906 0 0 1 12 3.493a59.903 59.903 0 0 1 10.399 5.84c-.896.248-1.783.52-2.658.814m-15.482 0A50.717 50.717 0 0 1 12 13.489a50.702 50.702 0 0 1 7.74-3.342M6.75 15a.75.75 0 1 0 0-1.5.75.75 0 0 0 0 1.5Zm0 0v-3.675A55.378 55.378 0 0 1 12 8.443m-7.007 11.55A5.981 5.981 0 0 0 6.75 15.75v-1.5"/>
      </svg>
      知识评测
    </a>
```

- [ ] **Step 4: Run and verify page loads**

Run: `python -m pytest tests/test_quiz_api.py -v` (existing tests still pass)

Add a quick route test:

```python
# Append to tests/test_quiz_api.py

def test_quiz_web_page_returns_200():
    _setup_app()
    client = _auth_client()
    r = client.get("/web/quiz")
    assert r.status_code == 200
    assert "知识评测" in r.text
```

- [ ] **Step 5: Commit**

```bash
git add benchmark_platform/web/routes.py benchmark_platform/web/templates/pages/quiz_list.html benchmark_platform/web/templates/components/sidebar.html tests/test_quiz_api.py
git commit -m "feat: add quiz list page and sidebar navigation"
```

---

### Task 5: Web UI — Quiz Answer Page

**Files:**
- Modify: `benchmark_platform/web/routes.py`
- Create: `benchmark_platform/web/templates/pages/quiz_detail.html`

- [ ] **Step 1: Add quiz detail route**

In `benchmark_platform/web/routes.py`, add:

```python
@web_router.get("/quiz/{benchmark_id}")
async def page_quiz_detail(request: Request, benchmark_id: str):
    quiz_store = getattr(request.app.state, "quiz_store", None)
    if not quiz_store:
        return RedirectResponse("/web/quiz", status_code=302)
    try:
        questions = quiz_store.get_questions(benchmark_id)
    except KeyError:
        return RedirectResponse("/web/quiz", status_code=302)
    bm_info = next((b for b in quiz_store.list_benchmarks() if b["id"] == benchmark_id), {})
    team_id = _get_selected_team_id(request)
    from benchmark_platform.db import get_team_progress
    progress = get_team_progress(team_id, benchmark_id)
    answered_ids = {p["flag_id"]: bool(p["solved"]) for p in progress}
    return _render(request, "pages/quiz_detail.html", {
        "page": "quiz",
        "benchmark_id": benchmark_id,
        "benchmark_name": bm_info.get("name", benchmark_id),
        "questions": questions,
        "answered": answered_ids,
        "total": len(questions),
        "correct_count": sum(1 for v in answered_ids.values() if v),
    })
```

- [ ] **Step 2: Create quiz detail template**

Create `benchmark_platform/web/templates/pages/quiz_detail.html`:

```html
{% extends "base.html" %}
{% block title %}{{ benchmark_name }}{% endblock %}
{% block content %}
<div x-data="{current: 0, answers: {}, submitted: {{ answered | tojson }} }">
  <div class="flex items-center justify-between mb-6">
    <div>
      <h2 class="text-[15px] font-semibold text-gray-900">{{ benchmark_name }}</h2>
      <p class="text-[12px] text-gray-500 mt-0.5">已答 {{ answered | length }}/{{ total }}，正确 {{ correct_count }}</p>
    </div>
    <a href="/web/quiz" class="text-[12px] text-gray-500 hover:text-gray-700">返回列表</a>
  </div>

  {% for q in questions %}
  <div x-show="current === {{ loop.index0 }}" class="bg-white rounded-xl border border-gray-100 p-6">
    <div class="text-[11px] text-gray-400 mb-2">第 {{ loop.index }}/{{ total }} 题</div>
    <div class="text-[14px] text-gray-900 font-medium mb-4">{{ q.text }}</div>
    <div class="space-y-2">
      {% for choice in q.choices %}
      <label class="flex items-center gap-3 p-3 rounded-lg border cursor-pointer transition-all"
             :class="{
               'border-gray-900 bg-gray-50': answers['{{ q.id }}'] === {{ loop.index0 }} && !submitted['{{ q.id }}'],
               'border-emerald-500 bg-emerald-50': submitted['{{ q.id }}'] === true && answers['{{ q.id }}'] === {{ loop.index0 }},
               'border-red-300 bg-red-50': submitted['{{ q.id }}'] === false && answers['{{ q.id }}'] === {{ loop.index0 }},
               'border-gray-200 hover:border-gray-300': answers['{{ q.id }}'] !== {{ loop.index0 }} && !submitted.hasOwnProperty('{{ q.id }}'),
               'border-gray-100 opacity-60': submitted.hasOwnProperty('{{ q.id }}') && answers['{{ q.id }}'] !== {{ loop.index0 }},
             }"
             @click="if(!submitted.hasOwnProperty('{{ q.id }}')) answers['{{ q.id }}'] = {{ loop.index0 }}">
        <input type="radio" name="q_{{ q.id }}" :checked="answers['{{ q.id }}'] === {{ loop.index0 }}"
               :disabled="submitted.hasOwnProperty('{{ q.id }}')" class="sr-only">
        <span class="w-5 h-5 rounded-full border-2 flex items-center justify-center flex-shrink-0"
              :class="answers['{{ q.id }}'] === {{ loop.index0 }} ? 'border-gray-900' : 'border-gray-300'">
          <span x-show="answers['{{ q.id }}'] === {{ loop.index0 }}" class="w-2.5 h-2.5 rounded-full bg-gray-900"></span>
        </span>
        <span class="text-[13px] text-gray-700">{{ choice }}</span>
      </label>
      {% endfor %}
    </div>

    <div class="flex items-center justify-between mt-6">
      <button @click="current = Math.max(0, current - 1)"
              x-show="current > 0"
              class="px-4 py-2 text-[12px] text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50">上一题</button>
      <div class="flex-1"></div>
      <button x-show="answers.hasOwnProperty('{{ q.id }}') && !submitted.hasOwnProperty('{{ q.id }}')"
              @click="
                fetch('/api/v1/quiz/{{ benchmark_id }}/submit', {
                  method: 'POST',
                  headers: {'Content-Type': 'application/json'},
                  body: JSON.stringify({answers: {'{{ q.id }}': answers['{{ q.id }}']}})
                })
                .then(r => r.json())
                .then(data => {
                  let detail = data.details.find(d => d.id === '{{ q.id }}');
                  if(detail) submitted['{{ q.id }}'] = detail.correct;
                })
              "
              class="px-4 py-2 text-[12px] font-medium text-white bg-gray-900 rounded-lg hover:bg-gray-800">提交</button>
      <button @click="current = Math.min({{ total }} - 1, current + 1)"
              x-show="current < {{ total }} - 1"
              class="ml-2 px-4 py-2 text-[12px] text-gray-600 border border-gray-200 rounded-lg hover:bg-gray-50">下一题</button>
    </div>
  </div>
  {% endfor %}

  <!-- Progress bar -->
  <div class="mt-6 flex gap-1">
    {% for q in questions %}
    <button @click="current = {{ loop.index0 }}"
            class="flex-1 h-2 rounded-full transition-colors"
            :class="{
              'bg-emerald-500': submitted['{{ q.id }}'] === true,
              'bg-red-400': submitted['{{ q.id }}'] === false,
              'bg-gray-900': current === {{ loop.index0 }} && !submitted.hasOwnProperty('{{ q.id }}'),
              'bg-gray-200': current !== {{ loop.index0 }} && !submitted.hasOwnProperty('{{ q.id }}'),
            }"></button>
    {% endfor %}
  </div>
</div>
{% endblock %}
```

- [ ] **Step 3: Add route test**

```python
# Append to tests/test_quiz_api.py

def test_quiz_detail_page_returns_200():
    _setup_app()
    client = _auth_client()
    r = client.get("/web/quiz/SAMPLE-QUIZ-001")
    assert r.status_code == 200
    assert "What does CVE stand for?" in r.text
    assert "SAMPLE-QUIZ-001" in r.text
```

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_quiz_api.py -v`
Expected: ALL PASS

- [ ] **Step 5: Commit**

```bash
git add benchmark_platform/web/routes.py benchmark_platform/web/templates/pages/quiz_detail.html tests/test_quiz_api.py
git commit -m "feat: add quiz answer page with per-question submission"
```

---

### Task 6: Scoreboard — Multi-Tab Ranking

**Files:**
- Modify: `benchmark_platform/web/routes.py`
- Modify: `benchmark_platform/web/templates/pages/scoreboard_admin.html`
- Modify: `benchmark_platform/web/templates/partials/scoreboard_table.html`
- Modify: `benchmark_platform/db.py`

- [ ] **Step 1: Add DB helper for quiz scores**

In `benchmark_platform/db.py`, add:

```python
def get_team_quiz_scores() -> list[dict]:
    """Get MCQ scores per team. Returns [{team_id, team_name, quiz_score, answered, correct}]."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT tp.team_id, t.name as team_name,
               COUNT(*) as answered,
               SUM(CASE WHEN tp.solved = 1 THEN 1 ELSE 0 END) as correct
        FROM team_progress tp
        JOIN teams t ON t.id = tp.team_id
        WHERE tp.benchmark_id IN (
            SELECT DISTINCT benchmark_id FROM team_progress
            WHERE benchmark_id LIKE 'CYBERMETRIC%' OR benchmark_id LIKE 'SECBENCH%'
               OR benchmark_id LIKE 'CTIBENCH%' OR benchmark_id LIKE 'MMLU%'
               OR benchmark_id LIKE 'CISSP%' OR benchmark_id LIKE 'SAMPLE-QUIZ%'
        )
        GROUP BY tp.team_id
    """).fetchall()
    return [dict(r) for r in rows]
```

Note: This is a simplified approach. A better long-term solution would store `win_condition` in the DB or use a quiz benchmark ID registry. For Phase 1, we identify quiz benchmarks by their known ID prefixes.

- [ ] **Step 2: Update scoreboard route to pass tab data**

In `benchmark_platform/web/routes.py`, modify `scoreboard_page`:

```python
@web_router.get("/scoreboard")
async def scoreboard_page(request: Request):
    from benchmark_platform.db import list_teams, get_team_quiz_scores
    tab = request.query_params.get("tab", "combined")
    teams_data = list_teams()
    teams_data.sort(key=lambda t: t.get("solved_flags", 0), reverse=True)
    manager = _get_manager(request)
    total_flags = sum(max(1, len(c.flag_states)) for c in manager.challenges) if manager else 1

    quiz_scores = {}
    try:
        for qs in get_team_quiz_scores():
            quiz_scores[qs["team_id"]] = qs
    except Exception:
        pass

    for t in teams_data:
        qs = quiz_scores.get(t["id"], {})
        t["quiz_score"] = qs.get("correct", 0) * 10  # simplified: 10 pts per correct
        t["quiz_answered"] = qs.get("answered", 0)
        t["quiz_correct"] = qs.get("correct", 0)
        t["combined_score"] = t.get("solved_flags", 0) * 100 + t["quiz_score"]

    if tab == "mcq":
        teams_data.sort(key=lambda t: t.get("quiz_score", 0), reverse=True)
    elif tab == "combined":
        teams_data.sort(key=lambda t: t.get("combined_score", 0), reverse=True)

    user = getattr(request.state, "user", {})
    ctx = {"teams": teams_data, "total_flags": total_flags or 1, "page": "scoreboard", "tab": tab}
    if user.get("role") == "admin":
        return _render(request, "pages/scoreboard_admin.html", ctx)
    return templates.TemplateResponse(
        request, "pages/scoreboard.html", context={**ctx, "user": user},
    )
```

- [ ] **Step 3: Update scoreboard_admin.html with tabs**

Replace `benchmark_platform/web/templates/pages/scoreboard_admin.html`:

```html
{% extends "base.html" %}
{% block title %}排行榜{% endblock %}
{% block content %}
<div class="mb-4 flex gap-2">
  <a href="/web/scoreboard?tab=combined"
     class="px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all
            {% if tab == 'combined' %}bg-gray-900 text-white{% else %}text-gray-600 hover:bg-gray-100{% endif %}">综合</a>
  <a href="/web/scoreboard?tab=ctf"
     class="px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all
            {% if tab == 'ctf' %}bg-gray-900 text-white{% else %}text-gray-600 hover:bg-gray-100{% endif %}">CTF</a>
  <a href="/web/scoreboard?tab=mcq"
     class="px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all
            {% if tab == 'mcq' %}bg-gray-900 text-white{% else %}text-gray-600 hover:bg-gray-100{% endif %}">MCQ</a>
</div>
<div hx-get="/web/scoreboard?tab={{ tab }}" hx-trigger="every 5s" hx-select="#scoreboard-table" hx-target="#scoreboard-table" hx-swap="outerHTML">
  {% include "partials/scoreboard_table.html" %}
</div>
{% endblock %}
```

- [ ] **Step 4: Update scoreboard_table.html to show tab-appropriate columns**

Modify `benchmark_platform/web/templates/partials/scoreboard_table.html` to conditionally show columns based on `tab`:

```html
<div id="scoreboard-table" class="bg-white rounded-xl border border-gray-100 overflow-hidden">
  <table class="w-full">
    <thead class="bg-gray-50 border-b border-gray-100">
      <tr>
        <th class="px-4 py-3 text-left text-[11px] font-medium text-gray-500 w-12">#</th>
        <th class="px-4 py-3 text-left text-[11px] font-medium text-gray-500">队伍</th>
        {% if tab != 'mcq' %}
        <th class="px-4 py-3 text-right text-[11px] font-medium text-gray-500">CTF Flags</th>
        {% endif %}
        {% if tab != 'ctf' %}
        <th class="px-4 py-3 text-right text-[11px] font-medium text-gray-500">MCQ 正确</th>
        {% endif %}
        {% if tab == 'combined' %}
        <th class="px-4 py-3 text-right text-[11px] font-medium text-gray-500">综合分</th>
        {% endif %}
      </tr>
    </thead>
    <tbody class="divide-y divide-gray-50">
      {% for team in teams %}
      <tr class="hover:bg-gray-50">
        <td class="px-4 py-3 text-[12px] text-gray-500 font-medium">{{ loop.index }}</td>
        <td class="px-4 py-3 text-[13px] text-gray-900 font-medium">{{ team.name }}</td>
        {% if tab != 'mcq' %}
        <td class="px-4 py-3 text-[12px] text-gray-700 text-right">{{ team.solved_flags }}/{{ total_flags }}</td>
        {% endif %}
        {% if tab != 'ctf' %}
        <td class="px-4 py-3 text-[12px] text-gray-700 text-right">{{ team.quiz_correct | default(0) }}</td>
        {% endif %}
        {% if tab == 'combined' %}
        <td class="px-4 py-3 text-[12px] text-gray-900 font-semibold text-right">{{ team.combined_score | default(0) }}</td>
        {% endif %}
      </tr>
      {% endfor %}
      {% if not teams %}
      <tr><td colspan="5" class="px-4 py-6 text-center text-[12px] text-gray-400">暂无队伍数据</td></tr>
      {% endif %}
    </tbody>
  </table>
</div>
```

- [ ] **Step 5: Add test for scoreboard tabs**

```python
# Append to tests/test_quiz_api.py

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
    assert "MCQ 正确" in r.text
```

- [ ] **Step 6: Run tests**

Run: `python -m pytest tests/test_quiz_api.py -v`
Expected: ALL PASS

- [ ] **Step 7: Commit**

```bash
git add benchmark_platform/db.py benchmark_platform/web/routes.py benchmark_platform/web/templates/pages/scoreboard_admin.html benchmark_platform/web/templates/partials/scoreboard_table.html tests/test_quiz_api.py
git commit -m "feat: add multi-tab scoreboard (CTF/MCQ/Combined)"
```

---

### Task 7: Observer Scoreboard — Add Tabs

**Files:**
- Modify: `benchmark_platform/web/templates/pages/scoreboard.html`

- [ ] **Step 1: Update observer scoreboard with same tab navigation**

Replace `benchmark_platform/web/templates/pages/scoreboard.html`:

```html
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>排行榜</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/htmx.org@2.0.4"></script>
</head>
<body class="bg-gray-100 min-h-screen">
  <header class="bg-white shadow-sm border-b">
    <div class="max-w-7xl mx-auto px-4 py-4 flex items-center justify-between">
      <h1 class="text-xl font-bold text-gray-800">排行榜</h1>
      <div class="flex items-center gap-4">
        <span class="text-sm text-gray-500">{{ user.get('team_name', '') }}</span>
        <a href="/web/logout" class="text-sm text-red-500 hover:text-red-700">Logout</a>
      </div>
    </div>
  </header>

  <main class="max-w-7xl mx-auto px-4 py-8">
    <div class="mb-4 flex gap-2">
      <a href="/web/scoreboard?tab=combined"
         class="px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all
                {% if tab == 'combined' %}bg-gray-900 text-white{% else %}text-gray-600 hover:bg-gray-200{% endif %}">综合</a>
      <a href="/web/scoreboard?tab=ctf"
         class="px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all
                {% if tab == 'ctf' %}bg-gray-900 text-white{% else %}text-gray-600 hover:bg-gray-200{% endif %}">CTF</a>
      <a href="/web/scoreboard?tab=mcq"
         class="px-3 py-1.5 rounded-lg text-[12px] font-medium transition-all
                {% if tab == 'mcq' %}bg-gray-900 text-white{% else %}text-gray-600 hover:bg-gray-200{% endif %}">MCQ</a>
    </div>
    <div hx-get="/web/scoreboard?tab={{ tab }}" hx-trigger="every 5s" hx-select="#scoreboard-table" hx-target="#scoreboard-table" hx-swap="outerHTML">
      {% include "partials/scoreboard_table.html" %}
    </div>
  </main>
</body>
</html>
```

- [ ] **Step 2: Verify existing scoreboard test still passes**

Run: `python -m pytest tests/test_web_routes.py::test_scoreboard_page_title_is_rankings -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add benchmark_platform/web/templates/pages/scoreboard.html
git commit -m "feat: add tab navigation to observer scoreboard"
```

---

### Task 8: Integration — Wire QuizStore into App Startup

**Files:**
- Modify: `benchmark_platform/server.py`

- [ ] **Step 1: Initialize QuizStore in app state**

In `benchmark_platform/server.py`, find where `app.state.manager` is set (in the CLI serve command or initialization block) and add quiz store initialization alongside it:

```python
from benchmark_platform.quiz import QuizStore

# After app creation, set default
app.state.quiz_store = None
```

In the CLI `serve` function (or wherever challenges are loaded), add:

```python
quiz_dirs = [Path(f) / "quiz" for f in benchmark_folders if (Path(f) / "quiz").exists()]
if not quiz_dirs:
    quiz_dirs = [Path("challenges/quiz")]
app.state.quiz_store = QuizStore(quiz_dirs)
```

- [ ] **Step 2: Verify full integration test**

```python
# Append to tests/test_quiz_api.py

def test_full_quiz_flow():
    """End-to-end: list -> get questions -> submit -> verify score."""
    _setup_app()
    get_or_create_default_team()
    client = _auth_client()

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
```

- [ ] **Step 3: Run all tests**

Run: `python -m pytest tests/test_quiz.py tests/test_quiz_api.py -v`
Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add benchmark_platform/server.py tests/test_quiz_api.py
git commit -m "feat: wire QuizStore into app startup and add integration test"
```
