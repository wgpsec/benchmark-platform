# Instance Lifecycle Persistence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Persist challenge instance state to SQLite so the platform recovers running instances after restart, and add per-difficulty timeout auto-cleanup.

**Architecture:** New `instance_lifecycle` table in SQLite stores instance metadata (challenge_code, ports, status, timestamps). ChallengeManager startup reconciles DB with Docker. A background reaper thread enforces timeouts. API responses gain `started_at`/`expires_at` fields.

**Tech Stack:** Python 3.10+, SQLite (existing db.py pattern), threading, subprocess (docker compose), FastAPI, Alpine.js

---

### Task 1: DB Schema and CRUD Functions

**Files:**
- Modify: `benchmark_platform/db.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing tests for instance lifecycle DB functions**

Add to `tests/test_db.py`:

```python
from benchmark_platform.db import (
    upsert_instance, get_instance_by_benchmark_id, get_running_instances,
    get_expired_instances, delete_instance,
)


def test_upsert_instance_insert():
    upsert_instance(
        instance_id="id-1",
        benchmark_id="XBEN-001-24",
        challenge_code="uuid-1",
        runtime_path="runtime/XBEN-001-24/uuid-1",
        ports=[8081, 8082],
        status="stopped",
    )
    row = get_instance_by_benchmark_id("XBEN-001-24")
    assert row is not None
    assert row["challenge_code"] == "uuid-1"
    assert row["status"] == "stopped"
    assert row["ports"] == "[8081, 8082]"


def test_upsert_instance_update():
    upsert_instance(
        instance_id="id-1",
        benchmark_id="XBEN-001-24",
        challenge_code="uuid-1",
        runtime_path="runtime/XBEN-001-24/uuid-1",
        ports=[8081],
        status="stopped",
    )
    upsert_instance(
        instance_id="id-1",
        benchmark_id="XBEN-001-24",
        challenge_code="uuid-2",
        runtime_path="runtime/XBEN-001-24/uuid-2",
        ports=[9091],
        status="running",
        started_at="2026-05-14T00:00:00Z",
        expires_at="2026-05-14T01:00:00Z",
    )
    row = get_instance_by_benchmark_id("XBEN-001-24")
    assert row["challenge_code"] == "uuid-2"
    assert row["status"] == "running"
    assert row["ports"] == "[9091]"


def test_get_running_instances():
    upsert_instance("id-1", "XBEN-001-24", "c1", "p1", [80], "running",
                    started_at="2026-05-14T00:00:00Z", expires_at="2026-05-14T01:00:00Z")
    upsert_instance("id-2", "XBEN-002-24", "c2", "p2", [81], "stopped")
    rows = get_running_instances()
    assert len(rows) == 1
    assert rows[0]["benchmark_id"] == "XBEN-001-24"


def test_get_expired_instances():
    upsert_instance("id-1", "XBEN-001-24", "c1", "p1", [80], "running",
                    started_at="2026-05-14T00:00:00Z", expires_at="2020-01-01T00:00:00Z")
    upsert_instance("id-2", "XBEN-002-24", "c2", "p2", [81], "running",
                    started_at="2026-05-14T00:00:00Z", expires_at="2099-01-01T00:00:00Z")
    rows = get_expired_instances()
    assert len(rows) == 1
    assert rows[0]["benchmark_id"] == "XBEN-001-24"


def test_delete_instance():
    upsert_instance("id-1", "XBEN-001-24", "c1", "p1", [80], "stopped")
    delete_instance("XBEN-001-24")
    assert get_instance_by_benchmark_id("XBEN-001-24") is None
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_db.py -v -k "instance"`
Expected: FAIL with ImportError (functions not defined)

- [ ] **Step 3: Add instance_lifecycle table to init_db and implement CRUD**

In `benchmark_platform/db.py`, add to `init_db()` executescript (after `challenge_visibility` table):

```python
        CREATE TABLE IF NOT EXISTS instance_lifecycle (
            id             TEXT PRIMARY KEY,
            benchmark_id   TEXT NOT NULL UNIQUE,
            challenge_code TEXT NOT NULL UNIQUE,
            team_id        TEXT,
            runtime_path   TEXT NOT NULL,
            ports          TEXT NOT NULL,
            status         TEXT NOT NULL DEFAULT 'stopped',
            started_at     TEXT,
            expires_at     TEXT,
            created_at     TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at     TEXT NOT NULL DEFAULT (datetime('now'))
        );
```

Then add these functions at the end of `db.py` (before `get_level_gate_config`):

```python
def upsert_instance(
    instance_id: str,
    benchmark_id: str,
    challenge_code: str,
    runtime_path: str,
    ports: list[int],
    status: str,
    team_id: str | None = None,
    started_at: str | None = None,
    expires_at: str | None = None,
) -> None:
    conn = _get_conn()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ports_json = json.dumps(ports)
    conn.execute(
        """INSERT INTO instance_lifecycle
           (id, benchmark_id, challenge_code, team_id, runtime_path, ports, status, started_at, expires_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(benchmark_id) DO UPDATE SET
             challenge_code = excluded.challenge_code,
             team_id = excluded.team_id,
             runtime_path = excluded.runtime_path,
             ports = excluded.ports,
             status = excluded.status,
             started_at = excluded.started_at,
             expires_at = excluded.expires_at,
             updated_at = excluded.updated_at
        """,
        (instance_id, benchmark_id, challenge_code, team_id, runtime_path,
         ports_json, status, started_at, expires_at, now),
    )
    conn.commit()


def get_instance_by_benchmark_id(benchmark_id: str) -> dict | None:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM instance_lifecycle WHERE benchmark_id = ?",
        (benchmark_id,),
    ).fetchone()
    return dict(row) if row else None


def get_running_instances() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM instance_lifecycle WHERE status = 'running'"
    ).fetchall()
    return [dict(r) for r in rows]


def get_expired_instances() -> list[dict]:
    conn = _get_conn()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT * FROM instance_lifecycle WHERE status = 'running' AND expires_at < ?",
        (now,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_instance_status(benchmark_id: str, status: str,
                           started_at: str | None = None,
                           expires_at: str | None = None) -> None:
    conn = _get_conn()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """UPDATE instance_lifecycle
           SET status = ?, started_at = ?, expires_at = ?, updated_at = ?
           WHERE benchmark_id = ?""",
        (status, started_at, expires_at, now, benchmark_id),
    )
    conn.commit()


def delete_instance(benchmark_id: str) -> None:
    conn = _get_conn()
    conn.execute(
        "DELETE FROM instance_lifecycle WHERE benchmark_id = ?",
        (benchmark_id,),
    )
    conn.commit()
```

Also add `import json` at the top of `db.py` (it's not there yet).

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_db.py -v -k "instance"`
Expected: All 5 new tests PASS

- [ ] **Step 5: Commit**

```bash
git add benchmark_platform/db.py tests/test_db.py
git commit -m "feat(db): add instance_lifecycle table and CRUD functions"
```

---

### Task 2: Timeout Configuration API

**Files:**
- Modify: `benchmark_platform/db.py`
- Modify: `benchmark_platform/server.py`
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing test for timeout config helpers**

Add to `tests/test_db.py`:

```python
from benchmark_platform.db import get_instance_timeout_config, set_instance_timeout_config


def test_get_instance_timeout_config_defaults():
    config = get_instance_timeout_config()
    assert config == {1: 3600, 2: 7200, 3: 14400}


def test_set_instance_timeout_config():
    set_instance_timeout_config({1: 1800, 2: 3600, 3: 7200})
    config = get_instance_timeout_config()
    assert config == {1: 1800, 2: 3600, 3: 7200}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/test_db.py::test_get_instance_timeout_config_defaults tests/test_db.py::test_set_instance_timeout_config -v`
Expected: FAIL with ImportError

- [ ] **Step 3: Implement timeout config functions in db.py**

Add to `benchmark_platform/db.py`:

```python
_DEFAULT_INSTANCE_TIMEOUTS = {1: 3600, 2: 7200, 3: 14400}


def get_instance_timeout_config() -> dict[int, int]:
    result = {}
    for level in (1, 2, 3):
        val = get_setting(f"instance_timeout_level_{level}", None)
        if val is not None:
            result[level] = int(val)
        else:
            result[level] = _DEFAULT_INSTANCE_TIMEOUTS[level]
    return result


def set_instance_timeout_config(config: dict[int, int]) -> None:
    for level in (1, 2, 3):
        if level in config:
            set_setting(f"instance_timeout_level_{level}", str(config[level]))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/test_db.py::test_get_instance_timeout_config_defaults tests/test_db.py::test_set_instance_timeout_config -v`
Expected: PASS

- [ ] **Step 5: Add API endpoints in server.py**

In `benchmark_platform/server.py`, add import of the new functions at the top import block:

```python
from benchmark_platform.db import (
    ...
    get_instance_timeout_config, set_instance_timeout_config,
)
```

Then add these endpoints (after the `tch_toggle_level_gate` / level gate config section):

```python
@app.get("/api/settings/instance_timeout")
async def get_timeout_settings():
    config = get_instance_timeout_config()
    return _ok({"level_1": config[1], "level_2": config[2], "level_3": config[3]})


class InstanceTimeoutRequest(PydanticBaseModel):
    level_1: int
    level_2: int
    level_3: int


@app.post("/api/settings/instance_timeout")
async def set_timeout_settings(payload: InstanceTimeoutRequest):
    if payload.level_1 < 60 or payload.level_2 < 60 or payload.level_3 < 60:
        _err("超时时间不能小于 60 秒", 400)
        return
    set_instance_timeout_config({1: payload.level_1, 2: payload.level_2, 3: payload.level_3})
    return _ok(None, "实例超时配置已保存")
```

- [ ] **Step 6: Run full test suite**

Run: `python3 -m pytest tests/ -v --ignore=tests/test_store.py`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add benchmark_platform/db.py benchmark_platform/server.py tests/test_db.py
git commit -m "feat(api): add instance timeout configuration endpoints"
```

---

### Task 3: ChallengeManager Startup Reconciliation

**Files:**
- Modify: `benchmark_platform/utils/challenge.py`
- Modify: `benchmark_platform/db.py` (import in challenge.py)

- [ ] **Step 1: Modify ChallengeManager.start() to reconcile with DB**

In `benchmark_platform/utils/challenge.py`, add imports at the top:

```python
from benchmark_platform.db import (
    get_instance_by_benchmark_id, upsert_instance, update_instance_status,
    get_instance_timeout_config,
)
```

Replace the `start()` method body (lines 52-89 approximately) with:

```python
    def start(self) -> 'ChallengeManager':
        discovered = self._discover_challenges()
        if not discovered:
            logger.warning("no challenges found in any benchmark folder")
            return self

        seen: set[str] = set()
        unique: list[tuple[Path, str]] = []
        for folder, bid in discovered:
            if bid not in seen:
                seen.add(bid)
                unique.append((folder, bid))
            else:
                logger.warning("duplicate benchmark_id skipped",
                               benchmark_id=bid, folder=str(folder))
        discovered = unique

        errors = []
        for folder, benchmark_id in discovered:
            try:
                challenge = self._reconcile_or_create(folder, benchmark_id)
                self.challenges.append(challenge)
            except Exception as e:
                errors.append((benchmark_id, e))
                logger.error("failed to prepare challenge",
                             benchmark_id=benchmark_id, error=str(e))

        if errors:
            self.stop()
            raise RuntimeError(
                f"Failed to prepare {len(errors)} challenges: "
                f"{[f'{bid}: {e}' for bid, e in errors]}"
            )
        logger.info("challenges prepared (not yet started)",
                    count=len(self.challenges))

        self._cleanup_orphan_runtimes(seen)
        return self
```

- [ ] **Step 2: Implement _reconcile_or_create method**

Add this method to ChallengeManager (after `start`):

```python
    def _reconcile_or_create(self, benchmark_folder: Path, benchmark_id: str) -> Challenge:
        """Check DB for existing instance, reconcile with Docker, or create new."""
        record = get_instance_by_benchmark_id(benchmark_id)

        if record and record["status"] == "running":
            runtime_path = Path(record["runtime_path"])
            if runtime_path.exists() and self._is_docker_running(runtime_path):
                challenge = self._restore_challenge(benchmark_id, record)
                self._instance_status[challenge.challenge_code] = "running"
                timeout_config = get_instance_timeout_config()
                level = self.get_level_for_challenge(challenge)
                timeout_secs = timeout_config.get(level, 7200)
                now = datetime.now(timezone.utc)
                expires_at = (now + timedelta(seconds=timeout_secs)).strftime("%Y-%m-%dT%H:%M:%SZ")
                update_instance_status(benchmark_id, "running",
                                       started_at=now.strftime("%Y-%m-%dT%H:%M:%SZ"),
                                       expires_at=expires_at)
                logger.info("recovered running instance",
                            benchmark_id=benchmark_id,
                            challenge_code=record["challenge_code"])
                return challenge
            else:
                self._cleanup_stale_record(record)

        if record and record["status"] in ("stopped", "expired"):
            runtime_path = Path(record["runtime_path"])
            if runtime_path.exists():
                shutil.rmtree(runtime_path, ignore_errors=True)

        challenge = self._create_challenge(benchmark_folder, benchmark_id)
        self._instance_status[challenge.challenge_code] = "stopped"
        upsert_instance(
            instance_id=str(uuid.uuid4()),
            benchmark_id=benchmark_id,
            challenge_code=challenge.challenge_code,
            runtime_path=str(Challenge.get_base_path(benchmark_id, challenge.challenge_code, self.runtime_dir)),
            ports=challenge.target_info.port,
            status="stopped",
        )
        return challenge
```

- [ ] **Step 3: Implement helper methods**

Add these methods to ChallengeManager:

```python
    def _is_docker_running(self, runtime_path: Path) -> bool:
        """Check if docker compose services are running in the given path."""
        compose_file = runtime_path / 'docker-compose.yml'
        if not compose_file.exists():
            return False
        try:
            res = subprocess.run(
                ['docker', 'compose', 'ps', '--format', 'json'],
                cwd=runtime_path, capture_output=True, text=True, timeout=10,
            )
            if res.returncode != 0:
                return False
            for line in res.stdout.strip().splitlines():
                info = json.loads(line)
                state = info.get("State", "")
                if state == "running":
                    return True
            return False
        except Exception:
            return False

    def _restore_challenge(self, benchmark_id: str, record: dict) -> Challenge:
        """Rebuild a Challenge object from a DB record and its runtime directory."""
        runtime_path = Path(record["runtime_path"])
        challenge_code = record["challenge_code"]
        ports = json.loads(record["ports"])

        meta = json.loads((runtime_path / 'benchmark.json').read_text())
        meta['id'] = benchmark_id
        bm = Benchmark.model_validate(meta)

        flag_states = []
        bm_yaml_path = runtime_path / 'benchmark.yaml'
        if bm_yaml_path.exists():
            bm_yaml = yaml.safe_load(bm_yaml_path.read_text(encoding='utf-8'))
            for flag_def in bm_yaml.get('flags', []):
                flag_states.append(FlagState(
                    id=flag_def['id'],
                    route=flag_def.get('route', '/'),
                    description=flag_def.get('description', ''),
                ))

        _level_map = {1: Difficulty.EASY, 2: Difficulty.MEDIUM, 3: Difficulty.HARD}
        import platform as _platform
        host_is_arm = _platform.machine() in ('arm64', 'aarch64')

        compose_path = runtime_path / 'docker-compose.yml'
        with open(compose_path) as f:
            data = yaml.safe_load(f)
        is_emulated = host_is_arm and any(
            svc.get('platform', '').endswith('amd64')
            for svc in data.get('services', {}).values()
        )

        challenge = Challenge(
            challenge_code=challenge_code,
            difficulty=_level_map[bm.level],
            points=bm.points,
            hint_viewed=False,
            solved=False,
            target_info=TargetInfo(ip=self.public_accessible_host, port=ports),
            flag_states=flag_states,
            emulated=is_emulated,
        )
        challenge.set_benchmark_id(benchmark_id)
        challenge.set_runtime_dir(self.runtime_dir)
        return challenge

    def _cleanup_stale_record(self, record: dict) -> None:
        """Docker is dead but DB says running — clean up."""
        runtime_path = Path(record["runtime_path"])
        if runtime_path.exists():
            try:
                subprocess.run(
                    ['docker', 'compose', 'down'],
                    cwd=runtime_path, capture_output=True, text=True, timeout=30,
                )
            except Exception:
                pass
            shutil.rmtree(runtime_path, ignore_errors=True)
        update_instance_status(record["benchmark_id"], "stopped")
        logger.info("cleaned stale instance",
                    benchmark_id=record["benchmark_id"],
                    challenge_code=record["challenge_code"])

    def _cleanup_orphan_runtimes(self, known_benchmark_ids: set[str]) -> None:
        """Remove runtime directories that have no DB record and no known benchmark_id."""
        if not self.runtime_dir.exists():
            return
        for entry in self.runtime_dir.iterdir():
            if not entry.is_dir():
                continue
            if entry.name in known_benchmark_ids:
                continue
            if entry.name.startswith('.'):
                continue
            logger.info("cleaning orphan runtime directory", path=str(entry))
            try:
                subprocess.run(
                    ['docker', 'compose', 'down'],
                    cwd=next(entry.iterdir(), entry),
                    capture_output=True, text=True, timeout=30,
                )
            except Exception:
                pass
            shutil.rmtree(entry, ignore_errors=True)
```

- [ ] **Step 4: Add datetime imports**

At the top of `benchmark_platform/utils/challenge.py`, add:

```python
from datetime import datetime, timedelta, timezone
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/ -v --ignore=tests/test_store.py`
Expected: All pass (existing tests should still pass since DB is in-memory for tests)

- [ ] **Step 6: Commit**

```bash
git add benchmark_platform/utils/challenge.py
git commit -m "feat(manager): reconcile instance state with DB on startup"
```

---

### Task 4: Persist State on Start/Stop

**Files:**
- Modify: `benchmark_platform/utils/challenge.py`

- [ ] **Step 1: Modify start_challenge_instance to update DB**

Replace the existing `start_challenge_instance` method:

```python
    def start_challenge_instance(self, challenge_code: str) -> list[str]:
        """Start docker containers for one challenge. Return entrypoint list."""
        challenge = self._find_by_code(challenge_code)
        benchmark_id = challenge.get_benchmark_id()

        record = get_instance_by_benchmark_id(benchmark_id)
        if record and record["status"] in ("stopped", "expired"):
            old_runtime = Path(record["runtime_path"])
            if old_runtime.exists():
                shutil.rmtree(old_runtime, ignore_errors=True)

            old_code = challenge.challenge_code
            new_code = str(uuid.uuid4())
            src_folder = self._find_source_folder(benchmark_id)
            new_challenge = self._create_challenge(src_folder, benchmark_id)

            challenge.challenge_code = new_challenge.challenge_code
            challenge.target_info = new_challenge.target_info

        self._compose(challenge.get_benchmark_id(), challenge.challenge_code, 'up', '-d')
        self._instance_status[challenge.challenge_code] = "running"

        timeout_config = get_instance_timeout_config()
        level = self.get_level_for_challenge(challenge)
        timeout_secs = timeout_config.get(level, 7200)
        now = datetime.now(timezone.utc)
        started_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        expires_at = (now + timedelta(seconds=timeout_secs)).strftime("%Y-%m-%dT%H:%M:%SZ")

        upsert_instance(
            instance_id=str(uuid.uuid4()),
            benchmark_id=benchmark_id,
            challenge_code=challenge.challenge_code,
            runtime_path=str(Challenge.get_base_path(benchmark_id, challenge.challenge_code, self.runtime_dir)),
            ports=challenge.target_info.port,
            status="running",
            started_at=started_at,
            expires_at=expires_at,
        )

        return [
            f"{self.public_accessible_host}:{p}"
            for p in challenge.target_info.port
        ]
```

- [ ] **Step 2: Add _find_source_folder helper**

```python
    def _find_source_folder(self, benchmark_id: str) -> Path:
        """Find the source folder for a benchmark_id from benchmark_folders."""
        for folder in self.benchmark_folders:
            if (folder / benchmark_id).is_dir():
                return folder
            for entry in folder.iterdir():
                if entry.is_dir() and (entry / benchmark_id).is_dir():
                    return entry
        raise FileNotFoundError(f"Source folder for {benchmark_id} not found")
```

- [ ] **Step 3: Modify stop_challenge_instance to update DB**

Replace the existing `stop_challenge_instance` method:

```python
    def stop_challenge_instance(self, challenge_code: str) -> None:
        """Stop docker containers for one challenge."""
        challenge = self._find_by_code(challenge_code)
        self._compose(challenge.get_benchmark_id(), challenge_code, 'down')
        self._instance_status[challenge_code] = "stopped"
        update_instance_status(challenge.get_benchmark_id(), "stopped")
```

- [ ] **Step 4: Add get_instance_expires_at helper for API use**

```python
    def get_instance_timestamps(self, challenge_code: str) -> tuple[str | None, str | None]:
        """Return (started_at, expires_at) for a challenge instance."""
        challenge = self._find_by_code(challenge_code)
        record = get_instance_by_benchmark_id(challenge.get_benchmark_id())
        if record and record["status"] == "running":
            return record["started_at"], record["expires_at"]
        return None, None
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/ -v --ignore=tests/test_store.py`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add benchmark_platform/utils/challenge.py
git commit -m "feat(manager): persist instance state on start/stop with fresh flags"
```

---

### Task 5: Timeout Reaper Thread

**Files:**
- Modify: `benchmark_platform/utils/challenge.py`

- [ ] **Step 1: Add reaper thread to ChallengeManager.__init__**

In `__init__`, after `self._instance_status` initialization, add:

```python
        self._reaper_stop = threading.Event()
        self._reaper_thread: threading.Thread | None = None
```

Add import at top of file:

```python
import threading
```

- [ ] **Step 2: Implement _start_reaper and _reaper_loop methods**

```python
    def _start_reaper(self) -> None:
        """Start the background reaper thread for expired instances."""
        if self._reaper_thread is not None:
            return
        self._reaper_stop.clear()
        self._reaper_thread = threading.Thread(target=self._reaper_loop, daemon=True)
        self._reaper_thread.start()
        logger.info("instance reaper started")

    def _reaper_loop(self) -> None:
        """Periodically check for and clean up expired instances."""
        from benchmark_platform.db import get_expired_instances
        while not self._reaper_stop.is_set():
            try:
                expired = get_expired_instances()
                for record in expired:
                    benchmark_id = record["benchmark_id"]
                    challenge_code = record["challenge_code"]
                    runtime_path = Path(record["runtime_path"])
                    logger.info("reaping expired instance",
                                benchmark_id=benchmark_id,
                                challenge_code=challenge_code)
                    try:
                        if runtime_path.exists():
                            subprocess.run(
                                ['docker', 'compose', 'down'],
                                cwd=runtime_path,
                                capture_output=True, text=True, timeout=60,
                            )
                        update_instance_status(benchmark_id, "expired")
                        self._instance_status[challenge_code] = "stopped"
                    except Exception as e:
                        logger.error("reaper failed for instance",
                                     benchmark_id=benchmark_id, error=str(e))
            except Exception as e:
                logger.error("reaper loop error", error=str(e))
            self._reaper_stop.wait(30)
```

- [ ] **Step 3: Start reaper at the end of start() method**

At the end of the `start()` method, before `return self`, add:

```python
        self._start_reaper()
```

- [ ] **Step 4: Stop reaper in stop() method**

Modify `stop()` to signal the reaper:

```python
    def stop(self) -> None:
        self._reaper_stop.set()
        if self._reaper_thread is not None:
            self._reaper_thread.join(timeout=5)
            self._reaper_thread = None
        self._cleanup(self.challenges)
        self.challenges.clear()
        self._instance_status.clear()
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/ -v --ignore=tests/test_store.py`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add benchmark_platform/utils/challenge.py
git commit -m "feat(manager): add background reaper thread for expired instances"
```

---

### Task 6: API Response Changes (started_at, expires_at)

**Files:**
- Modify: `benchmark_platform/server.py`
- Modify: `benchmark_platform/mcp_server.py`

- [ ] **Step 1: Add timestamps to /api/start_challenge response**

In `benchmark_platform/server.py`, in `tch_start_challenge`, after the successful start, change the return to include `expires_at`:

```python
    try:
        entrypoints = manager.start_challenge_instance(payload.code)
    except Exception as e:
        logger.error("start_challenge failed", action="api", challenge_code=payload.code, error=str(e))
        _err(f"赛题启动失败: {e}", 502)
        return

    started_at, expires_at = manager.get_instance_timestamps(payload.code)
    return _ok({"entrypoint": entrypoints, "started_at": started_at, "expires_at": expires_at}, "赛题实例启动成功")
```

Also update the "already running" case:

```python
    if manager.get_instance_status(payload.code) in ("running", "unhealthy"):
        entrypoints = [f"{manager.public_accessible_host}:{p}" for p in challenge.target_info.port]
        started_at, expires_at = manager.get_instance_timestamps(payload.code)
        return _ok({"entrypoint": entrypoints, "started_at": started_at, "expires_at": expires_at}, "赛题实例已在运行中")
```

- [ ] **Step 2: Add timestamps to /api/instance_statuses**

In `tch_instance_statuses`, add timestamps to each entry:

```python
    for c in manager.challenges:
        bm_id = c.get_benchmark_id()
        enabled = is_challenge_enabled(bm_id)
        if agent_view and not enabled:
            continue
        started_at, expires_at = manager.get_instance_timestamps(c.challenge_code)
        statuses[c.challenge_code] = {
            "status": manager.get_instance_status(c.challenge_code),
            "benchmark_id": bm_id,
            "level": manager.get_level_for_challenge(c),
            "solved": c.solved,
            "enabled": enabled,
            "started_at": started_at,
            "expires_at": expires_at,
        }
```

- [ ] **Step 3: Add timestamps to MCP start_challenge response**

In `benchmark_platform/mcp_server.py`, in the `start_challenge` tool, after successful start:

```python
    try:
        entrypoints = mgr.start_challenge_instance(code)
    except Exception as e:
        raise ValueError(f"赛题启动失败: {e}")

    started_at, expires_at = mgr.get_instance_timestamps(code)
    return json.dumps({"message": "赛题实例启动成功", "entrypoint": entrypoints,
                       "started_at": started_at, "expires_at": expires_at}, ensure_ascii=False)
```

Also update the "already running" case in MCP:

```python
    if mgr.get_instance_status(code) in ("running", "unhealthy"):
        entrypoints = [f"{mgr.public_accessible_host}:{p}" for p in challenge.target_info.port]
        started_at, expires_at = mgr.get_instance_timestamps(code)
        return json.dumps({"message": "赛题实例已在运行中", "entrypoint": entrypoints,
                           "started_at": started_at, "expires_at": expires_at}, ensure_ascii=False)
```

- [ ] **Step 4: Run tests**

Run: `python3 -m pytest tests/ -v --ignore=tests/test_store.py`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add benchmark_platform/server.py benchmark_platform/mcp_server.py
git commit -m "feat(api): expose started_at and expires_at in API/MCP responses"
```

---

### Task 7: Web UI — Countdown and Settings

**Files:**
- Modify: `benchmark_platform/web/templates/components/challenge_card.html`
- Modify: `benchmark_platform/web/templates/pages/settings.html`
- Modify: `benchmark_platform/web/context.py`

- [ ] **Step 1: Add timestamps to challenge card context**

In `benchmark_platform/web/context.py`, in `_challenge_to_card`, add the timestamps to the returned dict. After the line that sets `"enabled"`:

```python
    started_at, expires_at = None, None
    if manager.get_instance_status(challenge.challenge_code) in ("running", "unhealthy"):
        started_at, expires_at = manager.get_instance_timestamps(challenge.challenge_code)
```

Add to the returned dict:

```python
        "started_at": started_at,
        "expires_at": expires_at,
```

- [ ] **Step 2: Add countdown display to challenge_card.html**

In `benchmark_platform/web/templates/components/challenge_card.html`, inside the actions section, after the running-state stop button block, add a countdown element:

```html
    {% if card.instance_status in ('running', 'unhealthy') and card.expires_at %}
    <span class="ml-auto text-[11px] font-mono"
          x-data="countdown('{{ card.expires_at }}')"
          :class="remaining < 600 ? 'text-red-500 font-semibold' : 'text-gray-400'">
      <span x-text="display"></span>
    </span>
    {% endif %}
```

Then add the Alpine.js component at the bottom of the file (outside the card div):

```html
<script>
function countdown(expiresAt) {
  return {
    remaining: 0,
    display: '',
    interval: null,
    init() {
      this.tick();
      this.interval = setInterval(() => this.tick(), 1000);
    },
    tick() {
      const exp = new Date(expiresAt).getTime();
      const now = Date.now();
      this.remaining = Math.max(0, Math.floor((exp - now) / 1000));
      if (this.remaining <= 0) {
        this.display = '已超时';
        if (this.interval) clearInterval(this.interval);
        return;
      }
      const h = Math.floor(this.remaining / 3600);
      const m = Math.floor((this.remaining % 3600) / 60);
      const s = this.remaining % 60;
      this.display = h > 0
        ? `${h}h ${m.toString().padStart(2,'0')}m`
        : `${m}m ${s.toString().padStart(2,'0')}s`;
    },
    destroy() {
      if (this.interval) clearInterval(this.interval);
    }
  };
}
</script>
```

- [ ] **Step 3: Add timeout settings section to settings.html**

In `benchmark_platform/web/templates/pages/settings.html`, after the Level Gate settings `</div>` and before the closing `</div>` of the x-data, add:

```html
  <!-- Instance Timeout Settings -->
  <div class="bg-white border border-gray-200 rounded-xl p-5 mb-5">
    <h3 class="text-[13px] font-semibold text-gray-800 mb-4">实例超时</h3>
    <p class="text-[11px] text-gray-500 mb-4">按难度等级设置实例自动回收时间。超时后容器自动停止并清理，Agent 需重新启动。</p>

    <div class="space-y-3">
      <div class="flex items-center gap-3">
        <label class="w-28 text-[11px] font-medium text-gray-600">Level 1 (Easy)</label>
        <input type="number" x-model="timeoutL1" min="1"
               class="w-24 h-9 px-3 text-[12px] border border-gray-200 rounded-lg focus:outline-none focus:border-gray-400">
        <span class="text-[11px] text-gray-400">分钟</span>
      </div>
      <div class="flex items-center gap-3">
        <label class="w-28 text-[11px] font-medium text-gray-600">Level 2 (Medium)</label>
        <input type="number" x-model="timeoutL2" min="1"
               class="w-24 h-9 px-3 text-[12px] border border-gray-200 rounded-lg focus:outline-none focus:border-gray-400">
        <span class="text-[11px] text-gray-400">分钟</span>
      </div>
      <div class="flex items-center gap-3">
        <label class="w-28 text-[11px] font-medium text-gray-600">Level 3 (Hard)</label>
        <input type="number" x-model="timeoutL3" min="1"
               class="w-24 h-9 px-3 text-[12px] border border-gray-200 rounded-lg focus:outline-none focus:border-gray-400">
        <span class="text-[11px] text-gray-400">分钟</span>
      </div>
    </div>

    <div class="flex items-center gap-3 pt-4">
      <button @click="saveTimeout()" :disabled="savingTimeout"
              class="h-9 px-5 bg-gray-900 text-white text-[12px] font-medium rounded-lg hover:bg-gray-800 transition-colors cursor-pointer disabled:opacity-50">
        <span x-show="!savingTimeout">保存</span>
        <span x-show="savingTimeout">保存中...</span>
      </button>
      <span x-show="savedTimeout" x-transition class="text-[11px] text-emerald-600 font-medium">已保存</span>
    </div>
  </div>
```

- [ ] **Step 4: Add timeout state/methods to settings Alpine.js**

In the `settingsPage()` function in `settings.html`, add the new state and methods:

```javascript
    // Instance timeout
    timeoutL1: 60,
    timeoutL2: 120,
    timeoutL3: 240,
    savingTimeout: false,
    savedTimeout: false,
```

In `init()`, add:

```javascript
      fetch('/api/settings/instance_timeout')
        .then(r => r.json())
        .then(d => {
          if (d.data) {
            this.timeoutL1 = Math.round(d.data.level_1 / 60);
            this.timeoutL2 = Math.round(d.data.level_2 / 60);
            this.timeoutL3 = Math.round(d.data.level_3 / 60);
          }
        });
```

Add `saveTimeout` method:

```javascript
    saveTimeout() {
      this.savingTimeout = true;
      this.savedTimeout = false;
      fetch('/api/settings/instance_timeout', {
        method: 'POST',
        headers: {'Content-Type': 'application/json'},
        body: JSON.stringify({
          level_1: parseInt(this.timeoutL1) * 60,
          level_2: parseInt(this.timeoutL2) * 60,
          level_3: parseInt(this.timeoutL3) * 60
        })
      })
      .then(r => r.json())
      .then(d => {
        this.savingTimeout = false;
        if (d.code === 0) {
          this.savedTimeout = true;
          this.$dispatch('toast', {type: 'success', message: '实例超时配置已保存'});
          setTimeout(() => this.savedTimeout = false, 3000);
        } else {
          this.$dispatch('toast', {type: 'error', message: d.message || '保存失败'});
        }
      });
    }
```

- [ ] **Step 5: Run tests**

Run: `python3 -m pytest tests/ -v --ignore=tests/test_store.py`
Expected: All pass

- [ ] **Step 6: Manual test**

Start the server: `python3 -m benchmark_platform.server --benchmark-folder ./challenges --port 8088 --public-accessible-host localhost`

Verify:
1. Open settings page — timeout section appears with default values (60/120/240 minutes)
2. Start a challenge — card shows countdown timer
3. Countdown turns red when < 10 minutes remaining

- [ ] **Step 7: Commit**

```bash
git add benchmark_platform/web/templates/components/challenge_card.html \
        benchmark_platform/web/templates/pages/settings.html \
        benchmark_platform/web/context.py
git commit -m "feat(ui): add instance countdown timer and timeout settings"
```

---

### Task 8: Integration Test and Version Bump

**Files:**
- Modify: `benchmark_platform/__init__.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Run full test suite**

Run: `python3 -m pytest tests/ -v --ignore=tests/test_store.py`
Expected: All pass

- [ ] **Step 2: Manual integration test**

Start server and verify the full lifecycle:
1. Start a challenge → instance shows running with countdown
2. Restart server process (Ctrl+C → start again)
3. Verify the previously running challenge is recovered (shows running, countdown resets)
4. Wait for timeout or manually verify reaper logic by setting a very short timeout in settings

- [ ] **Step 3: Bump version**

In `benchmark_platform/__init__.py`:
```python
__version__ = "0.9.0"
```

In `pyproject.toml`:
```toml
version = "0.9.0"
```

- [ ] **Step 4: Commit**

```bash
git add benchmark_platform/__init__.py pyproject.toml
git commit -m "chore: bump version to v0.9.0"
```
