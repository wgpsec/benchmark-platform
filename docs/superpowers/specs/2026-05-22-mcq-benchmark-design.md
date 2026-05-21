# MCQ Knowledge Benchmark Support

## Goal

Extend the benchmark platform to support MCQ (multiple-choice question) knowledge benchmarks alongside existing CTF challenges, enabling comprehensive evaluation of both practical exploitation skills and cybersecurity knowledge.

## Architecture

Extend the existing Challenge system with a new `win_condition: "mcq"` type. MCQ benchmarks reuse the team/progress/scoring infrastructure but bypass Docker container lifecycle entirely. A lightweight quiz evaluator handles answer validation and scoring. UI and API are separated from CTF: dedicated `/web/quiz` page and `/api/v1/quiz/` endpoints. Scoreboard gains multi-tab ranking (CTF / MCQ / Combined).

## Tech Stack

- Backend: FastAPI (existing), SQLite (existing team_progress table)
- Frontend: Jinja2 + Tailwind + HTMX (existing patterns)
- Data format: JSON (benchmark.json with questions array)

---

## 1. Data Model

### 1.1 WinCondition Extension

```python
class WinCondition(str, Enum):
    FLAG = 'flag'
    MCQ = 'mcq'
```

### 1.2 MCQ Benchmark JSON Format

Each MCQ benchmark is a directory containing `benchmark.json`:

```json
{
  "id": "CYBERMETRIC-001",
  "name": "CyberMetric 基础安全知识",
  "description": "网络安全基础知识评估",
  "level": 1,
  "win_condition": "mcq",
  "tags": ["knowledge", "cybermetric"],
  "category": "security_knowledge",
  "questions": [
    {
      "id": "q1",
      "text": "Which protocol operates at Layer 4 of the OSI model?",
      "choices": ["HTTP", "TCP", "ARP", "Ethernet"],
      "answer": 1
    }
  ]
}
```

Fields:
- `win_condition`: must be `"mcq"`
- `category`: one of `threat_intelligence`, `vulnerability_analysis`, `security_knowledge`, `certification`
- `questions[].id`: unique within this benchmark
- `questions[].text`: question text
- `questions[].choices`: list of 4 options
- `questions[].answer`: 0-based index of correct choice
- No `docker-compose.yml`, `.env`, or `canaries` required

### 1.3 Directory Structure

```
challenges/quiz/cybermetric-80/benchmark.json
challenges/quiz/secbench-mcq/benchmark.json
challenges/quiz/ctibench-mcq/benchmark.json
challenges/quiz/mmlu-compsec/benchmark.json
challenges/quiz/cissp-mc-zh/benchmark.json
```

MCQ benchmarks live under `challenges/quiz/`, physically separated from CTF challenges.

### 1.4 Scoring

- Total points per benchmark follow existing level mapping: level 1 = 200, level 2 = 300, level 3 = 500, level 4 = 1000
- Per-question score = benchmark total points / question count
- Correct answer earns points; wrong answer earns 0 (no penalty)

---

## 2. API

### 2.1 Endpoints

```
GET  /api/v1/quiz                         → List all MCQ benchmarks (id, name, category, question_count, team progress)
GET  /api/v1/quiz/{benchmark_id}          → Get questions for a benchmark (without answer field)
POST /api/v1/quiz/{benchmark_id}/submit   → Submit answers
```

### 2.2 Submit Request

```json
{
  "answers": {"q1": 1, "q2": 0, "q3": 2}
}
```

Supports partial submission (subset of questions). Each question can only be answered once per team.

### 2.3 Submit Response

```json
{
  "correct": 8,
  "total": 10,
  "score": 160,
  "details": [
    {"id": "q1", "correct": true},
    {"id": "q2", "correct": false, "your_answer": 2, "correct_answer": 0}
  ]
}
```

### 2.4 Rules

- Each question can only be submitted once per team (prevents brute-force)
- Re-submitting an already-answered question returns the previous result without modification
- Already-answered questions in a batch submission are silently skipped

---

## 3. Storage

Reuse existing `team_progress` table:

```
team_progress(team_id, benchmark_id, flag_id, solved, solved_at)
```

For MCQ:
- `benchmark_id` = MCQ benchmark id (e.g., "CYBERMETRIC-001")
- `flag_id` = question id (e.g., "q1")
- `solved` = 1 if correct, 0 if wrong (still recorded to prevent re-submission)

Score calculation queries filter by benchmark `win_condition` type to separate CTF and MCQ scores.

---

## 4. Challenge Loading

### 4.1 ChallengeManager Changes

`_discover_challenges` detects `win_condition` from `benchmark.json`:
- `flag` → existing logic (requires docker-compose.yml)
- `mcq` → load metadata only, skip Docker validation

MCQ benchmarks:
- Not subject to instance management (no start/stop/timeout/reaper)
- Not subject to level gate (independent from CTF progression)
- Not included in CTF challenge list API

### 4.2 Quiz Module

New module: `benchmark_platform/quiz.py`

Responsibilities:
- Load MCQ benchmarks from `challenges/quiz/` directories
- Serve questions (strip answer field for API responses)
- Validate submitted answers against stored correct answers
- Calculate scores and write to team_progress
- Provide aggregate stats (per-team scores, accuracy rates)

---

## 5. Web UI

### 5.1 New Page: `/web/quiz`

MCQ benchmark list page:
- Card layout showing each benchmark: name, category tag, question count
- Per-team progress indicator (e.g., "8/10 已答, 正确率 80%")
- "开始答题" / "查看结果" button per card

### 5.2 New Page: `/web/quiz/{benchmark_id}`

Answer page:
- Single-question view with radio buttons for choices
- Navigation: previous/next question buttons
- Submit per question (immediate feedback: correct/wrong)
- Cannot change answer after submission
- Summary view after all questions answered (total score, accuracy)

### 5.3 Scoreboard Changes (`/web/scoreboard`)

Add tab navigation at top: `综合` | `CTF` | `MCQ`

Table columns per tab:
- CTF tab: rank, team name, CTF score, solved flags
- MCQ tab: rank, team name, MCQ score, accuracy rate
- Combined tab: rank, team name, CTF score, MCQ score, total score

Default view: Combined. Weight configurable in settings (default 50/50).

### 5.4 Sidebar

Add "知识评测" entry below "题目列表", linking to `/web/quiz`.

### 5.5 Topbar

Add to `page_titles`: `'quiz': ('知识评测', '网安知识基准评估')`

### 5.6 Observer Role

Observers can only view scoreboard. Cannot access `/web/quiz` or answer questions (consistent with CTF restriction).

---

## 6. Auth Middleware

Update observer path allowlist:
```python
if user["role"] == "observer" and path not in ("/web/scoreboard", "/web/logout"):
```

No change needed — quiz pages are already blocked for observers by this rule.

---

## 7. Target Benchmarks (Phase 1)

Priority datasets to integrate:

| Benchmark | Category | Questions | Source |
|-----------|----------|-----------|--------|
| CyberMetric-80Q | security_knowledge | 80 | Open source |
| CyberMetric-500Q | security_knowledge | 500 | Open source |
| SecBench-MCQ | security_knowledge | ~1000 | Open source |
| MMLU-CompSec | security_knowledge | ~100 | Open source |
| CTIBench-MCQ | threat_intelligence | ~200 | Open source |

Data collection and formatting is a separate task after the platform support is built.
