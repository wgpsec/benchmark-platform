# Per-Team Container Isolation Design

## Goal

Change the platform from shared containers (all teams use same instance) to per-team independent instances, achieving:
1. **Fairness** — teams cannot interfere with each other's challenge environments
2. **Flag isolation** — each team gets unique flags, preventing answer sharing

## Constraints

- 3-4 teams typical, up to 20 teams max
- Each team can run at most 3 concurrent instances (platform-enforced, configurable)
- Server: 16C/32G (scales to 20 teams × 3 = 60 concurrent instances)
- Level 4 (AD) challenges remain shared across all teams
- Agent-side API is zero-change (token already associates team_id)

## Architecture

Single `ChallengeManager` extended with team dimension. No new abstractions or files introduced. Challenge objects become metadata templates; per-team instances are tracked separately via `(benchmark_id, team_id)` compound key.

## Data Model

### instance_lifecycle Table (Revised)

```sql
CREATE TABLE IF NOT EXISTS instance_lifecycle (
    id             TEXT PRIMARY KEY,
    benchmark_id   TEXT NOT NULL,
    team_id        TEXT,                    -- NULL = shared instance (AD challenges)
    challenge_code TEXT NOT NULL UNIQUE,
    runtime_path   TEXT NOT NULL,
    ports          TEXT NOT NULL,
    status         TEXT NOT NULL DEFAULT 'stopped',
    started_at     TEXT,
    expires_at     TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE(benchmark_id, team_id)
);
```

Key change: `benchmark_id UNIQUE` → `(benchmark_id, team_id) UNIQUE`.

### Runtime Directory Structure

```
runtime/
├── XBEN-001-24/
│   ├── <team_id_a>/
│   │   └── <uuid>/           ← Team A's isolated instance
│   │       ├── docker-compose.yml
│   │       ├── .env           (team A's unique flag)
│   │       └── ...
│   └── <team_id_b>/
│       └── <uuid>/           ← Team B's isolated instance
│           └── ...
├── AD-GOAD-01/
│   └── shared/               ← AD shared instance (team_id=NULL)
│       └── <uuid>/
│           └── ...
```

### ChallengeManager Internal State

```python
# Existing (unchanged)
self._instance_status: dict[str, str]  # challenge_code → status

# New
self._team_instances: dict[tuple[str, str], str]  # (benchmark_id, team_id) → challenge_code
```

## ChallengeManager Changes

### Initialization

- `start()` no longer pre-creates runtime copies for non-AD challenges
- Only loads metadata (benchmark.json) into `self.challenges` list
- AD challenges: pre-create shared instance as before

### start_challenge_instance(challenge_code, team_id)

```
1. Find challenge metadata by code
2. If AD → delegate to _start_shared_instance() (existing logic)
3. Check team concurrent limit (query DB: count WHERE team_id=? AND status='running')
4. If limit exceeded → raise error (429)
5. Look up (benchmark_id, team_id) in _team_instances
6. If found and running → return existing ports
7. If found and starting → return None (202)
8. If stopped/expired/not found → create new instance:
   a. copytree from source to runtime/<benchmark_id>/<team_id>/<uuid>/
   b. inject unique flags
   c. allocate ports
   d. docker compose up
   e. register in _team_instances and DB
9. Return entrypoints
```

### stop_challenge_instance(challenge_code, team_id)

```
1. Verify ownership: instance's team_id must match caller's team_id
2. If mismatch → raise PermissionError
3. docker compose down
4. Update status in DB and _instance_status
```

### Admin Operations

- `stop_all_instances(team_id=None)` — if team_id given, stop only that team's; else stop all
- `stop_level_instances(level, team_id=None)` — same pattern
- `get_all_instance_statuses()` — returns all instances grouped by team (admin dashboard)

### Flag Verification

```python
def get_instance_flags(self, benchmark_id: str, team_id: str | None) -> list[str]:
    """Read flags from a team's runtime .env file."""
    if team_id is None:
        # AD shared: read from shared instance path
        ...
    else:
        # Per-team: read from team's instance path
        ...
```

Submit endpoint:
- Non-AD: only match flags from the submitting team's own instance
- AD: match flags from the shared instance
- If team has no running instance for that challenge → reject (400)

## API Layer

### Changed Endpoints

| Endpoint | Change |
|----------|--------|
| `POST /api/start_challenge` | Pass `team["id"]` to manager |
| `POST /api/stop_challenge` | Pass `team["id"]`, ownership check |
| `GET /api/challenges` | `instance_status`/`entrypoint` reflect caller's team instance |
| `POST /api/submit` | Flag validation against own team's instance only |
| `POST /api/stop_all` | Admin: stops all teams' instances |
| `GET /api/instance_statuses` | Admin: returns all teams' instances |

### New Error Response

```json
// 429 Too Many Requests
{
  "code": -1,
  "message": "已达到最大同时运行实例数 (3)，请先停止其他赛题",
  "data": null
}
```

### API Compatibility

- Agent REST API: **zero changes** (Agent-Token already maps to team_id)
- Agent MCP: **zero changes** (Bearer token maps to team_id)
- Web UI JS: **zero changes** (cookie session maps to team_id)

## Web UI

### Admin Status Page (`/web/status`)

Table with team dimension:

| Challenge | Team | Status | Ports | Actions |
|-----------|------|--------|-------|---------|
| XBEN-001 | pojun | running | 32001 | [Stop] |
| XBEN-001 | team-b | stopped | — | |
| AD-GOAD-01 | (shared) | running | 32010 | [Stop] |

Admin can:
- Filter by team
- Stop individual team instances
- Stop all instances for a team
- Stop all instances globally

### Admin Dashboard

New stat cards:
- Total active instances (all teams)
- Per-team running instance count

### Settings Page

New config: "每队最大并发实例数" (max instances per team), default 3. Stored in `settings` table as `max_instances_per_team`.

## AD Challenge Special Handling

Level 4 (AD) challenges:
- Shared instance with `team_id = NULL` in DB
- All teams see same instance status and ports
- Flag is shared — first team to submit wins
- Start/stop follows existing logic unchanged
- No per-team isolation applied

Detection: `challenge.difficulty == Difficulty.AD`

## Migration

### DB Migration

On `init_db()`:
1. Check if `team_id` column exists in `instance_lifecycle`
2. If not: DROP table and recreate (instance data is ephemeral, no preservation needed)

### Startup Behavior Change

- Before: copytree + port allocation for ALL challenges at startup
- After: only metadata loading at startup; copytree happens on first `start_challenge` per team
- Result: faster startup, slightly slower first-start per challenge (~2-3s for copytree)

### Prebuild

Unaffected — operates at Docker image layer, shared across all team instances.

## Configuration Summary

| Setting | Key | Default | Stored In |
|---------|-----|---------|-----------|
| Max instances per team | `max_instances_per_team` | 3 | settings table |

## Scope

### In Scope
- Per-team instance lifecycle (create/start/stop/expire)
- Per-team flag injection and validation
- Concurrent instance limit enforcement
- Admin multi-team instance management UI
- AD challenge shared-instance exemption

### Out of Scope
- Network isolation between team containers (Docker default bridge is sufficient)
- Per-team resource quotas (CPU/memory limits per team)
- Instance migration between servers
