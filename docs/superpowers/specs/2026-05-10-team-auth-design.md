# Team Authentication System Design

## Overview

Add multi-team support to the benchmark platform. Each team gets a unique Agent-Token for API authentication, with independent progress tracking (solved flags, hints, scores) while sharing challenge container instances. Web UI gains a team management page with leaderboard.

## Decisions

| Topic | Decision |
|-------|----------|
| Storage | SQLite (`data/benchmark.db`) |
| Instance model | Shared (one container per challenge, all teams access it) |
| Level Gate | Global (admin controls which levels are open, same for all teams) |
| Scale | 1-5 teams (personal/small team training) |
| Team deletion | Not supported (create-only, unused teams stay) |
| Dashboard | Leaderboard view (teams ranked by score) |
| Auth mode | Optional (no token → default team, backward compatible) |

## Data Layer

### SQLite Schema

File: `data/benchmark.db` (WAL mode, `sqlite3.Row` factory)

```sql
CREATE TABLE IF NOT EXISTS teams (
    id         TEXT PRIMARY KEY,
    name       TEXT UNIQUE NOT NULL,
    token      TEXT UNIQUE NOT NULL,
    created_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS team_progress (
    team_id        TEXT NOT NULL,
    challenge_code TEXT NOT NULL,
    flag_id        TEXT NOT NULL,
    solved         INTEGER NOT NULL DEFAULT 0,
    solved_at      TEXT,
    PRIMARY KEY (team_id, challenge_code, flag_id)
);

CREATE TABLE IF NOT EXISTS team_hints (
    team_id        TEXT NOT NULL,
    challenge_code TEXT NOT NULL,
    viewed_at      TEXT NOT NULL DEFAULT (datetime('now')),
    PRIMARY KEY (team_id, challenge_code)
);
```

### Module: `benchmark_platform/db.py`

Public functions:

- `init_db()` — create tables
- `create_team(name: str) -> dict` — returns `{id, name, token}`, token is `secrets.token_hex(16)`
- `list_teams() -> list[dict]` — with aggregate scores
- `get_team_by_token(token: str) -> dict | None`
- `get_or_create_default_team() -> dict` — ensures a team with `name="default"` exists
- `mark_flag_solved(team_id, challenge_code, flag_id)` — INSERT OR IGNORE
- `get_team_solved_count(team_id, challenge_code) -> int`
- `is_hint_viewed(team_id, challenge_code) -> bool`
- `mark_hint_viewed(team_id, challenge_code)`
- `get_team_progress(team_id) -> dict[str, dict[str, bool]]` — `{challenge_code: {flag_id: solved}}`

No ORM. Pure `sqlite3` standard library.

## Authentication Layer

### Module: `benchmark_platform/auth.py`

Single FastAPI dependency:

```python
async def get_current_team(agent_token: str | None = Header(None, alias="Agent-Token")) -> dict:
    if agent_token is None:
        return get_or_create_default_team()
    team = get_team_by_token(agent_token)
    if team is None:
        raise HTTPException(401, detail={"code": -1, "message": "Invalid Agent-Token", "data": None})
    return team
```

### Route scoping

**Authenticated** (inject `team = Depends(get_current_team)`):
- `GET /api/challenges`
- `POST /api/start_challenge`
- `POST /api/stop_challenge`
- `POST /api/submit`
- `POST /api/hint`
- `GET /api/challenges/{code}/progress`
- `POST /api/stop_all`

**Unauthenticated** (admin operations):
- `POST /api/toggle_level_gate`
- `POST /api/start_level`, `POST /api/stop_level`
- `/api/prebuild/*`
- All `/web/*` routes

## State Separation

Challenge objects become immutable definitions. All mutable per-team state moves to DB.

| Route | Before (global) | After (per-team DB) |
|-------|----------------|---------------------|
| `GET /api/challenges` | `challenge.solved` | `get_team_solved_count(team_id, code)` |
| `POST /api/submit` | `fs.solved = True` | `mark_flag_solved(team_id, code, flag_id)` |
| `POST /api/hint` | `challenge.hint_viewed = True` | `mark_hint_viewed(team_id, code)` |
| `GET /api/.../progress` | `fs.solved` | query DB per team |
| `POST /api/start_challenge` | `challenge.solved` for skip check | `is_challenge_fully_solved()` from DB |

Instance management (`start_challenge`/`stop_challenge`) operates on shared containers — any team can start/stop.

### SubmissionStore extension

`SubmissionRecord` gains `team_id: str` and `team_name: str` fields. Existing JSONL format extended (backward compatible — old records won't have these fields).

## Web UI

### New page: Team Management (`/web/teams`)

- Create team form (name input only) → modal shows generated token once with copy button
- Leaderboard table (ranked by total score):
  - Rank, Team Name, Token (first 8 chars + "..."), Solved Count, Total Score, Created At

### Dashboard change

- Add leaderboard section showing team rankings
- Retain existing stats cards (total challenges, flags, etc.) as global aggregates

### Sidebar

Add "队伍管理" nav item under "系统" group.

### Admin API routes (on web_router, no auth)

- `POST /web/api/teams/create` — body: `{name}`, returns `{id, name, token}`
- `GET /web/api/teams` — returns team list with scores

## Initialization

Server startup (`serve()`) adds:

1. `init_db()` — create tables if not exist
2. `get_or_create_default_team()` — ensure default team present

## Compatibility

- No Agent-Token header → default team → behavior identical to current single-user mode
- Web UI unaffected
- Existing `/api/v1/*` routes (old PoJun API) unchanged
- No new pip dependencies (all stdlib)

## File Changes Summary

| File | Action |
|------|--------|
| `benchmark_platform/db.py` | New |
| `benchmark_platform/auth.py` | New |
| `benchmark_platform/server.py` | Modify — inject team dep, read/write progress from DB |
| `benchmark_platform/web/routes.py` | Modify — add team management routes |
| `benchmark_platform/web/context.py` | Modify — add leaderboard context |
| `benchmark_platform/web/submission_store.py` | Modify — add team_id/team_name to record |
| `benchmark_platform/web/templates/pages/teams.html` | New |
| `benchmark_platform/web/templates/components/sidebar.html` | Modify — add nav item |
| `benchmark_platform/web/templates/pages/dashboard.html` | Modify — add leaderboard section |
| `benchmark_platform/__init__.py` | Modify — version bump to 0.4.0 |
| `.gitignore` | Modify — add `data/` |

## Version

Bump to `0.4.0`.
