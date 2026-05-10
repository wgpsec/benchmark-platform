# Benchmark Platform Web UI — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a full-featured Web UI to the benchmark-platform FastAPI server — dashboard, challenge management, submission history, instance status — served on the same port, following RedC GUI design spec.

**Architecture:** Jinja2 templates rendered by FastAPI, HTMX for partial refreshes and API calls, Alpine.js for client-side state (filters, modals, toasts). All pages share a sidebar layout via `base.html`. The Web UI reads from the same `ChallengeManager` and a new `SubmissionStore` that the existing `/api/*` endpoints use. No separate frontend build step.

**Tech Stack:** Python 3.12, FastAPI, Jinja2, Tailwind CSS (CDN), HTMX (CDN), Alpine.js (CDN), Heroicons (inline SVG)

---

## File Structure

### New files:

```
benchmark_platform/
├── static/css/app.css                          # Custom styles (toast animation, scrollbar)
├── web/
│   ├── __init__.py                             # Empty
│   ├── routes.py                               # Page routes (/web/*) + partial routes (/web/partials/*)
│   ├── context.py                              # Build template context dicts from manager/store state
│   ├── submission_store.py                     # SubmissionStore: in-memory list + JSONL append
│   └── templates/
│       ├── base.html                           # Layout skeleton: sidebar + main area + CDN imports
│       ├── components/
│       │   ├── sidebar.html                    # Sidebar navigation with groups
│       │   ├── topbar.html                     # Page title bar
│       │   ├── toast.html                      # Alpine.js toast notification manager
│       │   ├── challenge_card.html             # Single challenge card (used in challenges page + partial)
│       │   ├── modal_submit.html               # Flag submission modal
│       │   └── modal_confirm.html              # Dangerous action confirmation modal
│       ├── pages/
│       │   ├── dashboard.html                  # Scoreboard + stats + level progress
│       │   ├── challenges.html                 # Challenge cards grouped by level
│       │   ├── history.html                    # Submission history table
│       │   └── status.html                     # Instance status table
│       └── partials/
│           ├── dashboard_stats.html            # Stats cards + level progress (HTMX poll target)
│           ├── challenge_card_single.html       # Single card refresh after action
│           ├── history_rows.html               # Table rows for history (HTMX poll target)
│           └── status_table.html               # Status table body (HTMX poll target)
tests/
├── test_submission_store.py
├── test_level_gate.py
├── test_web_context.py
└── test_web_routes.py
```

### Modified files:

- `pyproject.toml` — add jinja2, aiofiles deps
- `benchmark_platform/server.py` — mount web router + static files, wire SubmissionStore, change root redirect
- `benchmark_platform/utils/challenge.py` — add `get_current_level()`, `is_level_unlocked()`, `get_level_for_challenge()`

---

## Task 1: Project Scaffolding & Dependencies

**Files:**
- Modify: `pyproject.toml`
- Create: `benchmark_platform/static/css/app.css`
- Create: `benchmark_platform/web/__init__.py`

- [ ] **Step 1: Add Python dependencies**

In `pyproject.toml`, add to the `dependencies` list:

```toml
    "jinja2>=3.1.0",
    "aiofiles>=24.0.0",
```

The full dependencies block becomes:

```toml
dependencies = [
    "fastapi>=0.121.2",
    "portpicker>=1.6.0",
    "pydantic>=2.12.4",
    "pyyaml>=6.0.2",
    "rich>=13.7.0",
    "tenacity>=9.0.0",
    "python-dotenv>=1.0.0",
    "typer>=0.20.0",
    "uvicorn>=0.38.0",
    "jinja2>=3.1.0",
    "aiofiles>=24.0.0",
]
```

- [ ] **Step 2: Install updated deps**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && pip install -e .`
Expected: Successfully installed (jinja2 and aiofiles added)

- [ ] **Step 3: Create directory structure**

```bash
mkdir -p benchmark_platform/static/css
mkdir -p benchmark_platform/web/templates/components
mkdir -p benchmark_platform/web/templates/pages
mkdir -p benchmark_platform/web/templates/partials
```

- [ ] **Step 4: Create app.css**

```css
/* benchmark_platform/static/css/app.css */

@keyframes toast-in {
  from { opacity: 0; transform: translateX(100%); }
  to { opacity: 1; transform: translateX(0); }
}
@keyframes toast-out {
  from { opacity: 1; transform: translateX(0); }
  to { opacity: 0; transform: translateX(100%); }
}
.animate-toast-in { animation: toast-in 0.25s ease-out; }
.animate-toast-out { animation: toast-out 0.2s ease-in forwards; }

/* Thin scrollbar for sidebar and tables */
.thin-scroll::-webkit-scrollbar { width: 4px; }
.thin-scroll::-webkit-scrollbar-track { background: transparent; }
.thin-scroll::-webkit-scrollbar-thumb { background: #d1d5db; border-radius: 2px; }
```

- [ ] **Step 5: Create web/__init__.py**

```python
# benchmark_platform/web/__init__.py
```

Empty file. The module init.

- [ ] **Step 6: Commit**

```bash
git add pyproject.toml benchmark_platform/static/ benchmark_platform/web/__init__.py
git commit -m "feat: scaffold web UI directories and add jinja2/aiofiles deps"
```

---

## Task 2: SubmissionStore

**Files:**
- Create: `benchmark_platform/web/submission_store.py`
- Create: `tests/test_submission_store.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_submission_store.py
"""Tests for SubmissionStore."""
from benchmark_platform.web.submission_store import SubmissionRecord, SubmissionStore


def test_add_and_query():
    store = SubmissionStore()
    r1 = SubmissionRecord(
        timestamp="2026-05-10T14:00:00Z",
        challenge_code="c1",
        benchmark_id="XBEN-001-24",
        challenge_name="Test Challenge",
        flag_id="default",
        flag_value="flag{test}",
        correct=True,
        points=200,
    )
    r2 = SubmissionRecord(
        timestamp="2026-05-10T14:01:00Z",
        challenge_code="c2",
        benchmark_id="XBEN-002-24",
        challenge_name="Another",
        flag_id="default",
        flag_value="flag{wrong}",
        correct=False,
        points=0,
    )
    store.add(r1)
    store.add(r2)
    all_records = store.query()
    assert len(all_records) == 2
    assert all_records[0].timestamp == "2026-05-10T14:01:00Z"  # newest first


def test_query_filter_correct():
    store = SubmissionStore()
    store.add(SubmissionRecord("t1", "c1", "B1", "N1", "d", "f", True, 200))
    store.add(SubmissionRecord("t2", "c2", "B2", "N2", "d", "f", False, 0))
    store.add(SubmissionRecord("t3", "c3", "B3", "N3", "d", "f", True, 300))
    correct_only = store.query(correct=True)
    assert len(correct_only) == 2
    assert all(r.correct for r in correct_only)


def test_query_limit_offset():
    store = SubmissionStore()
    for i in range(20):
        store.add(SubmissionRecord(f"t{i}", f"c{i}", f"B{i}", f"N{i}", "d", "f", True, 100))
    page = store.query(limit=5, offset=5)
    assert len(page) == 5
    assert page[0].timestamp == "t14"  # newest first, skip 5


def test_total_counts():
    store = SubmissionStore()
    store.add(SubmissionRecord("t1", "c1", "B1", "N1", "d", "f", True, 200))
    store.add(SubmissionRecord("t2", "c2", "B2", "N2", "d", "f", False, 0))
    store.add(SubmissionRecord("t3", "c3", "B3", "N3", "d", "f", True, 300))
    assert store.total_count == 3
    assert store.correct_count == 2
    assert store.incorrect_count == 1


def test_jsonl_persistence(tmp_path):
    log_path = tmp_path / "submissions.jsonl"
    store = SubmissionStore(log_path=log_path)
    store.add(SubmissionRecord("t1", "c1", "B1", "N1", "d", "f", True, 200))
    assert log_path.exists()
    lines = log_path.read_text().strip().split("\n")
    assert len(lines) == 1
    assert '"correct": true' in lines[0]
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -m pytest tests/test_submission_store.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'benchmark_platform.web.submission_store'`

- [ ] **Step 3: Implement SubmissionStore**

```python
# benchmark_platform/web/submission_store.py
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -m pytest tests/test_submission_store.py -v`
Expected: All 5 tests PASS

- [ ] **Step 5: Commit**

```bash
git add benchmark_platform/web/submission_store.py tests/test_submission_store.py
git commit -m "feat: SubmissionStore with in-memory storage and JSONL persistence"
```

---

## Task 3: Level Gate Logic

**Files:**
- Modify: `benchmark_platform/utils/challenge.py`
- Create: `tests/test_level_gate.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_level_gate.py
"""Tests for level gate logic in ChallengeManager."""
from pathlib import Path
from unittest.mock import patch

from benchmark_platform.base import Challenge, Difficulty, TargetInfo
from benchmark_platform.utils.challenge import ChallengeManager


def _make_challenge(code: str, level: int, solved: bool = False) -> Challenge:
    level_map = {1: Difficulty.EASY, 2: Difficulty.MEDIUM, 3: Difficulty.HARD}
    c = Challenge(
        challenge_code=code,
        difficulty=level_map[level],
        points={1: 200, 2: 300, 3: 500}[level],
        hint_viewed=False,
        solved=solved,
        target_info=TargetInfo(ip="localhost", port=[8080]),
    )
    c.set_benchmark_id(f"XBEN-{code}")
    return c


def _make_manager(challenges: list[Challenge], no_level_gate: bool = False) -> ChallengeManager:
    mgr = ChallengeManager(
        benchmark_folders=[],
        benchmark_ids=[],
        public_accessible_host="localhost",
        no_level_gate=no_level_gate,
    )
    mgr.challenges = challenges
    return mgr


def test_current_level_all_unsolved():
    mgr = _make_manager([
        _make_challenge("001", 1),
        _make_challenge("002", 2),
    ])
    assert mgr.get_current_level() == 1


def test_current_level_after_solving_level1():
    mgr = _make_manager([
        _make_challenge("001", 1, solved=True),
        _make_challenge("002", 1, solved=True),
        _make_challenge("003", 2),
    ])
    assert mgr.get_current_level() == 2


def test_current_level_all_solved():
    mgr = _make_manager([
        _make_challenge("001", 1, solved=True),
        _make_challenge("002", 2, solved=True),
    ])
    assert mgr.get_current_level() == 2


def test_is_level_unlocked():
    mgr = _make_manager([
        _make_challenge("001", 1, solved=True),
        _make_challenge("002", 1, solved=True),
        _make_challenge("003", 2),
        _make_challenge("004", 3),
    ])
    assert mgr.is_level_unlocked(1) is True
    assert mgr.is_level_unlocked(2) is True
    assert mgr.is_level_unlocked(3) is False


def test_no_level_gate_unlocks_all():
    mgr = _make_manager(
        [_make_challenge("001", 1), _make_challenge("002", 3)],
        no_level_gate=True,
    )
    assert mgr.is_level_unlocked(1) is True
    assert mgr.is_level_unlocked(3) is True


def test_get_level_for_challenge():
    mgr = _make_manager([])
    c = _make_challenge("001", 2)
    assert mgr.get_level_for_challenge(c) == 2


def test_no_challenges():
    mgr = _make_manager([])
    assert mgr.get_current_level() == 1
    assert mgr.is_level_unlocked(1) is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -m pytest tests/test_level_gate.py -v`
Expected: FAIL — `AttributeError: 'ChallengeManager' object has no attribute 'get_current_level'`

- [ ] **Step 3: Implement level gate methods**

Add these methods to the `ChallengeManager` class in `benchmark_platform/utils/challenge.py`, after the `get_instance_status` method:

```python
    def get_level_for_challenge(self, challenge: Challenge) -> int:
        """Return the level (1/2/3) for a challenge based on its difficulty."""
        level_map = {Difficulty.EASY: 1, Difficulty.MEDIUM: 2, Difficulty.HARD: 3}
        return level_map[challenge.difficulty]

    def get_current_level(self) -> int:
        """Return the highest unlocked level based on solved challenges."""
        if not self.challenges:
            return 1
        levels = sorted(set(self.get_level_for_challenge(c) for c in self.challenges))
        for level in levels:
            at_level = [c for c in self.challenges if self.get_level_for_challenge(c) == level]
            if not all(c.solved for c in at_level):
                return level
        return levels[-1]

    def is_level_unlocked(self, level: int) -> bool:
        """Check if a level is accessible. Always True when no_level_gate is set."""
        if self.no_level_gate:
            return True
        return level <= self.get_current_level()
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -m pytest tests/test_level_gate.py -v`
Expected: All 7 tests PASS

- [ ] **Step 5: Run existing tests to verify no regression**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 6: Commit**

```bash
git add benchmark_platform/utils/challenge.py tests/test_level_gate.py
git commit -m "feat: level gate logic — get_current_level, is_level_unlocked"
```

---

## Task 4: Context Builder

**Files:**
- Create: `benchmark_platform/web/context.py`
- Create: `tests/test_web_context.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_web_context.py
"""Tests for web context builder functions."""
from benchmark_platform.base import Challenge, Difficulty, FlagState, TargetInfo
from benchmark_platform.web.context import dashboard_context, challenges_context
from benchmark_platform.web.submission_store import SubmissionRecord, SubmissionStore
from benchmark_platform.utils.challenge import ChallengeManager


def _make_challenge(code: str, level: int, solved: bool = False, flag_count: int = 1) -> Challenge:
    level_map = {1: Difficulty.EASY, 2: Difficulty.MEDIUM, 3: Difficulty.HARD}
    flags = []
    if flag_count > 1:
        flags = [FlagState(id=f"f{i}", route=f"/r{i}", description=f"flag {i}") for i in range(flag_count)]
    c = Challenge(
        challenge_code=code,
        difficulty=level_map[level],
        points={1: 200, 2: 300, 3: 500}[level],
        hint_viewed=False,
        solved=solved,
        target_info=TargetInfo(ip="localhost", port=[8080]),
        flag_states=flags,
    )
    c.set_benchmark_id(f"XBEN-{code}")
    return c


def _make_manager(challenges: list[Challenge]) -> ChallengeManager:
    mgr = ChallengeManager(
        benchmark_folders=[],
        benchmark_ids=[],
        public_accessible_host="localhost",
    )
    mgr.challenges = challenges
    for c in challenges:
        mgr._instance_status[c.challenge_code] = "stopped"
    return mgr


def test_dashboard_context_basic():
    mgr = _make_manager([
        _make_challenge("001", 1, solved=True),
        _make_challenge("002", 1, solved=False),
        _make_challenge("003", 2, solved=False),
    ])
    store = SubmissionStore()
    ctx = dashboard_context(mgr, store)
    assert ctx["total_challenges"] == 3
    assert ctx["solved_challenges"] == 1
    assert ctx["total_flags"] == 3
    assert ctx["total_points"] == 200 + 200 + 300
    assert ctx["earned_points"] == 200


def test_dashboard_context_difficulty_stats():
    mgr = _make_manager([
        _make_challenge("001", 1, solved=True),
        _make_challenge("002", 1, solved=False),
        _make_challenge("003", 2, solved=True),
    ])
    store = SubmissionStore()
    ctx = dashboard_context(mgr, store)
    diff = {d["difficulty"]: d for d in ctx["difficulty_stats"]}
    assert diff["easy"]["total"] == 2
    assert diff["easy"]["solved"] == 1
    assert diff["medium"]["total"] == 1
    assert diff["medium"]["solved"] == 1


def test_dashboard_context_level_progress():
    mgr = _make_manager([
        _make_challenge("001", 1, solved=True),
        _make_challenge("002", 1, solved=True),
        _make_challenge("003", 2, solved=False),
    ])
    store = SubmissionStore()
    ctx = dashboard_context(mgr, store)
    levels = {lp["level"]: lp for lp in ctx["level_progress"]}
    assert levels[1]["solved"] == 2
    assert levels[1]["total"] == 2
    assert levels[1]["unlocked"] is True
    assert levels[2]["unlocked"] is True
    assert levels[2]["solved"] == 0


def test_challenges_context_groups_by_level():
    mgr = _make_manager([
        _make_challenge("001", 1),
        _make_challenge("002", 2),
        _make_challenge("003", 1),
    ])
    ctx = challenges_context(mgr)
    assert len(ctx["level_groups"]) == 2
    assert ctx["level_groups"][0]["level"] == 1
    assert len(ctx["level_groups"][0]["challenges"]) == 2
    assert ctx["level_groups"][1]["level"] == 2


def test_challenges_context_includes_status():
    mgr = _make_manager([_make_challenge("001", 1)])
    mgr._instance_status["001"] = "running"
    ctx = challenges_context(mgr)
    card = ctx["level_groups"][0]["challenges"][0]
    assert card["instance_status"] == "running"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -m pytest tests/test_web_context.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'benchmark_platform.web.context'`

- [ ] **Step 3: Implement context.py**

```python
# benchmark_platform/web/context.py
"""Build template context dicts from ChallengeManager and SubmissionStore state."""
from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from benchmark_platform.utils.challenge import ChallengeManager
    from benchmark_platform.web.submission_store import SubmissionStore


def _challenge_to_card(manager: ChallengeManager, challenge) -> dict:
    bm = challenge.get_benchmark()
    status = manager.get_instance_status(challenge.challenge_code)
    entrypoint = None
    if status == "running":
        entrypoint = [
            f"{manager.public_accessible_host}:{p}" for p in challenge.target_info.port
        ]
    return {
        "challenge_code": challenge.challenge_code,
        "benchmark_id": challenge.get_benchmark_id(),
        "name": bm.name,
        "description": bm.description,
        "level": bm.level,
        "difficulty": challenge.difficulty.value,
        "points": challenge.points,
        "flag_count": challenge.flag_count,
        "solved_count": challenge.solved_count,
        "solved": challenge.solved,
        "hint_viewed": challenge.hint_viewed,
        "instance_status": status,
        "entrypoint": entrypoint,
        "flag_states": [
            {"id": fs.id, "route": fs.route, "description": fs.description, "solved": fs.solved}
            for fs in challenge.flag_states
        ],
    }


def dashboard_context(manager: ChallengeManager, store: SubmissionStore) -> dict:
    challenges = manager.challenges
    total_challenges = len(challenges)
    solved_challenges = sum(1 for c in challenges if c.solved)
    total_flags = sum(c.flag_count for c in challenges)
    solved_flags = sum(c.solved_count for c in challenges)
    total_points = sum(c.points for c in challenges)
    earned_points = sum(c.points for c in challenges if c.solved)
    running_count = sum(
        1 for c in challenges if manager.get_instance_status(c.challenge_code) == "running"
    )

    # Level progress
    levels_seen: dict[int, dict] = {}
    for c in challenges:
        lv = manager.get_level_for_challenge(c)
        if lv not in levels_seen:
            levels_seen[lv] = {"level": lv, "total": 0, "solved": 0, "unlocked": False}
        levels_seen[lv]["total"] += 1
        if c.solved:
            levels_seen[lv]["solved"] += 1
    for lv_data in levels_seen.values():
        lv_data["unlocked"] = manager.is_level_unlocked(lv_data["level"])
    level_progress = sorted(levels_seen.values(), key=lambda x: x["level"])

    # Difficulty stats
    diff_map: dict[str, dict] = {}
    for c in challenges:
        d = c.difficulty.value
        if d not in diff_map:
            diff_map[d] = {"difficulty": d, "total": 0, "solved": 0}
        diff_map[d]["total"] += 1
        if c.solved:
            diff_map[d]["solved"] += 1
    order = ["easy", "medium", "hard"]
    difficulty_stats = [diff_map[d] for d in order if d in diff_map]

    # Recent submissions
    recent = store.query(limit=10)

    return {
        "total_challenges": total_challenges,
        "solved_challenges": solved_challenges,
        "total_flags": total_flags,
        "solved_flags": solved_flags,
        "total_points": total_points,
        "earned_points": earned_points,
        "running_count": running_count,
        "level_progress": level_progress,
        "difficulty_stats": difficulty_stats,
        "recent_submissions": recent,
        "submission_total": store.total_count,
        "submission_correct": store.correct_count,
        "submission_incorrect": store.incorrect_count,
    }


def challenges_context(manager: ChallengeManager) -> dict:
    groups: dict[int, list[dict]] = {}
    for c in manager.challenges:
        lv = manager.get_level_for_challenge(c)
        if lv not in groups:
            groups[lv] = []
        groups[lv].append(_challenge_to_card(manager, c))

    level_groups = []
    for lv in sorted(groups.keys()):
        total = len(groups[lv])
        solved = sum(1 for card in groups[lv] if card["solved"])
        level_groups.append({
            "level": lv,
            "challenges": groups[lv],
            "total": total,
            "solved": solved,
            "all_solved": solved == total,
            "unlocked": manager.is_level_unlocked(lv),
        })

    return {
        "level_groups": level_groups,
        "total_challenges": len(manager.challenges),
        "total_flags": sum(c.flag_count for c in manager.challenges),
    }


def status_context(manager: ChallengeManager) -> dict:
    running = []
    stopped = []
    for c in manager.challenges:
        card = _challenge_to_card(manager, c)
        if card["instance_status"] == "running":
            running.append(card)
        else:
            stopped.append(card)
    return {
        "running": running,
        "stopped": stopped,
        "running_count": len(running),
        "stopped_count": len(stopped),
        "total": len(running) + len(stopped),
    }


def history_context(store: SubmissionStore, correct: bool | None = None, limit: int = 50, offset: int = 0) -> dict:
    records = store.query(correct=correct, limit=limit, offset=offset)
    return {
        "records": records,
        "total": store.total_count,
        "correct_count": store.correct_count,
        "incorrect_count": store.incorrect_count,
        "filter_correct": correct,
        "limit": limit,
        "offset": offset,
    }
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -m pytest tests/test_web_context.py -v`
Expected: All 6 tests PASS

- [ ] **Step 5: Commit**

```bash
git add benchmark_platform/web/context.py tests/test_web_context.py
git commit -m "feat: web context builder — dashboard, challenges, status, history"
```

---

## Task 5: Base Template, Sidebar, Routes & Server Integration

**Files:**
- Create: `benchmark_platform/web/routes.py`
- Create: `benchmark_platform/web/templates/base.html`
- Create: `benchmark_platform/web/templates/components/sidebar.html`
- Create: `benchmark_platform/web/templates/components/topbar.html`
- Create: `benchmark_platform/web/templates/components/toast.html`
- Modify: `benchmark_platform/server.py`
- Create: `tests/test_web_routes.py`

- [ ] **Step 1: Create routes.py**

```python
# benchmark_platform/web/routes.py
"""Web UI page routes and HTMX partial routes."""
from pathlib import Path

from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

from benchmark_platform.web.context import (
    challenges_context,
    dashboard_context,
    history_context,
    status_context,
)

_templates_dir = Path(__file__).parent / "templates"
templates = Jinja2Templates(directory=_templates_dir)

web_router = APIRouter()


def _get_manager(request: Request):
    return request.app.state.manager


def _get_store(request: Request):
    return request.app.state.submission_store


# ── Page routes ──────────────────────────────────────────────────────────────

@web_router.get("/dashboard")
async def page_dashboard(request: Request):
    manager = _get_manager(request)
    store = _get_store(request)
    ctx = dashboard_context(manager, store) if manager else {}
    return templates.TemplateResponse("pages/dashboard.html", {
        "request": request, "page": "dashboard", **ctx,
    })


@web_router.get("/challenges")
async def page_challenges(request: Request):
    manager = _get_manager(request)
    ctx = challenges_context(manager) if manager else {"level_groups": [], "total_challenges": 0, "total_flags": 0}
    return templates.TemplateResponse("pages/challenges.html", {
        "request": request, "page": "challenges", **ctx,
    })


@web_router.get("/history")
async def page_history(request: Request):
    store = _get_store(request)
    correct_filter = None
    ctx = history_context(store, correct=correct_filter) if store else {}
    return templates.TemplateResponse("pages/history.html", {
        "request": request, "page": "history", **ctx,
    })


@web_router.get("/status")
async def page_status(request: Request):
    manager = _get_manager(request)
    ctx = status_context(manager) if manager else {}
    return templates.TemplateResponse("pages/status.html", {
        "request": request, "page": "status", **ctx,
    })


# ── Partial routes (HTMX) ───────────────────────────────────────────────────

@web_router.get("/partials/dashboard_stats")
async def partial_dashboard_stats(request: Request):
    manager = _get_manager(request)
    store = _get_store(request)
    ctx = dashboard_context(manager, store) if manager else {}
    return templates.TemplateResponse("partials/dashboard_stats.html", {
        "request": request, **ctx,
    })


@web_router.get("/partials/challenge_card")
async def partial_challenge_card(request: Request, code: str):
    manager = _get_manager(request)
    if manager:
        from benchmark_platform.web.context import _challenge_to_card
        try:
            challenge = manager._find_by_code(code)
            card = _challenge_to_card(manager, challenge)
        except KeyError:
            card = None
    else:
        card = None
    return templates.TemplateResponse("partials/challenge_card_single.html", {
        "request": request, "card": card,
    })


@web_router.get("/partials/history_rows")
async def partial_history_rows(request: Request):
    store = _get_store(request)
    ctx = history_context(store) if store else {}
    return templates.TemplateResponse("partials/history_rows.html", {
        "request": request, **ctx,
    })


@web_router.get("/partials/status_table")
async def partial_status_table(request: Request):
    manager = _get_manager(request)
    ctx = status_context(manager) if manager else {}
    return templates.TemplateResponse("partials/status_table.html", {
        "request": request, **ctx,
    })
```

- [ ] **Step 2: Create base.html**

```html
{# benchmark_platform/web/templates/base.html #}
<!DOCTYPE html>
<html lang="zh-CN">
<head>
  <meta charset="UTF-8">
  <meta name="viewport" content="width=device-width, initial-scale=1.0">
  <title>{% block title %}Benchmark Platform{% endblock %}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <script src="https://unpkg.com/htmx.org@2.0.4"></script>
  <script defer src="https://unpkg.com/alpinejs@3.14.8/dist/cdn.min.js"></script>
  <link rel="stylesheet" href="/static/css/app.css">
</head>
<body class="bg-gray-50 min-h-screen flex" x-data>

  {% include "components/sidebar.html" %}

  <main class="flex-1 min-h-screen overflow-auto">
    {% include "components/topbar.html" %}
    <div class="p-6">
      {% block content %}{% endblock %}
    </div>
  </main>

  {% include "components/toast.html" %}

</body>
</html>
```

- [ ] **Step 3: Create sidebar.html**

```html
{# benchmark_platform/web/templates/components/sidebar.html #}
<aside class="w-56 bg-white border-r border-gray-100 min-h-screen flex flex-col flex-shrink-0">
  <!-- Logo -->
  <div class="px-4 py-5 border-b border-gray-100">
    <div class="flex items-center gap-2.5">
      <div class="w-8 h-8 rounded-lg bg-gradient-to-br from-rose-500 to-red-600 flex items-center justify-center">
        <span class="text-white font-bold text-[13px]">B</span>
      </div>
      <div>
        <div class="text-[13px] font-semibold text-gray-900">Benchmark</div>
        <div class="text-[10px] text-gray-400">Platform</div>
      </div>
    </div>
  </div>

  <!-- Navigation -->
  <nav class="flex-1 px-3 py-4 space-y-1 thin-scroll overflow-y-auto">
    <!-- Dashboard (top-level) -->
    <a href="/web/dashboard"
       class="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap
              {% if page == 'dashboard' %}bg-gray-900 text-white{% else %}text-gray-600 hover:bg-gray-50 cursor-pointer{% endif %}">
      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3.75 6A2.25 2.25 0 0 1 6 3.75h2.25A2.25 2.25 0 0 1 10.5 6v2.25a2.25 2.25 0 0 1-2.25 2.25H6a2.25 2.25 0 0 1-2.25-2.25V6ZM3.75 15.75A2.25 2.25 0 0 1 6 13.5h2.25a2.25 2.25 0 0 1 2.25 2.25V18a2.25 2.25 0 0 1-2.25 2.25H6A2.25 2.25 0 0 1 3.75 18v-2.25ZM13.5 6a2.25 2.25 0 0 1 2.25-2.25H18A2.25 2.25 0 0 1 20.25 6v2.25A2.25 2.25 0 0 1 18 10.5h-2.25a2.25 2.25 0 0 1-2.25-2.25V6ZM13.5 15.75a2.25 2.25 0 0 1 2.25-2.25H18a2.25 2.25 0 0 1 2.25 2.25V18A2.25 2.25 0 0 1 18 20.25h-2.25a2.25 2.25 0 0 1-2.25-2.25v-2.25Z"/>
      </svg>
      仪表盘
    </a>

    <!-- 赛题 group -->
    <div class="pt-3">
      <span class="px-2.5 text-[10px] uppercase tracking-wider font-semibold text-gray-400">赛题</span>
    </div>
    <a href="/web/challenges"
       class="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap
              {% if page == 'challenges' %}bg-gray-900 text-white{% else %}text-gray-600 hover:bg-gray-50 cursor-pointer{% endif %}">
      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M3 13.125C3 12.504 3.504 12 4.125 12h2.25c.621 0 1.125.504 1.125 1.125v6.75C7.5 20.496 6.996 21 6.375 21h-2.25A1.125 1.125 0 0 1 3 19.875v-6.75ZM9.75 8.625c0-.621.504-1.125 1.125-1.125h2.25c.621 0 1.125.504 1.125 1.125v11.25c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V8.625ZM16.5 4.125c0-.621.504-1.125 1.125-1.125h2.25C20.496 3 21 3.504 21 4.125v15.75c0 .621-.504 1.125-1.125 1.125h-2.25a1.125 1.125 0 0 1-1.125-1.125V4.125Z"/>
      </svg>
      题目列表
    </a>
    <a href="/web/history"
       class="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap
              {% if page == 'history' %}bg-gray-900 text-white{% else %}text-gray-600 hover:bg-gray-50 cursor-pointer{% endif %}">
      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M12 6v6h4.5m4.5 0a9 9 0 1 1-18 0 9 9 0 0 1 18 0Z"/>
      </svg>
      提交记录
    </a>

    <!-- 系统 group -->
    <div class="pt-3">
      <span class="px-2.5 text-[10px] uppercase tracking-wider font-semibold text-gray-400">系统</span>
    </div>
    <a href="/web/status"
       class="w-full flex items-center gap-2 px-2.5 py-2 rounded-lg text-[12px] font-medium transition-all whitespace-nowrap
              {% if page == 'status' %}bg-gray-900 text-white{% else %}text-gray-600 hover:bg-gray-50 cursor-pointer{% endif %}">
      <svg class="w-4 h-4" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor">
        <path stroke-linecap="round" stroke-linejoin="round" d="M5.25 14.25h13.5m-13.5 0a3 3 0 0 1-3-3m3 3a3 3 0 1 0 0 6h13.5a3 3 0 1 0 0-6m-16.5-3a3 3 0 0 1 3-3h13.5a3 3 0 0 1 3 3m-19.5 0a4.5 4.5 0 0 1 .9-2.7L5.737 5.1a3.375 3.375 0 0 1 2.7-1.35h7.126c1.062 0 2.062.5 2.7 1.35l2.587 3.45a4.5 4.5 0 0 1 .9 2.7m0 0a3 3 0 0 1-3 3m0 3h.008v.008h-.008v-.008Zm0-6h.008v.008h-.008v-.008Zm-3 6h.008v.008h-.008v-.008Zm0-6h.008v.008h-.008v-.008Z"/>
      </svg>
      实例状态
    </a>
  </nav>

  <!-- Bottom summary (HTMX refreshed) -->
  <div class="px-4 py-3 border-t border-gray-100 text-[11px] text-gray-500 space-y-1"
       hx-get="/web/partials/sidebar_summary" hx-trigger="every 5s" hx-swap="innerHTML">
    {% include "components/_sidebar_summary_content.html" ignore missing %}
  </div>
</aside>
```

- [ ] **Step 4: Create topbar.html**

```html
{# benchmark_platform/web/templates/components/topbar.html #}
{% set page_titles = {
  'dashboard': ('仪表盘', '比赛概览与统计'),
  'challenges': ('题目列表', '所有赛题管理'),
  'history': ('提交记录', 'Flag 提交历史'),
  'status': ('实例状态', '靶机容器运行状态'),
} %}
{% set title, subtitle = page_titles.get(page, ('Benchmark Platform', '')) %}
<div class="px-6 py-4 border-b border-gray-100 bg-white">
  <h1 class="text-lg font-semibold text-gray-900">{{ title }}</h1>
  {% if subtitle %}
  <p class="text-[12px] text-gray-500 mt-0.5">{{ subtitle }}</p>
  {% endif %}
</div>
```

- [ ] **Step 5: Create toast.html**

```html
{# benchmark_platform/web/templates/components/toast.html #}
<div x-data="{
       toasts: [],
       addToast(detail) {
         const id = Date.now();
         const colorMap = {
           success: 'bg-emerald-50 border-emerald-200 text-emerald-800',
           error: 'bg-red-50 border-red-200 text-red-800',
           warning: 'bg-amber-50 border-amber-200 text-amber-800',
           info: 'bg-blue-50 border-blue-200 text-blue-800',
         };
         this.toasts.push({id, message: detail.message, classes: colorMap[detail.type] || colorMap.info});
         setTimeout(() => this.toasts = this.toasts.filter(t => t.id !== id), 3000);
       }
     }"
     @toast.window="addToast($event.detail)"
     class="fixed top-4 right-4 z-[9999] flex flex-col gap-2 pointer-events-none" style="max-width: 380px;">
  <template x-for="toast in toasts" :key="toast.id">
    <div class="pointer-events-auto flex items-start gap-2.5 px-4 py-3 rounded-xl border shadow-lg animate-toast-in"
         :class="toast.classes">
      <span x-text="toast.message" class="text-[13px] font-medium"></span>
    </div>
  </template>
</div>
```

- [ ] **Step 6: Modify server.py to mount web router and static files**

In `benchmark_platform/server.py`, add imports at top:

```python
from pathlib import Path as _Path
from fastapi.staticfiles import StaticFiles
from benchmark_platform.web.routes import web_router
from benchmark_platform.web.submission_store import SubmissionStore
```

After `app = FastAPI()`, add:

```python
app.mount("/static", StaticFiles(directory=_Path(__file__).parent / "static"), name="static")
app.include_router(web_router, prefix="/web")
```

Change the root route from redirecting to `/docs` to:

```python
@app.get('/')
async def index():
    return RedirectResponse(url='/web/dashboard')
```

In the `serve()` function, after `manager = ChallengeManager(...)` and before `manager.start()`, add:

```python
    submission_store = SubmissionStore(
        log_path=_Path("logs/submissions.jsonl"),
    )
```

After `CHALLENGES = manager.challenges`, add:

```python
    app.state.manager = manager
    app.state.submission_store = submission_store
```

- [ ] **Step 7: Create minimal placeholder page templates**

Create all four page templates with minimal content so routes work. They will be fully built in later tasks.

```html
{# benchmark_platform/web/templates/pages/dashboard.html #}
{% extends "base.html" %}
{% block title %}仪表盘 — Benchmark Platform{% endblock %}
{% block content %}
<div class="text-[13px] text-gray-500">Dashboard — coming soon</div>
{% endblock %}
```

```html
{# benchmark_platform/web/templates/pages/challenges.html #}
{% extends "base.html" %}
{% block title %}题目列表 — Benchmark Platform{% endblock %}
{% block content %}
<div class="text-[13px] text-gray-500">Challenges — coming soon</div>
{% endblock %}
```

```html
{# benchmark_platform/web/templates/pages/history.html #}
{% extends "base.html" %}
{% block title %}提交记录 — Benchmark Platform{% endblock %}
{% block content %}
<div class="text-[13px] text-gray-500">History — coming soon</div>
{% endblock %}
```

```html
{# benchmark_platform/web/templates/pages/status.html #}
{% extends "base.html" %}
{% block title %}实例状态 — Benchmark Platform{% endblock %}
{% block content %}
<div class="text-[13px] text-gray-500">Status — coming soon</div>
{% endblock %}
```

Also create empty partials so partial routes don't error:

```html
{# benchmark_platform/web/templates/partials/dashboard_stats.html #}
<div></div>
```

```html
{# benchmark_platform/web/templates/partials/challenge_card_single.html #}
<div></div>
```

```html
{# benchmark_platform/web/templates/partials/history_rows.html #}
<tr></tr>
```

```html
{# benchmark_platform/web/templates/partials/status_table.html #}
<div></div>
```

- [ ] **Step 8: Write route integration tests**

```python
# tests/test_web_routes.py
"""Tests that web page routes return 200."""
from fastapi.testclient import TestClient

from benchmark_platform.server import app
from benchmark_platform.web.submission_store import SubmissionStore


def _init_app_state():
    """Set minimal app.state so routes don't crash."""
    app.state.manager = None
    app.state.submission_store = SubmissionStore()


def test_dashboard_returns_200():
    _init_app_state()
    client = TestClient(app)
    r = client.get("/web/dashboard")
    assert r.status_code == 200
    assert "仪表盘" in r.text


def test_challenges_returns_200():
    _init_app_state()
    client = TestClient(app)
    r = client.get("/web/challenges")
    assert r.status_code == 200


def test_history_returns_200():
    _init_app_state()
    client = TestClient(app)
    r = client.get("/web/history")
    assert r.status_code == 200


def test_status_returns_200():
    _init_app_state()
    client = TestClient(app)
    r = client.get("/web/status")
    assert r.status_code == 200


def test_root_redirects_to_dashboard():
    _init_app_state()
    client = TestClient(app, follow_redirects=False)
    r = client.get("/")
    assert r.status_code == 307
    assert "/web/dashboard" in r.headers["location"]
```

- [ ] **Step 9: Run all tests**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -m pytest tests/ -v`
Expected: All tests PASS

- [ ] **Step 10: Commit**

```bash
git add benchmark_platform/web/routes.py benchmark_platform/web/templates/ benchmark_platform/server.py benchmark_platform/static/ tests/test_web_routes.py
git commit -m "feat: web UI skeleton — base template, sidebar, routes, server integration"
```

---

## Task 6: Dashboard Page

**Files:**
- Modify: `benchmark_platform/web/templates/pages/dashboard.html`
- Create: `benchmark_platform/web/templates/partials/dashboard_stats.html` (replace placeholder)

- [ ] **Step 1: Build dashboard page template**

Replace the placeholder `pages/dashboard.html` with:

```html
{# benchmark_platform/web/templates/pages/dashboard.html #}
{% extends "base.html" %}
{% block title %}仪表盘 — Benchmark Platform{% endblock %}
{% block content %}
<div hx-get="/web/partials/dashboard_stats" hx-trigger="every 5s" hx-swap="innerHTML">
  {% include "partials/dashboard_stats.html" %}
</div>
{% endblock %}
```

- [ ] **Step 2: Build dashboard_stats partial**

Replace the placeholder `partials/dashboard_stats.html`:

```html
{# benchmark_platform/web/templates/partials/dashboard_stats.html #}

<!-- Stats cards -->
<div class="grid grid-cols-4 gap-4 mb-6">
  <!-- Total challenges -->
  <div class="bg-white rounded-xl border border-gray-100 p-5">
    <div class="text-[12px] text-gray-500">总题目</div>
    <div class="text-2xl font-semibold text-gray-900 mt-1">{{ total_challenges }}</div>
    <div class="text-[11px] text-gray-400 mt-1">{{ total_flags }} flags</div>
  </div>
  <!-- Solved -->
  <div class="bg-white rounded-xl border border-gray-100 p-5">
    <div class="text-[12px] text-gray-500">已解决</div>
    <div class="text-2xl font-semibold text-emerald-600 mt-1">{{ solved_challenges }}</div>
    <div class="text-[11px] text-gray-400 mt-1">
      {% if total_challenges > 0 %}{{ '%.1f' | format(solved_challenges / total_challenges * 100) }}%{% else %}0%{% endif %}
    </div>
  </div>
  <!-- Score -->
  <div class="bg-white rounded-xl border border-gray-100 p-5">
    <div class="text-[12px] text-gray-500">总得分</div>
    <div class="text-2xl font-semibold text-gray-900 mt-1">{{ earned_points }}<span class="text-[14px] text-gray-400">/{{ total_points }}</span></div>
    <div class="mt-2 h-1.5 bg-gray-200 rounded-full overflow-hidden">
      <div class="h-full bg-emerald-500 rounded-full" style="width: {% if total_points > 0 %}{{ earned_points / total_points * 100 }}%{% else %}0%{% endif %}"></div>
    </div>
  </div>
  <!-- Running -->
  <div class="bg-white rounded-xl border border-gray-100 p-5">
    <div class="text-[12px] text-gray-500">运行中实例</div>
    <div class="text-2xl font-semibold text-amber-600 mt-1">{{ running_count }}</div>
    <div class="text-[11px] text-gray-400 mt-1">/ {{ total_challenges }}</div>
  </div>
</div>

<div class="grid grid-cols-2 gap-4 mb-6">
  <!-- Level progress -->
  <div class="bg-white rounded-xl border border-gray-100 p-5">
    <div class="text-[15px] font-medium text-gray-900 mb-4">关卡进度</div>
    <div class="space-y-4">
      {% for lp in level_progress %}
      <div class="{% if not lp.unlocked %}opacity-40{% endif %}">
        <div class="flex items-center justify-between mb-1.5">
          <span class="text-[13px] font-medium text-gray-900">
            Level {{ lp.level }}
            {% if not lp.unlocked %}
            <svg class="w-3.5 h-3.5 inline ml-1 text-gray-400" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z"/></svg>
            {% endif %}
          </span>
          <span class="text-[12px] text-gray-500">{{ lp.solved }}/{{ lp.total }}</span>
        </div>
        <div class="h-2 bg-gray-200 rounded-full overflow-hidden">
          <div class="h-full bg-emerald-500 rounded-full transition-all" style="width: {% if lp.total > 0 %}{{ lp.solved / lp.total * 100 }}%{% else %}0%{% endif %}"></div>
        </div>
        {% if not lp.unlocked %}
        <div class="text-[11px] text-gray-400 mt-1">需通过 Level {{ lp.level - 1 }} 解锁</div>
        {% endif %}
      </div>
      {% endfor %}
      {% if not level_progress %}
      <div class="text-[13px] text-gray-400 text-center py-4">暂无赛题数据</div>
      {% endif %}
    </div>
  </div>

  <!-- Recent submissions -->
  <div class="bg-white rounded-xl border border-gray-100 p-5">
    <div class="text-[15px] font-medium text-gray-900 mb-4">最近提交</div>
    <div class="space-y-2">
      {% for sub in recent_submissions %}
      <div class="flex items-center gap-3 text-[12px]">
        <span class="text-gray-400 font-mono w-16 flex-shrink-0">{{ sub.timestamp[11:19] if sub.timestamp|length > 19 else sub.timestamp }}</span>
        <span class="text-gray-700 truncate flex-1">{{ sub.benchmark_id }}</span>
        {% if sub.correct %}
        <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-50 text-emerald-600">✓ 正确</span>
        {% else %}
        <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-red-50 text-red-600">✗ 错误</span>
        {% endif %}
      </div>
      {% endfor %}
      {% if not recent_submissions %}
      <div class="text-[13px] text-gray-400 text-center py-4">暂无提交记录</div>
      {% endif %}
    </div>
  </div>
</div>

<!-- Difficulty distribution -->
<div class="bg-white rounded-xl border border-gray-100 p-5">
  <div class="text-[15px] font-medium text-gray-900 mb-4">难度分布</div>
  <div class="space-y-3">
    {% set diff_labels = {'easy': 'Easy', 'medium': 'Medium', 'hard': 'Hard'} %}
    {% set diff_colors = {'easy': 'bg-emerald-500', 'medium': 'bg-amber-500', 'hard': 'bg-red-500'} %}
    {% for ds in difficulty_stats %}
    <div>
      <div class="flex items-center justify-between mb-1">
        <span class="text-[13px] font-medium text-gray-700">{{ diff_labels.get(ds.difficulty, ds.difficulty) }}</span>
        <span class="text-[12px] text-gray-500">{{ ds.solved }}/{{ ds.total }} &nbsp; {% if ds.total > 0 %}{{ '%.0f' | format(ds.solved / ds.total * 100) }}%{% else %}0%{% endif %}</span>
      </div>
      <div class="h-2 bg-gray-200 rounded-full overflow-hidden">
        <div class="h-full {{ diff_colors.get(ds.difficulty, 'bg-gray-500') }} rounded-full" style="width: {% if ds.total > 0 %}{{ ds.solved / ds.total * 100 }}%{% else %}0%{% endif %}"></div>
      </div>
    </div>
    {% endfor %}
  </div>
</div>
```

- [ ] **Step 3: Verify dashboard renders**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -m pytest tests/test_web_routes.py::test_dashboard_returns_200 -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add benchmark_platform/web/templates/pages/dashboard.html benchmark_platform/web/templates/partials/dashboard_stats.html
git commit -m "feat: dashboard page — stats cards, level progress, difficulty distribution"
```

---

## Task 7: Challenges Page + Modals

**Files:**
- Modify: `benchmark_platform/web/templates/pages/challenges.html`
- Create: `benchmark_platform/web/templates/components/challenge_card.html`
- Create: `benchmark_platform/web/templates/components/modal_submit.html`
- Modify: `benchmark_platform/web/templates/partials/challenge_card_single.html`

- [ ] **Step 1: Create challenge_card component**

```html
{# benchmark_platform/web/templates/components/challenge_card.html #}
{# Expects: card (dict from _challenge_to_card) #}
{% set diff_badge = {'easy': 'bg-emerald-50 text-emerald-600', 'medium': 'bg-amber-50 text-amber-600', 'hard': 'bg-red-50 text-red-600'} %}
{% set diff_label = {'easy': 'Easy', 'medium': 'Medium', 'hard': 'Hard'} %}

<div class="bg-white rounded-xl border border-gray-100 p-5 flex flex-col gap-3"
     id="card-{{ card.challenge_code }}">
  <!-- Header -->
  <div class="flex items-start justify-between">
    <div class="min-w-0">
      <div class="text-[11px] text-gray-400 font-mono">{{ card.benchmark_id }}</div>
      <div class="text-[15px] font-medium text-gray-900 truncate">{{ card.name }}</div>
    </div>
    <span class="flex-shrink-0 ml-2 px-2.5 py-1 text-[11px] font-medium rounded-full {{ diff_badge.get(card.difficulty, '') }}">
      {{ diff_label.get(card.difficulty, card.difficulty) }}
    </span>
  </div>

  <!-- Description -->
  <p class="text-[12px] text-gray-500 line-clamp-2">{{ card.description }}</p>

  <!-- Stats row -->
  <div class="flex items-center gap-4 text-[12px]">
    <span class="font-medium text-gray-900">{{ card.solved_count }}/{{ card.flag_count }} flags</span>
    {% if card.instance_status == 'running' %}
    <span class="text-emerald-600 flex items-center gap-1">
      <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> running
    </span>
    {% else %}
    <span class="text-gray-400 flex items-center gap-1">
      <span class="w-1.5 h-1.5 rounded-full bg-gray-300"></span> stopped
    </span>
    {% endif %}
    <span class="text-gray-500">{{ card.points }} pts</span>
    {% if card.solved %}
    <span class="inline-flex items-center px-2 py-0.5 rounded-full text-[11px] font-medium bg-emerald-50 text-emerald-600">✓ 已完成</span>
    {% endif %}
  </div>

  <!-- Multi-flag progress bar -->
  {% if card.flag_count > 1 %}
  <div class="flex gap-0.5">
    {% for fs in card.flag_states %}
    <div class="h-1.5 flex-1 rounded-full {{ 'bg-emerald-500' if fs.solved else 'bg-gray-200' }}"></div>
    {% endfor %}
  </div>
  {% endif %}

  <!-- Entrypoint links -->
  {% if card.entrypoint %}
  <div class="flex flex-wrap gap-2">
    {% for ep in card.entrypoint %}
    <a href="http://{{ ep }}" target="_blank"
       class="text-[11px] font-mono text-blue-600 hover:text-blue-700 hover:underline">
      {{ ep }}
    </a>
    {% endfor %}
  </div>
  {% endif %}

  <!-- Actions -->
  <div class="flex items-center gap-2 pt-2 border-t border-gray-100">
    {% if card.solved %}
    <span class="text-[12px] text-gray-400">全部完成</span>
    {% elif card.instance_status == 'running' %}
    <!-- Stop -->
    <button
      hx-post="/api/stop_challenge"
      hx-vals='{"code": "{{ card.challenge_code }}"}'
      hx-swap="none"
      hx-on::after-request="
        if(event.detail.successful) {
          $dispatch('toast', {type:'success', message:'靶机已停止'});
          htmx.ajax('GET', '/web/partials/challenge_card?code={{ card.challenge_code }}', '#card-{{ card.challenge_code }}');
        } else {
          $dispatch('toast', {type:'error', message:'停止失败'});
        }
      "
      class="h-8 px-3 text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 text-[12px] font-medium rounded-lg transition-colors cursor-pointer">
      停止
    </button>
    <!-- Submit Flag -->
    <button
      @click="$dispatch('open-submit-modal', {code: '{{ card.challenge_code }}', name: '{{ card.name }}', solved_count: {{ card.solved_count }}, flag_count: {{ card.flag_count }}})"
      class="h-8 px-3 bg-red-600 text-white text-[12px] font-medium rounded-lg hover:bg-red-700 transition-colors cursor-pointer">
      提交 Flag
    </button>
    <!-- Hint -->
    {% if not card.hint_viewed %}
    <button
      hx-post="/api/hint"
      hx-vals='{"code": "{{ card.challenge_code }}"}'
      hx-swap="none"
      hx-on::after-request="
        if(event.detail.successful) {
          const data = JSON.parse(event.detail.xhr.responseText);
          if(data.data && data.data.hint_content) {
            $dispatch('toast', {type:'info', message: data.data.hint_content});
          }
          htmx.ajax('GET', '/web/partials/challenge_card?code={{ card.challenge_code }}', '#card-{{ card.challenge_code }}');
        }
      "
      class="h-8 px-3 text-gray-500 hover:text-gray-700 text-[12px] font-medium rounded-lg hover:bg-gray-50 transition-colors cursor-pointer">
      查看提示
    </button>
    {% endif %}
    {% else %}
    <!-- Start -->
    <button
      hx-post="/api/start_challenge"
      hx-vals='{"code": "{{ card.challenge_code }}"}'
      hx-swap="none"
      hx-on::after-request="
        if(event.detail.successful) {
          $dispatch('toast', {type:'success', message:'靶机启动成功'});
          htmx.ajax('GET', '/web/partials/challenge_card?code={{ card.challenge_code }}', '#card-{{ card.challenge_code }}');
        } else {
          $dispatch('toast', {type:'error', message:'启动失败'});
        }
      "
      class="h-8 px-3 bg-gray-900 text-white text-[12px] font-medium rounded-lg hover:bg-gray-800 transition-colors cursor-pointer">
      启动
    </button>
    {% endif %}
  </div>
</div>
```

- [ ] **Step 2: Create modal_submit component**

```html
{# benchmark_platform/web/templates/components/modal_submit.html #}
<div x-data="{
       open: false,
       code: '',
       name: '',
       solved_count: 0,
       flag_count: 0,
       flag_value: '',
       submitting: false,
     }"
     @open-submit-modal.window="
       open = true;
       code = $event.detail.code;
       name = $event.detail.name;
       solved_count = $event.detail.solved_count;
       flag_count = $event.detail.flag_count;
       flag_value = '';
     "
     x-show="open"
     x-cloak
     class="fixed inset-0 z-50">
  <!-- Overlay -->
  <div class="fixed inset-0 bg-black/50 flex items-center justify-center p-4"
       @click.self="open = false">
    <!-- Modal -->
    <div class="bg-white rounded-xl shadow-xl w-full max-w-lg overflow-hidden" @click.stop>
      <!-- Header -->
      <div class="px-5 py-4 border-b border-gray-100 flex items-center justify-between">
        <h3 class="text-[15px] font-semibold text-gray-900">提交 Flag</h3>
        <button @click="open = false" class="w-8 h-8 flex items-center justify-center rounded-lg hover:bg-gray-100 text-gray-400 cursor-pointer">
          <svg class="w-5 h-5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M6 18 18 6M6 6l12 12"/></svg>
        </button>
      </div>
      <!-- Body -->
      <div class="px-5 py-4 space-y-4">
        <div>
          <div class="text-[13px] font-medium text-gray-900" x-text="name"></div>
          <div class="text-[12px] text-gray-500 mt-0.5">进度: <span x-text="solved_count"></span>/<span x-text="flag_count"></span> flags</div>
        </div>
        <input type="text" x-model="flag_value" placeholder="flag{...}"
               @keydown.enter="$refs.submitBtn.click()"
               class="w-full h-10 px-3 text-[13px] bg-gray-50 border-0 rounded-lg text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-red-500 focus:ring-offset-1 transition-shadow font-mono">
      </div>
      <!-- Footer -->
      <div class="px-5 py-4 bg-gray-50 flex justify-end gap-2">
        <button @click="open = false"
                class="h-10 px-5 text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 text-[13px] font-medium rounded-lg transition-colors cursor-pointer">
          取消
        </button>
        <button x-ref="submitBtn"
                :disabled="submitting || !flag_value.trim()"
                @click="
                  submitting = true;
                  fetch('/api/submit', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({code: code, flag: flag_value.trim()})
                  })
                  .then(r => r.json())
                  .then(data => {
                    submitting = false;
                    if(data.data && data.data.correct) {
                      $dispatch('toast', {type:'success', message: data.data.message || '恭喜！答案正确'});
                      open = false;
                    } else {
                      $dispatch('toast', {type:'error', message: (data.data && data.data.message) || '答案错误'});
                    }
                    htmx.ajax('GET', '/web/partials/challenge_card?code=' + code, '#card-' + code);
                  })
                  .catch(() => {
                    submitting = false;
                    $dispatch('toast', {type:'error', message:'提交失败'});
                  });
                "
                class="h-10 px-5 bg-red-600 text-white text-[13px] font-medium rounded-lg hover:bg-red-700 transition-colors cursor-pointer disabled:opacity-50 disabled:cursor-not-allowed">
          <span x-show="!submitting">提交</span>
          <span x-show="submitting" class="flex items-center gap-1.5">
            <svg class="w-3.5 h-3.5 animate-spin" fill="none" viewBox="0 0 24 24"><circle class="opacity-25" cx="12" cy="12" r="10" stroke="currentColor" stroke-width="4"/><path class="opacity-75" fill="currentColor" d="M4 12a8 8 0 018-8V0C5.373 0 0 5.373 0 12h4z"/></svg>
            提交中...
          </span>
        </button>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Build challenges page template**

Replace `pages/challenges.html`:

```html
{# benchmark_platform/web/templates/pages/challenges.html #}
{% extends "base.html" %}
{% block title %}题目列表 — Benchmark Platform{% endblock %}
{% block content %}
<!-- Filter bar -->
<div class="flex items-center justify-between mb-6" x-data="{filter: 'all', search: ''}">
  <div class="text-[13px] text-gray-500">
    共 {{ total_challenges }} 题 · {{ total_flags }} flags
  </div>
  <div class="flex items-center gap-3">
    <select x-model="filter" @change="$dispatch('filter-change', {filter, search})"
            class="h-9 px-3 text-[12px] bg-gray-50 border-0 rounded-lg text-gray-900 focus:ring-2 focus:ring-gray-900 cursor-pointer">
      <option value="all">全部</option>
      <option value="unsolved">未解决</option>
      <option value="solved">已解决</option>
      <option value="running">运行中</option>
    </select>
    <input type="text" x-model="search" @input.debounce.300ms="$dispatch('filter-change', {filter, search})"
           placeholder="搜索题目..."
           class="h-9 w-48 px-3 text-[12px] bg-gray-50 border-0 rounded-lg text-gray-900 placeholder-gray-400 focus:ring-2 focus:ring-gray-900 transition-shadow">
  </div>
</div>

<!-- Level groups -->
<div class="space-y-8" x-data
     @filter-change.window="
       const f = $event.detail.filter;
       const s = $event.detail.search.toLowerCase();
       document.querySelectorAll('[data-challenge-card]').forEach(el => {
         const d = el.dataset;
         let show = true;
         if(f === 'solved' && d.solved !== 'true') show = false;
         if(f === 'unsolved' && d.solved === 'true') show = false;
         if(f === 'running' && d.status !== 'running') show = false;
         if(s && !d.name.toLowerCase().includes(s) && !d.benchmarkId.toLowerCase().includes(s)) show = false;
         el.style.display = show ? '' : 'none';
       });
     ">
  {% for lg in level_groups %}
  <div>
    <!-- Level header -->
    <div class="flex items-center gap-3 mb-4">
      <h2 class="text-[15px] font-semibold text-gray-900">Level {{ lg.level }}</h2>
      <span class="text-[12px] text-gray-500">{{ lg.solved }}/{{ lg.total }}</span>
      {% if lg.all_solved %}
      <span class="px-2 py-0.5 text-[11px] font-medium rounded-full bg-emerald-50 text-emerald-600">✓ 已通过</span>
      {% endif %}
      {% if not lg.unlocked %}
      <span class="px-2 py-0.5 text-[11px] font-medium rounded-full bg-gray-100 text-gray-500">
        <svg class="w-3 h-3 inline mr-0.5" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M16.5 10.5V6.75a4.5 4.5 0 1 0-9 0v3.75m-.75 11.25h10.5a2.25 2.25 0 0 0 2.25-2.25v-6.75a2.25 2.25 0 0 0-2.25-2.25H6.75a2.25 2.25 0 0 0-2.25 2.25v6.75a2.25 2.25 0 0 0 2.25 2.25Z"/></svg>
        需通过 Level {{ lg.level - 1 }} 解锁
      </span>
      {% endif %}
    </div>

    <!-- Cards grid -->
    <div class="grid grid-cols-3 gap-4 {% if not lg.unlocked %}opacity-40 pointer-events-none{% endif %}">
      {% for card in lg.challenges %}
      <div data-challenge-card
           data-solved="{{ 'true' if card.solved else 'false' }}"
           data-status="{{ card.instance_status }}"
           data-name="{{ card.name }}"
           data-benchmark-id="{{ card.benchmark_id }}">
        {% include "components/challenge_card.html" %}
      </div>
      {% endfor %}
    </div>
  </div>
  {% endfor %}

  {% if not level_groups %}
  <div class="px-5 py-8 text-center text-[13px] text-gray-400">暂无赛题数据，请检查服务器启动参数</div>
  {% endif %}
</div>

{% include "components/modal_submit.html" %}
{% endblock %}
```

- [ ] **Step 4: Update challenge_card_single partial**

Replace `partials/challenge_card_single.html`:

```html
{# benchmark_platform/web/templates/partials/challenge_card_single.html #}
{% if card %}
{% include "components/challenge_card.html" %}
{% endif %}
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -m pytest tests/test_web_routes.py -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add benchmark_platform/web/templates/
git commit -m "feat: challenges page — cards by level, flag submit modal, filters"
```

---

## Task 8: SubmissionStore API Integration

**Files:**
- Modify: `benchmark_platform/server.py`

- [ ] **Step 1: Wire SubmissionStore into tch_submit**

In `benchmark_platform/server.py`, find the `tch_submit` function. After the line `return _ok({...})` at the end of the function, insert submission recording **before** the return. The modified function body after the `is_correct` block should end with:

```python
    # Record submission
    from datetime import datetime, timezone as _tz
    from benchmark_platform.web.submission_store import SubmissionRecord
    if hasattr(app.state, 'submission_store') and app.state.submission_store is not None:
        bm = challenge.get_benchmark()
        app.state.submission_store.add(SubmissionRecord(
            timestamp=datetime.now(_tz.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            challenge_code=payload.code,
            benchmark_id=challenge.get_benchmark_id(),
            challenge_name=bm.name,
            flag_id=matched_flag_id,
            flag_value=payload.flag[:8] + "..." + payload.flag[-4:] if len(payload.flag) > 16 else payload.flag,
            correct=is_correct,
            points=challenge.points if is_correct and matched_flag_id else 0,
        ))

    return _ok({
        "correct": is_correct,
        "flag_id": matched_flag_id,
        "message": "恭喜！答案正确" if is_correct else "答案错误，请继续尝试",
        "flag_count": challenge.flag_count,
        "flag_got_count": challenge.solved_count,
        "all_solved": challenge.solved,
    })
```

- [ ] **Step 2: Run existing tests**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 3: Commit**

```bash
git add benchmark_platform/server.py
git commit -m "feat: record submissions in SubmissionStore on /api/submit"
```

---

## Task 9: History Page

**Files:**
- Modify: `benchmark_platform/web/templates/pages/history.html`
- Modify: `benchmark_platform/web/templates/partials/history_rows.html`

- [ ] **Step 1: Build history page**

Replace `pages/history.html`:

```html
{# benchmark_platform/web/templates/pages/history.html #}
{% extends "base.html" %}
{% block title %}提交记录 — Benchmark Platform{% endblock %}
{% block content %}
<!-- Summary bar -->
<div class="flex items-center justify-between mb-6">
  <div class="text-[13px] text-gray-500">
    共 {{ total }} 次提交 · <span class="text-emerald-600">{{ correct_count }} 正确</span> · <span class="text-red-500">{{ incorrect_count }} 错误</span>
  </div>
</div>

<!-- Table -->
<div class="bg-white rounded-xl border border-gray-100 overflow-hidden">
  <table class="w-full">
    <thead class="bg-gray-50 border-b border-gray-100">
      <tr>
        <th class="px-4 py-3 text-left text-[12px] font-medium text-gray-500">时间</th>
        <th class="px-4 py-3 text-left text-[12px] font-medium text-gray-500">题目</th>
        <th class="px-4 py-3 text-left text-[12px] font-medium text-gray-500">Flag ID</th>
        <th class="px-4 py-3 text-left text-[12px] font-medium text-gray-500">提交值</th>
        <th class="px-4 py-3 text-left text-[12px] font-medium text-gray-500">结果</th>
        <th class="px-4 py-3 text-right text-[12px] font-medium text-gray-500">得分</th>
      </tr>
    </thead>
    <tbody class="divide-y divide-gray-100" hx-get="/web/partials/history_rows" hx-trigger="every 3s" hx-swap="innerHTML">
      {% include "partials/history_rows.html" %}
    </tbody>
  </table>
</div>

{% if not records %}
<div class="px-5 py-8 text-center text-[13px] text-gray-400">暂无提交记录</div>
{% endif %}
{% endblock %}
```

- [ ] **Step 2: Build history_rows partial**

Replace `partials/history_rows.html`:

```html
{# benchmark_platform/web/templates/partials/history_rows.html #}
{% for r in records %}
<tr class="hover:bg-gray-50">
  <td class="px-4 py-3 text-[13px] text-gray-900 font-mono whitespace-nowrap">
    {{ r.timestamp[11:19] if r.timestamp|length > 19 else r.timestamp }}
  </td>
  <td class="px-4 py-3">
    <div class="text-[13px] text-gray-900">{{ r.challenge_name }}</div>
    <div class="text-[11px] text-gray-400 font-mono">{{ r.benchmark_id }}</div>
  </td>
  <td class="px-4 py-3 text-[12px] text-gray-500 font-mono">
    {{ r.flag_id or '—' }}
  </td>
  <td class="px-4 py-3 text-[12px] text-gray-400 font-mono">
    {{ r.flag_value }}
  </td>
  <td class="px-4 py-3">
    {% if r.correct %}
    <span class="inline-flex items-center px-2.5 py-1 text-[11px] font-medium rounded-full bg-emerald-50 text-emerald-600">✓ 正确</span>
    {% else %}
    <span class="inline-flex items-center px-2.5 py-1 text-[11px] font-medium rounded-full bg-red-50 text-red-600">✗ 错误</span>
    {% endif %}
  </td>
  <td class="px-4 py-3 text-right">
    {% if r.correct %}
    <span class="text-[13px] font-medium text-emerald-600">+{{ r.points }}</span>
    {% else %}
    <span class="text-[13px] text-gray-400">—</span>
    {% endif %}
  </td>
</tr>
{% endfor %}
```

- [ ] **Step 3: Run tests**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -m pytest tests/test_web_routes.py::test_history_returns_200 -v`
Expected: PASS

- [ ] **Step 4: Commit**

```bash
git add benchmark_platform/web/templates/pages/history.html benchmark_platform/web/templates/partials/history_rows.html
git commit -m "feat: history page — submission table with auto-refresh"
```

---

## Task 10: Status Page + Stop All

**Files:**
- Modify: `benchmark_platform/web/templates/pages/status.html`
- Create: `benchmark_platform/web/templates/components/modal_confirm.html`
- Modify: `benchmark_platform/web/templates/partials/status_table.html`
- Modify: `benchmark_platform/server.py` — add `/api/stop_all` endpoint

- [ ] **Step 1: Add /api/stop_all endpoint in server.py**

Add after the `tch_hint` route in `server.py`:

```python
@app.post("/api/stop_all")
async def tch_stop_all():
    if manager is None:
        _err("Server not initialized", 503)
        return

    stopped = []
    for c in manager.challenges:
        if manager.get_instance_status(c.challenge_code) == "running":
            try:
                manager.stop_challenge_instance(c.challenge_code)
                stopped.append(c.challenge_code)
            except Exception:
                pass
    return _ok({"stopped_count": len(stopped)}, f"已停止 {len(stopped)} 个实例")
```

- [ ] **Step 2: Create modal_confirm component**

```html
{# benchmark_platform/web/templates/components/modal_confirm.html #}
<div x-data="{open: false, action: null, message: '', onConfirm: null}"
     @open-confirm-modal.window="
       open = true;
       message = $event.detail.message;
       onConfirm = $event.detail.onConfirm;
     "
     x-show="open" x-cloak class="fixed inset-0 z-50">
  <div class="fixed inset-0 bg-black/50 flex items-center justify-center p-4" @click.self="open = false">
    <div class="bg-white rounded-xl shadow-xl w-full max-w-sm overflow-hidden" @click.stop>
      <div class="px-5 py-5">
        <div class="flex items-start gap-3">
          <div class="w-10 h-10 rounded-full bg-amber-100 flex items-center justify-center flex-shrink-0">
            <svg class="w-5 h-5 text-amber-600" fill="none" viewBox="0 0 24 24" stroke-width="2" stroke="currentColor"><path stroke-linecap="round" stroke-linejoin="round" d="M12 9v3.75m-9.303 3.376c-.866 1.5.217 3.374 1.948 3.374h14.71c1.73 0 2.813-1.874 1.948-3.374L13.949 3.378c-.866-1.5-3.032-1.5-3.898 0L2.697 16.126ZM12 15.75h.007v.008H12v-.008Z"/></svg>
          </div>
          <div>
            <h3 class="text-[15px] font-semibold text-gray-900">确认操作</h3>
            <p class="text-[13px] text-gray-500 mt-1" x-text="message"></p>
          </div>
        </div>
      </div>
      <div class="px-5 py-4 bg-gray-50 flex justify-end gap-2">
        <button @click="open = false"
                class="h-10 px-5 text-gray-700 bg-white border border-gray-300 hover:bg-gray-50 text-[13px] font-medium rounded-lg transition-colors cursor-pointer">
          取消
        </button>
        <button @click="if(onConfirm) onConfirm(); open = false;"
                class="h-10 px-5 bg-red-500 text-white text-[13px] font-medium rounded-lg hover:bg-red-600 transition-colors cursor-pointer">
          确认
        </button>
      </div>
    </div>
  </div>
</div>
```

- [ ] **Step 3: Build status page**

Replace `pages/status.html`:

```html
{# benchmark_platform/web/templates/pages/status.html #}
{% extends "base.html" %}
{% block title %}实例状态 — Benchmark Platform{% endblock %}
{% block content %}
<div x-data>
  <!-- Top bar -->
  <div class="flex items-center justify-between mb-6">
    <div class="text-[13px] text-gray-500">
      <span class="text-emerald-600 font-medium">{{ running_count }} 运行中</span> ·
      {{ stopped_count }} 已停止
    </div>
    <div class="flex gap-2">
      {% if running_count > 0 %}
      <button
        @click="$dispatch('open-confirm-modal', {
          message: '确认停止所有运行中的靶机实例？',
          onConfirm: () => {
            fetch('/api/stop_all', {method:'POST'})
              .then(r => r.json())
              .then(data => {
                $dispatch('toast', {type:'success', message: data.message});
                htmx.ajax('GET', '/web/partials/status_table', '#status-table-body');
              });
          }
        })"
        class="h-9 px-4 bg-red-500 text-white text-[12px] font-medium rounded-lg hover:bg-red-600 transition-colors cursor-pointer">
        全部停止
      </button>
      {% endif %}
    </div>
  </div>

  <!-- Table -->
  <div class="bg-white rounded-xl border border-gray-100 overflow-hidden">
    <table class="w-full">
      <thead class="bg-gray-50 border-b border-gray-100">
        <tr>
          <th class="px-4 py-3 text-left text-[12px] font-medium text-gray-500">题目</th>
          <th class="px-4 py-3 text-left text-[12px] font-medium text-gray-500">Benchmark ID</th>
          <th class="px-4 py-3 text-left text-[12px] font-medium text-gray-500">端口映射</th>
          <th class="px-4 py-3 text-left text-[12px] font-medium text-gray-500">状态</th>
          <th class="px-4 py-3 text-right text-[12px] font-medium text-gray-500">操作</th>
        </tr>
      </thead>
      <tbody class="divide-y divide-gray-100" id="status-table-body"
             hx-get="/web/partials/status_table" hx-trigger="every 5s" hx-swap="innerHTML">
        {% include "partials/status_table.html" %}
      </tbody>
    </table>
  </div>
</div>

{% include "components/modal_confirm.html" %}
{% endblock %}
```

- [ ] **Step 4: Build status_table partial**

Replace `partials/status_table.html`:

```html
{# benchmark_platform/web/templates/partials/status_table.html #}
{% for card in running %}
<tr class="hover:bg-gray-50">
  <td class="px-4 py-3">
    <div class="text-[13px] text-gray-900">{{ card.name }}</div>
    <div class="text-[11px] text-gray-400 font-mono">{{ card.challenge_code[:12] }}...</div>
  </td>
  <td class="px-4 py-3 text-[13px] font-mono text-purple-600">{{ card.benchmark_id }}</td>
  <td class="px-4 py-3">
    {% if card.entrypoint %}
    {% for ep in card.entrypoint %}
    <a href="http://{{ ep }}" target="_blank" class="block text-[12px] font-mono text-blue-600 hover:text-blue-700 hover:underline">{{ ep }}</a>
    {% endfor %}
    {% else %}
    <span class="text-[12px] text-gray-400">—</span>
    {% endif %}
  </td>
  <td class="px-4 py-3">
    <span class="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded-full bg-emerald-50 text-emerald-600">
      <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> running
    </span>
  </td>
  <td class="px-4 py-3 text-right">
    <button
      hx-post="/api/stop_challenge"
      hx-vals='{"code": "{{ card.challenge_code }}"}'
      hx-swap="none"
      hx-on::after-request="
        $dispatch('toast', {type:'success', message:'已停止'});
        htmx.ajax('GET', '/web/partials/status_table', '#status-table-body');
      "
      class="text-[12px] text-gray-500 hover:text-gray-600 cursor-pointer">停止</button>
    {% if card.entrypoint %}
    <a href="http://{{ card.entrypoint[0] }}" target="_blank" class="ml-3 text-[12px] text-emerald-600 hover:text-emerald-700 cursor-pointer">访问</a>
    {% endif %}
  </td>
</tr>
{% endfor %}

{% if stopped %}
<tr>
  <td colspan="5" class="px-4 py-2" x-data="{expanded: false}">
    <button @click="expanded = !expanded" class="text-[12px] text-gray-500 hover:text-gray-700 cursor-pointer">
      <span x-text="expanded ? '▾' : '▸'"></span> 已停止 ({{ stopped|length }})
    </button>
    <table x-show="expanded" class="w-full mt-2">
      <tbody class="divide-y divide-gray-100">
        {% for card in stopped %}
        <tr class="hover:bg-gray-50">
          <td class="px-4 py-2">
            <div class="text-[13px] text-gray-900">{{ card.name }}</div>
          </td>
          <td class="px-4 py-2 text-[13px] font-mono text-purple-600">{{ card.benchmark_id }}</td>
          <td class="px-4 py-2 text-[12px] text-gray-400">—</td>
          <td class="px-4 py-2">
            <span class="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded-full bg-gray-50 text-gray-500">
              <span class="w-1.5 h-1.5 rounded-full bg-gray-300"></span> stopped
            </span>
          </td>
          <td class="px-4 py-2 text-right">
            <button
              hx-post="/api/start_challenge"
              hx-vals='{"code": "{{ card.challenge_code }}"}'
              hx-swap="none"
              hx-on::after-request="
                $dispatch('toast', {type:'success', message:'靶机启动成功'});
                htmx.ajax('GET', '/web/partials/status_table', '#status-table-body');
              "
              class="text-[12px] text-emerald-600 hover:text-emerald-700 cursor-pointer">启动</button>
          </td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </td>
</tr>
{% endif %}
```

- [ ] **Step 5: Run tests**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -m pytest tests/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add benchmark_platform/server.py benchmark_platform/web/templates/
git commit -m "feat: status page — instance table, stop-all with confirm modal"
```

---

## Task 11: Sidebar Summary Partial

**Files:**
- Create: `benchmark_platform/web/templates/components/_sidebar_summary_content.html`
- Modify: `benchmark_platform/web/routes.py` — add sidebar summary partial route

- [ ] **Step 1: Create sidebar summary content**

```html
{# benchmark_platform/web/templates/components/_sidebar_summary_content.html #}
<div class="flex items-center gap-1.5">
  <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span>
  运行中 {{ running_count|default(0) }}/{{ total_challenges|default(0) }}
</div>
<div class="flex items-center gap-1.5">
  <span class="w-1.5 h-1.5 rounded-full bg-gray-400"></span>
  已解决 {{ solved_flags|default(0) }}/{{ total_flags|default(0) }}
</div>
```

- [ ] **Step 2: Add sidebar partial route**

In `benchmark_platform/web/routes.py`, add:

```python
@web_router.get("/partials/sidebar_summary")
async def partial_sidebar_summary(request: Request):
    manager = _get_manager(request)
    if manager:
        running_count = sum(
            1 for c in manager.challenges
            if manager.get_instance_status(c.challenge_code) == "running"
        )
        ctx = {
            "running_count": running_count,
            "total_challenges": len(manager.challenges),
            "solved_flags": sum(c.solved_count for c in manager.challenges),
            "total_flags": sum(c.flag_count for c in manager.challenges),
        }
    else:
        ctx = {}
    return templates.TemplateResponse("components/_sidebar_summary_content.html", {
        "request": request, **ctx,
    })
```

- [ ] **Step 3: Commit**

```bash
git add benchmark_platform/web/templates/components/_sidebar_summary_content.html benchmark_platform/web/routes.py
git commit -m "feat: sidebar summary partial — running/solved counts with auto-refresh"
```

---

## Task 12: End-to-End Validation

- [ ] **Step 1: Run all tests**

Run: `cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform && python -m pytest tests/ -v`
Expected: All tests PASS (submission_store, level_gate, web_context, web_routes, multi_flag)

- [ ] **Step 2: Start the server with a few challenges**

Run:
```bash
cd /Users/f0x/pte-project/weaponize/infra/benchmark-platform
python -m benchmark_platform.server serve \
  --benchmark-folder challenges \
  -i XBEN-001-24 \
  -i XBEN-005-24 \
  -i XBOW-XSS-A
```

Expected: Server starts on port 8000, prints challenge summary table.

- [ ] **Step 3: Verify Web UI in browser**

Open `http://localhost:8000` in browser. Check:
- [ ] Redirects to `/web/dashboard`
- [ ] Sidebar shows with correct nav items
- [ ] Dashboard shows stats cards (3 challenges, 0 solved, 0 running)
- [ ] Click "题目列表" → challenges page with 3 cards grouped by level
- [ ] Click "提交记录" → empty history table
- [ ] Click "实例状态" → status page with all stopped

- [ ] **Step 4: Test challenge lifecycle**

In the browser:
- [ ] Click "启动" on XBEN-001-24 → Toast "靶机启动成功", card shows running + entrypoint link
- [ ] Click entrypoint link → opens challenge in new tab
- [ ] Click "提交 Flag" → modal opens
- [ ] Submit wrong flag → Toast "答案错误"
- [ ] Navigate to History → see the failed submission record
- [ ] Navigate to Status → see XBEN-001-24 running with port link
- [ ] Navigate back to Dashboard → stats updated (1 running)

- [ ] **Step 5: Verify API still works for pojun**

In another terminal:
```bash
curl -s http://localhost:8000/api/challenges | python3 -m json.tool | head -20
```

Expected: JSON response with `code: 0` and challenge list — same as before the web UI was added.

- [ ] **Step 6: Stop server and commit any fixes**

If any fixes were needed during validation:
```bash
git add -u
git commit -m "fix: end-to-end validation fixes for web UI"
```
