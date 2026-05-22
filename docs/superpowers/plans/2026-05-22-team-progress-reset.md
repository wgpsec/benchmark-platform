# Team Progress Reset Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Split team progress reset into separate CTF and knowledge quiz reset actions in team management.

**Architecture:** Add two DB functions that delete scoped `team_progress` rows using quiz benchmark IDs as the boundary between MCQ and CTF data. Expose two web API endpoints and replace the generic team reset UI with two explicit buttons. Submission history remains untouched.

**Tech Stack:** Python 3.9, FastAPI, SQLite, Jinja2, Alpine.js, pytest, FastAPI TestClient.

---

## Files

- Modify: `benchmark_platform/db.py`
  - Add `reset_team_ctf_progress(team_id, quiz_benchmark_ids)`.
  - Add `reset_team_quiz_progress(team_id, quiz_benchmark_ids)`.
  - Keep `reset_team_progress(team_id)` for compatibility.
- Modify: `benchmark_platform/web/routes.py`
  - Add `POST /web/api/teams/reset-ctf`.
  - Add `POST /web/api/teams/reset-quiz`.
- Modify: `benchmark_platform/web/templates/pages/teams.html`
  - Replace one generic reset button with two explicit buttons.
  - Replace `resetTeam(team)` with `resetCtfProgress(team)` and `resetQuizProgress(team)`.
- Modify: `tests/test_db.py`
  - Add DB-level tests for scoped reset behavior.
- Modify: `tests/test_quiz_api.py`
  - Add web page/API tests for button labels and endpoint behavior.

---

### Task 1: Add scoped reset DB functions

**Files:**
- Modify: `tests/test_db.py`
- Modify: `benchmark_platform/db.py`

- [ ] **Step 1: Write failing DB tests**

In `tests/test_db.py`, update the import block to include the new functions:

```python
from benchmark_platform.db import (
    init_db, create_team, list_teams, get_team_by_token,
    get_or_create_default_team, mark_flag_solved,
    get_team_solved_count, is_hint_viewed, mark_hint_viewed,
    get_team_progress, reset_team_progress, _set_db_path,
    reset_team_ctf_progress, reset_team_quiz_progress,
    upsert_instance, get_instance_by_benchmark_id, get_running_instances,
    get_expired_instances, delete_instance,
    get_instance_timeout_config, set_instance_timeout_config,
    get_instance_by_benchmark_and_team,
    get_team_running_count, get_all_instances,
    update_instance_status_by_team,
)
```

Add these tests after `test_reset_team_progress`:

```python
def test_reset_team_ctf_progress_preserves_quiz_progress():
    team = create_team("Team1")
    mark_flag_solved(team["id"], "XBEN-001-24", "flag1")
    mark_flag_solved(team["id"], "SAMPLE-QUIZ-001", "q1")
    mark_hint_viewed(team["id"], "XBEN-001-24")

    reset_team_ctf_progress(team["id"], ["SAMPLE-QUIZ-001"])

    assert get_team_solved_count(team["id"], "XBEN-001-24") == 0
    assert get_team_solved_count(team["id"], "SAMPLE-QUIZ-001") == 1
    assert is_hint_viewed(team["id"], "XBEN-001-24") is False


def test_reset_team_quiz_progress_preserves_ctf_progress_and_hints():
    team = create_team("Team1")
    mark_flag_solved(team["id"], "XBEN-001-24", "flag1")
    mark_flag_solved(team["id"], "SAMPLE-QUIZ-001", "q1")
    mark_hint_viewed(team["id"], "XBEN-001-24")

    reset_team_quiz_progress(team["id"], ["SAMPLE-QUIZ-001"])

    assert get_team_solved_count(team["id"], "XBEN-001-24") == 1
    assert get_team_solved_count(team["id"], "SAMPLE-QUIZ-001") == 0
    assert is_hint_viewed(team["id"], "XBEN-001-24") is True
```

- [ ] **Step 2: Run DB tests to verify they fail**

Run:

```bash
python -m pytest tests/test_db.py::test_reset_team_ctf_progress_preserves_quiz_progress tests/test_db.py::test_reset_team_quiz_progress_preserves_ctf_progress_and_hints -v
```

Expected: FAIL during import with `ImportError: cannot import name 'reset_team_ctf_progress'` or similar missing-function error.

- [ ] **Step 3: Implement DB functions**

In `benchmark_platform/db.py`, add these functions near `reset_team_progress`:

```python
def reset_team_ctf_progress(team_id: str, quiz_benchmark_ids: list[str]) -> None:
    conn = _get_conn()
    if quiz_benchmark_ids:
        placeholders = ",".join("?" for _ in quiz_benchmark_ids)
        conn.execute(
            f"DELETE FROM team_progress WHERE team_id = ? AND benchmark_id NOT IN ({placeholders})",
            (team_id, *quiz_benchmark_ids),
        )
    else:
        conn.execute("DELETE FROM team_progress WHERE team_id = ?", (team_id,))
    conn.execute("DELETE FROM team_hints WHERE team_id = ?", (team_id,))
    conn.commit()


def reset_team_quiz_progress(team_id: str, quiz_benchmark_ids: list[str]) -> None:
    conn = _get_conn()
    if not quiz_benchmark_ids:
        return
    placeholders = ",".join("?" for _ in quiz_benchmark_ids)
    conn.execute(
        f"DELETE FROM team_progress WHERE team_id = ? AND benchmark_id IN ({placeholders})",
        (team_id, *quiz_benchmark_ids),
    )
    conn.commit()
```

- [ ] **Step 4: Run DB tests to verify they pass**

Run:

```bash
python -m pytest tests/test_db.py::test_reset_team_ctf_progress_preserves_quiz_progress tests/test_db.py::test_reset_team_quiz_progress_preserves_ctf_progress_and_hints -v
```

Expected: PASS.

- [ ] **Step 5: Commit DB functions**

Run:

```bash
git add benchmark_platform/db.py tests/test_db.py
git commit -m "fix: split CTF and quiz progress resets"
```

---

### Task 2: Add scoped reset web API endpoints

**Files:**
- Modify: `tests/test_quiz_api.py`
- Modify: `benchmark_platform/web/routes.py`

- [ ] **Step 1: Write failing API tests**

In `tests/test_quiz_api.py`, add this import near the top:

```python
from benchmark_platform.db import get_team_solved_count, mark_flag_solved
```

If `benchmark_platform.db` is already imported in a multiline import, extend it instead of adding a second import.

Add these tests after `test_quiz_detail_shows_saved_choice_and_correct_answer`:

```python
def test_team_management_page_has_separate_reset_buttons():
    _setup_app()
    client = _auth_client()

    r = client.get("/web/teams")

    assert r.status_code == 200
    assert "重置 CTF 进度" in r.text
    assert "重置知识评测进度" in r.text


def test_reset_ctf_endpoint_preserves_quiz_progress():
    _setup_app()
    team = get_or_create_default_team()
    client = _auth_client(team_id=team["id"])
    mark_flag_solved(team["id"], "XBEN-001-24", "flag1")
    client.post("/api/v1/quiz/SAMPLE-QUIZ-001/submit", json={"answers": {"q1": 0}})

    r = client.post("/web/api/teams/reset-ctf", json={"team_id": team["id"]})

    assert r.status_code == 200
    assert r.json()["code"] == 0
    assert get_team_solved_count(team["id"], "XBEN-001-24") == 0
    assert get_team_solved_count(team["id"], "SAMPLE-QUIZ-001") == 1


def test_reset_quiz_endpoint_preserves_ctf_progress():
    _setup_app()
    team = get_or_create_default_team()
    client = _auth_client(team_id=team["id"])
    mark_flag_solved(team["id"], "XBEN-001-24", "flag1")
    client.post("/api/v1/quiz/SAMPLE-QUIZ-001/submit", json={"answers": {"q1": 0}})

    r = client.post("/web/api/teams/reset-quiz", json={"team_id": team["id"]})

    assert r.status_code == 200
    assert r.json()["code"] == 0
    assert get_team_solved_count(team["id"], "XBEN-001-24") == 1
    assert get_team_solved_count(team["id"], "SAMPLE-QUIZ-001") == 0
```

- [ ] **Step 2: Run API tests to verify they fail**

Run:

```bash
python -m pytest tests/test_quiz_api.py::test_team_management_page_has_separate_reset_buttons tests/test_quiz_api.py::test_reset_ctf_endpoint_preserves_quiz_progress tests/test_quiz_api.py::test_reset_quiz_endpoint_preserves_ctf_progress -v
```

Expected: FAIL because the page still shows only `重置进度` and the new endpoints return 404.

- [ ] **Step 3: Add helper and endpoints**

In `benchmark_platform/web/routes.py`, add this helper near the team management routes:

```python
def _quiz_benchmark_ids(request: Request) -> list[str]:
    quiz_store = getattr(request.app.state, "quiz_store", None)
    if not quiz_store:
        return []
    return [bm["id"] for bm in quiz_store.list_benchmarks()]
```

Add these routes near the existing `api_reset_team` route:

```python
@web_router.post("/api/teams/reset-ctf")
async def api_reset_team_ctf(request: Request):
    from benchmark_platform.db import reset_team_ctf_progress
    body = await request.json()
    team_id = body.get("team_id", "").strip()
    if not team_id:
        return {"code": -1, "message": "缺少 team_id", "data": None}
    reset_team_ctf_progress(team_id, _quiz_benchmark_ids(request))
    return {"code": 0, "message": "CTF 进度已重置", "data": None}


@web_router.post("/api/teams/reset-quiz")
async def api_reset_team_quiz(request: Request):
    from benchmark_platform.db import reset_team_quiz_progress
    body = await request.json()
    team_id = body.get("team_id", "").strip()
    if not team_id:
        return {"code": -1, "message": "缺少 team_id", "data": None}
    reset_team_quiz_progress(team_id, _quiz_benchmark_ids(request))
    return {"code": 0, "message": "知识评测进度已重置", "data": None}
```

- [ ] **Step 4: Run endpoint tests again**

Run:

```bash
python -m pytest tests/test_quiz_api.py::test_reset_ctf_endpoint_preserves_quiz_progress tests/test_quiz_api.py::test_reset_quiz_endpoint_preserves_ctf_progress -v
```

Expected: PASS for endpoint behavior. The page-label test still fails until Task 3 updates the template.

- [ ] **Step 5: Commit endpoints**

Run:

```bash
git add benchmark_platform/web/routes.py tests/test_quiz_api.py
git commit -m "feat: add scoped team reset endpoints"
```

---

### Task 3: Update team management UI

**Files:**
- Modify: `benchmark_platform/web/templates/pages/teams.html`
- Test: `tests/test_quiz_api.py`

- [ ] **Step 1: Confirm the page-label test is still failing**

Run:

```bash
python -m pytest tests/test_quiz_api.py::test_team_management_page_has_separate_reset_buttons -v
```

Expected: FAIL with missing `重置 CTF 进度` and `重置知识评测进度`.

- [ ] **Step 2: Replace the operation-column button**

In `benchmark_platform/web/templates/pages/teams.html`, replace lines 46-49:

```html
<td class="px-4 py-3">
  <button @click="resetTeam(team)"
          class="text-[11px] text-red-500 hover:text-red-700 cursor-pointer">重置进度</button>
</td>
```

with:

```html
<td class="px-4 py-3">
  <div class="flex flex-col gap-1">
    <button @click="resetCtfProgress(team)"
            class="text-[11px] text-red-500 hover:text-red-700 cursor-pointer text-left">重置 CTF 进度</button>
    <button @click="resetQuizProgress(team)"
            class="text-[11px] text-amber-600 hover:text-amber-700 cursor-pointer text-left">重置知识评测进度</button>
  </div>
</td>
```

- [ ] **Step 3: Replace the JavaScript reset function**

In `benchmark_platform/web/templates/pages/teams.html`, replace the existing `async resetTeam(team) { ... }` method with:

```javascript
async resetCtfProgress(team) {
  if (!confirm(`确定要重置「${team.name}」的 CTF 解题进度吗？提交记录会保留，此操作不可恢复。`)) return;
  try {
    const res = await fetch('/web/api/teams/reset-ctf', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({team_id: team.id}),
    });
    const data = await res.json();
    if (data.code === 0) {
      this.fetchTeams();
    } else {
      alert(data.message);
    }
  } catch(e) {
    alert('重置 CTF 进度失败');
  }
},

async resetQuizProgress(team) {
  if (!confirm(`确定要重置「${team.name}」的知识评测答题进度吗？提交记录会保留，此操作不可恢复。`)) return;
  try {
    const res = await fetch('/web/api/teams/reset-quiz', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({team_id: team.id}),
    });
    const data = await res.json();
    if (data.code === 0) {
      this.fetchTeams();
    } else {
      alert(data.message);
    }
  } catch(e) {
    alert('重置知识评测进度失败');
  }
},
```

Keep the trailing comma after the second method because it is inside the returned object literal.

- [ ] **Step 4: Run page-label test**

Run:

```bash
python -m pytest tests/test_quiz_api.py::test_team_management_page_has_separate_reset_buttons -v
```

Expected: PASS.

- [ ] **Step 5: Run all related tests**

Run:

```bash
python -m pytest tests/test_db.py tests/test_quiz_api.py -v
```

Expected: PASS.

- [ ] **Step 6: Commit UI update**

Run:

```bash
git add benchmark_platform/web/templates/pages/teams.html tests/test_quiz_api.py
git commit -m "feat: split team reset controls by challenge type"
```

---

## Self-Review

- Spec coverage: The plan covers separate UI buttons, two endpoints, two DB reset functions, scoped deletion rules, and retained submission history.
- Placeholder scan: No TBD/TODO/placeholders remain.
- Type consistency: Function names are consistent across DB, routes, tests, and template JavaScript: `reset_team_ctf_progress`, `reset_team_quiz_progress`, `resetCtfProgress`, `resetQuizProgress`, `/reset-ctf`, `/reset-quiz`.
