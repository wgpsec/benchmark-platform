# Instance Lifecycle Persistence Design

> Resolves: [GitHub Issue #2](https://github.com/wgpsec/benchmark-platform/issues/2)

## Goal

Persist challenge instance state to SQLite so the platform can recover running instances after a service restart, and add difficulty-based timeout auto-cleanup to prevent resource exhaustion.

## Architecture

The platform currently stores instance status in a memory-only dict (`_instance_status`). Each restart generates new UUIDs and runtime directories, losing all association with previously running Docker containers.

This design introduces a `instance_lifecycle` DB table as the source of truth for instance state. On startup, the ChallengeManager reconciles DB records with actual Docker state. A background reaper thread enforces per-difficulty timeout limits.

## DB Schema

```sql
CREATE TABLE IF NOT EXISTS instance_lifecycle (
    id             TEXT PRIMARY KEY,
    benchmark_id   TEXT NOT NULL,
    challenge_code TEXT NOT NULL UNIQUE,
    team_id        TEXT,
    runtime_path   TEXT NOT NULL,
    ports          TEXT NOT NULL,       -- JSON array e.g. [8081, 8082]
    status         TEXT NOT NULL DEFAULT 'stopped',  -- stopped | running | expired
    started_at     TEXT,
    expires_at     TEXT,
    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
    updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
);
```

Fields:
- `challenge_code` UNIQUE — one active instance per benchmark_id at a time.
- `ports` — JSON array of allocated host ports, reused on recovery.
- `status` — three states: `stopped`, `running`, `expired`.
- `started_at` / `expires_at` — ISO8601 timestamps, set when instance starts.

## ChallengeManager Lifecycle Changes

### Startup (start method)

```
For each discovered benchmark_id:
  1. Query DB for existing record
  2a. Record exists + Docker containers running:
      → Reuse challenge_code, runtime_path, ports
      → Mark running in memory
      → Reset expires_at = now + timeout (from recovery moment)
  2b. Record exists + Docker containers dead:
      → docker compose down (cleanup networks)
      → Remove runtime directory
      → Update DB status = stopped
      → Proceed as "no record"
  2c. No record:
      → Generate new UUID (challenge_code)
      → copytree + inject dynamic flags + allocate ports
      → Insert DB record with status = stopped
```

### start_challenge_instance

```
1. docker compose up -d
2. Update DB: status=running, started_at=now, expires_at=now+timeout
3. Update memory: _instance_status[code] = "running"
```

Timeout values by difficulty:
- Level 1 (Easy): 1 hour (3600s)
- Level 2 (Medium): 2 hours (7200s)
- Level 3 (Hard): 4 hours (14400s)

Configurable via `settings` table (keys: `instance_timeout_level_1`, `instance_timeout_level_2`, `instance_timeout_level_3`).

### stop_challenge_instance

```
1. docker compose down
2. Update DB: status=stopped, started_at=NULL, expires_at=NULL
3. Update memory: _instance_status[code] = "stopped"
```

### Re-start after stop/expire

When a user/Agent calls `start_challenge` on a challenge whose DB record has `status=stopped` or `status=expired`:
1. Delete old runtime directory (located via DB `runtime_path` field)
2. Generate new UUID as challenge_code
3. copytree from source + inject new dynamic flags + allocate new ports
4. Update the existing DB row: set new `challenge_code`, `runtime_path`, `ports`, `status=running`, `started_at=now`, `expires_at=now+timeout`
5. Update in-memory Challenge object and `_instance_status`

This ensures fresh flags on every new start (dynamic flag requirement). The in-memory Challenge object's `challenge_code` and `target_info.port` are mutated to reflect the new values.

## Timeout Reaper

A daemon thread in ChallengeManager, started during `__init__`, running every 30 seconds:

```
loop:
  1. Query DB: status='running' AND expires_at < now()
  2. For each expired record:
     - docker compose down
     - Update DB: status='expired', updated_at=now
     - Update memory: _instance_status[code] = 'stopped'
  3. Sleep 30s (interruptible via stop flag)
```

Thread lifecycle:
- Created in ChallengeManager.__init__ with `daemon=True`
- Stopped via threading.Event when ChallengeManager.stop() is called.

## Timeout Configuration

Default values hardcoded: `{1: 3600, 2: 7200, 3: 14400}`.

Overridable via settings table. New API endpoints:
- `GET /api/settings/instance_timeout` — returns `{level_1: int, level_2: int, level_3: int}` (seconds)
- `POST /api/settings/instance_timeout` — accepts `{level_1: int, level_2: int, level_3: int}`

Web UI: add "Instance Timeout" section in the existing settings page with three input fields (minutes).

## API/MCP Changes (Additive)

### Existing endpoints — new fields

`GET /api/challenges` and MCP `list_challenges`:
- Each challenge gains: `started_at: string | null`, `expires_at: string | null`

`POST /api/start_challenge` response:
- New field: `expires_at: string`

`GET /api/instance_statuses`:
- Each entry gains: `started_at: string | null`, `expires_at: string | null`

### New endpoints

- `GET /api/settings/instance_timeout`
- `POST /api/settings/instance_timeout`

### MCP tools

No new tools. `list_challenges` and `start_challenge` return values naturally include `expires_at`.

## Web UI Changes

Challenge card:
- Display remaining time countdown when instance is running (Alpine.js computed from `expires_at`)
- Text turns red when < 10 minutes remaining

Settings page:
- New "实例超时 / Instance Timeout" section with three inputs for Level 1/2/3 timeout (in minutes)

## Edge Cases

### DB says running, Docker is dead
Startup reconciliation detects this via `docker compose ps`. Cleans up (compose down + rmtree) and resets DB to `stopped`.

### Runtime directory exists but no DB record
Startup scans runtime subdirectories. Any directory without a matching DB record gets `docker compose down` + `shutil.rmtree`.

### Multi-team
Current design: one instance per challenge (not per-team). `team_id` records who last started it (audit). Schema supports future extension to `(benchmark_id, team_id)` unique for per-team isolation.

### Concurrency safety
- SQLite WAL mode for write safety across threads.
- Reaper uses CAS pattern: `UPDATE ... WHERE status='running' AND expires_at < ?` to avoid double-cleanup race with API stop requests.

### Abnormal exit (kill -9)
Next startup runs the full reconciliation flow — discovers containers via DB + Docker, recovers or cleans as appropriate.

## Out of Scope

- Multi-node / distributed deployment (future consideration)
- Per-team independent instances (schema ready, not implemented now)
- Container resource limits (CPU/memory)
