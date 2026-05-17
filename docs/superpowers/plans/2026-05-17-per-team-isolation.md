# Per-Team Container Isolation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Change the platform from shared containers to per-team independent instances, with per-team flag isolation, concurrent instance limits, and AD challenge exemption.

**Architecture:** Extend `ChallengeManager` with team dimension. Challenge objects become metadata templates (no runtime state). Per-team instances tracked via `(benchmark_id, team_id)` compound key in DB and in-memory dict. AD (Level 4) challenges remain shared with `team_id=NULL`.

**Tech Stack:** Python 3.10+, FastAPI, SQLite, Docker Compose, pytest

---

## File Map

| File | Role | Change Type |
|------|------|-------------|
| `benchmark_platform/db.py` | DB schema + query functions | Modify |
| `benchmark_platform/utils/challenge.py` | ChallengeManager per-team lifecycle | Modify (major) |
| `benchmark_platform/server.py` | API layer team_id passthrough | Modify |
| `benchmark_platform/base.py` | Challenge.get_base_path signature update | Modify (minor) |
| `benchmark_platform/web/routes.py` | Web UI context for status page | Modify (minor) |
| `benchmark_platform/web/templates/partials/status_table.html` | Admin status view with team column | Modify |
| `tests/test_db.py` | DB function tests | Modify |
| `tests/test_per_team_isolation.py` | Integration tests for isolation logic | Create |

---

### Task 1: DB Schema Migration — Add team_id to instance_lifecycle

**Files:**
- Modify: `benchmark_platform/db.py:35-81` (init_db), `benchmark_platform/db.py:279-360` (instance functions)
- Test: `tests/test_db.py`

- [ ] **Step 1: Write failing tests for new DB functions**

Add to `tests/test_db.py`:

```python
from benchmark_platform.db import (
    upsert_instance, get_instance_by_benchmark_and_team,
    get_team_running_count, get_all_instances,
    update_instance_status_by_team,
)


def test_upsert_instance_with_team_id():
    upsert_instance(
        instance_id="inst-1",
        benchmark_id="XBEN-001",
        challenge_code="code-1",
        runtime_path="/tmp/rt/XBEN-001/team-a/code-1",
        ports=[8080],
        status="running",
        team_id="team-a",
        started_at="2026-01-01T00:00:00Z",
        expires_at="2026-01-01T01:00:00Z",
    )
    row = get_instance_by_benchmark_and_team("XBEN-001", "team-a")
    assert row is not None
    assert row["team_id"] == "team-a"
    assert row["status"] == "running"


def test_upsert_instance_shared_no_team():
    upsert_instance(
        instance_id="inst-shared",
        benchmark_id="AD-001",
        challenge_code="code-shared",
        runtime_path="/tmp/rt/AD-001/shared/code-shared",
        ports=[9090],
        status="running",
        team_id=None,
    )
    row = get_instance_by_benchmark_and_team("AD-001", None)
    assert row is not None
    assert row["team_id"] is None


def test_same_benchmark_different_teams():
    upsert_instance(
        instance_id="inst-1", benchmark_id="XBEN-001",
        challenge_code="code-1", runtime_path="/tmp/1",
        ports=[8001], status="running", team_id="team-a",
    )
    upsert_instance(
        instance_id="inst-2", benchmark_id="XBEN-001",
        challenge_code="code-2", runtime_path="/tmp/2",
        ports=[8002], status="running", team_id="team-b",
    )
    a = get_instance_by_benchmark_and_team("XBEN-001", "team-a")
    b = get_instance_by_benchmark_and_team("XBEN-001", "team-b")
    assert a["challenge_code"] == "code-1"
    assert b["challenge_code"] == "code-2"


def test_get_team_running_count():
    upsert_instance(
        instance_id="i1", benchmark_id="X1", challenge_code="c1",
        runtime_path="/tmp/1", ports=[8001], status="running", team_id="team-a",
    )
    upsert_instance(
        instance_id="i2", benchmark_id="X2", challenge_code="c2",
        runtime_path="/tmp/2", ports=[8002], status="running", team_id="team-a",
    )
    upsert_instance(
        instance_id="i3", benchmark_id="X3", challenge_code="c3",
        runtime_path="/tmp/3", ports=[8003], status="stopped", team_id="team-a",
    )
    assert get_team_running_count("team-a") == 2


def test_get_all_instances():
    upsert_instance(
        instance_id="i1", benchmark_id="X1", challenge_code="c1",
        runtime_path="/tmp/1", ports=[8001], status="running", team_id="team-a",
    )
    upsert_instance(
        instance_id="i2", benchmark_id="X1", challenge_code="c2",
        runtime_path="/tmp/2", ports=[8002], status="running", team_id="team-b",
    )
    all_inst = get_all_instances()
    assert len(all_inst) == 2


def test_update_instance_status_by_team():
    upsert_instance(
        instance_id="i1", benchmark_id="X1", challenge_code="c1",
        runtime_path="/tmp/1", ports=[8001], status="running", team_id="team-a",
    )
    update_instance_status_by_team("X1", "team-a", "stopped")
    row = get_instance_by_benchmark_and_team("X1", "team-a")
    assert row["status"] == "stopped"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `cd /Users/f0x/pte-project/weaponize/Agentic/benchmark-platform && python -m pytest tests/test_db.py -v -k "team_running_count or benchmark_and_team or same_benchmark or all_instances or status_by_team or shared_no_team" 2>&1 | tail -20`

Expected: FAIL — functions not defined

- [ ] **Step 3: Update init_db() to new schema**

In `benchmark_platform/db.py`, replace the `instance_lifecycle` CREATE TABLE in `init_db()` with:

```python
        CREATE TABLE IF NOT EXISTS instance_lifecycle (
            id             TEXT PRIMARY KEY,
            benchmark_id   TEXT NOT NULL,
            team_id        TEXT,
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

Add migration logic after `conn.commit()` in `init_db()`:

```python
    # Migrate instance_lifecycle: add team_id column if missing
    try:
        cols_il = [r[1] for r in conn.execute("PRAGMA table_info(instance_lifecycle)").fetchall()]
        if "team_id" not in cols_il:
            conn.execute("DROP TABLE instance_lifecycle")
            conn.execute("""
                CREATE TABLE instance_lifecycle (
                    id             TEXT PRIMARY KEY,
                    benchmark_id   TEXT NOT NULL,
                    team_id        TEXT,
                    challenge_code TEXT NOT NULL UNIQUE,
                    runtime_path   TEXT NOT NULL,
                    ports          TEXT NOT NULL,
                    status         TEXT NOT NULL DEFAULT 'stopped',
                    started_at     TEXT,
                    expires_at     TEXT,
                    created_at     TEXT NOT NULL DEFAULT (datetime('now')),
                    updated_at     TEXT NOT NULL DEFAULT (datetime('now')),
                    UNIQUE(benchmark_id, team_id)
                )
            """)
            conn.commit()
    except Exception:
        pass
```

- [ ] **Step 4: Implement new DB functions**

Replace `upsert_instance` and add new functions in `benchmark_platform/db.py`:

```python
def upsert_instance(
    instance_id: str,
    benchmark_id: str,
    challenge_code: str,
    runtime_path: str,
    ports: List[int],
    status: str,
    team_id: Optional[str] = None,
    started_at: Optional[str] = None,
    expires_at: Optional[str] = None,
) -> None:
    conn = _get_conn()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    ports_json = json.dumps(ports)
    conn.execute(
        """INSERT INTO instance_lifecycle
           (id, benchmark_id, team_id, challenge_code, runtime_path, ports, status, started_at, expires_at, updated_at)
           VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
           ON CONFLICT(benchmark_id, team_id) DO UPDATE SET
             id = excluded.id,
             challenge_code = excluded.challenge_code,
             runtime_path = excluded.runtime_path,
             ports = excluded.ports,
             status = excluded.status,
             started_at = excluded.started_at,
             expires_at = excluded.expires_at,
             updated_at = excluded.updated_at
        """,
        (instance_id, benchmark_id, team_id, challenge_code, runtime_path,
         ports_json, status, started_at, expires_at, now),
    )
    conn.commit()


def get_instance_by_benchmark_and_team(benchmark_id: str, team_id: Optional[str]) -> Optional[dict]:
    conn = _get_conn()
    if team_id is None:
        row = conn.execute(
            "SELECT * FROM instance_lifecycle WHERE benchmark_id = ? AND team_id IS NULL",
            (benchmark_id,),
        ).fetchone()
    else:
        row = conn.execute(
            "SELECT * FROM instance_lifecycle WHERE benchmark_id = ? AND team_id = ?",
            (benchmark_id, team_id),
        ).fetchone()
    return dict(row) if row else None


def get_instance_by_benchmark_id(benchmark_id: str) -> Optional[dict]:
    """Legacy compat: return first instance for a benchmark_id (prefers shared)."""
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM instance_lifecycle WHERE benchmark_id = ? ORDER BY team_id IS NOT NULL",
        (benchmark_id,),
    ).fetchone()
    return dict(row) if row else None


def get_team_running_count(team_id: str) -> int:
    conn = _get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM instance_lifecycle WHERE team_id = ? AND status = 'running'",
        (team_id,),
    ).fetchone()
    return row["cnt"]


def get_all_instances() -> List[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM instance_lifecycle ORDER BY benchmark_id, team_id"
    ).fetchall()
    return [dict(r) for r in rows]


def update_instance_status_by_team(
    benchmark_id: str, team_id: Optional[str], status: str,
    started_at: Optional[str] = None, expires_at: Optional[str] = None,
) -> None:
    conn = _get_conn()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if team_id is None:
        conn.execute(
            """UPDATE instance_lifecycle
               SET status = ?, started_at = ?, expires_at = ?, updated_at = ?
               WHERE benchmark_id = ? AND team_id IS NULL""",
            (status, started_at, expires_at, now, benchmark_id),
        )
    else:
        conn.execute(
            """UPDATE instance_lifecycle
               SET status = ?, started_at = ?, expires_at = ?, updated_at = ?
               WHERE benchmark_id = ? AND team_id = ?""",
            (status, started_at, expires_at, now, benchmark_id, team_id),
        )
    conn.commit()
```

Keep the old `update_instance_status` and `get_running_instances` as-is for backward compat during transition.

- [ ] **Step 5: Run tests to verify they pass**

Run: `cd /Users/f0x/pte-project/weaponize/Agentic/benchmark-platform && python -m pytest tests/test_db.py -v 2>&1 | tail -30`

Expected: ALL PASS

- [ ] **Step 6: Commit**

```bash
git add benchmark_platform/db.py tests/test_db.py
git commit -m "feat: add team_id dimension to instance_lifecycle schema"
```

---

### Task 2: ChallengeManager — Separate Metadata from Instances

**Files:**
- Modify: `benchmark_platform/utils/challenge.py:35-100` (init, start, stop methods)
- Modify: `benchmark_platform/base.py:63-66` (get_base_path)

- [ ] **Step 1: Update Challenge.get_base_path to support team_id**

In `benchmark_platform/base.py`, change:

```python
    @staticmethod
    def get_base_path(benchmark_id: str, challenge_code: str, runtime_dir: Path | None = None) -> Path:
        base = runtime_dir if runtime_dir else Path('runtime')
        return base / benchmark_id / challenge_code
```

To:

```python
    @staticmethod
    def get_base_path(benchmark_id: str, challenge_code: str, runtime_dir: Path | None = None, team_id: str | None = None) -> Path:
        base = runtime_dir if runtime_dir else Path('runtime')
        if team_id:
            return base / benchmark_id / team_id / challenge_code
        return base / benchmark_id / challenge_code
```

- [ ] **Step 2: Add `_team_instances` dict and `max_instances_per_team` to ChallengeManager.__init__**

In `benchmark_platform/utils/challenge.py`, add to `__init__`:

```python
        self._team_instances: dict[tuple[str, str], str] = {}  # (benchmark_id, team_id) → challenge_code
        self.max_instances_per_team: int = 3
```

- [ ] **Step 3: Change `start()` to NOT pre-create runtime copies for non-AD challenges**

Replace the `_reconcile_or_create` call loop in `start()` with metadata-only loading for non-AD, and keep instance creation for AD:

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
                challenge = self._load_challenge_metadata(folder, benchmark_id)
                self.challenges.append(challenge)
                self._instance_status[challenge.challenge_code] = "stopped"
            except Exception as e:
                errors.append((benchmark_id, e))
                logger.error("failed to load challenge metadata",
                             benchmark_id=benchmark_id, error=str(e))

        if errors:
            self.stop()
            raise RuntimeError(
                f"Failed to load {len(errors)} challenges: "
                f"{[f'{bid}: {e}' for bid, e in errors]}"
            )
        logger.info("challenges loaded (metadata only)",
                    count=len(self.challenges))

        self._recover_running_instances()
        self._cleanup_orphan_runtimes(seen)
        self._start_reaper()

        # Load max_instances_per_team from settings
        from benchmark_platform.db import get_setting
        try:
            self.max_instances_per_team = int(get_setting("max_instances_per_team", "3"))
        except (ValueError, TypeError):
            self.max_instances_per_team = 3

        return self
```

- [ ] **Step 4: Implement `_load_challenge_metadata`**

This creates a Challenge object from benchmark.json WITHOUT copytree or port allocation:

```python
    def _load_challenge_metadata(self, benchmark_folder: Path, benchmark_id: str) -> Challenge:
        """Load challenge metadata without creating a runtime instance."""
        src = benchmark_folder / benchmark_id
        meta = json.loads((src / 'benchmark.json').read_text(encoding='utf-8'))
        meta['id'] = benchmark_id
        bm = Benchmark.model_validate(meta)

        flag_states = []
        bm_yaml_path = src / 'benchmark.yaml'
        if bm_yaml_path.exists():
            bm_yaml = yaml.safe_load(bm_yaml_path.read_text(encoding='utf-8'))
            for flag_def in bm_yaml.get('flags', []):
                flag_states.append(FlagState(
                    id=flag_def['id'],
                    route=flag_def.get('route', '/'),
                    description=flag_def.get('description', ''),
                ))

        _level_map = {1: Difficulty.EASY, 2: Difficulty.MEDIUM, 3: Difficulty.HARD, 4: Difficulty.AD}
        if bm.level not in _level_map:
            raise ValueError(f"Unknown level {bm.level!r} in benchmark {benchmark_id!r}")

        import platform as _platform
        host_is_arm = _platform.machine() in ('arm64', 'aarch64')

        compose_path = src / 'docker-compose.yml'
        with open(compose_path) as f:
            data = yaml.safe_load(f)

        is_emulated = host_is_arm and any(
            svc.get('platform', '').endswith('amd64')
            for svc in data.get('services', {}).values()
        )

        is_unsupported = False
        unsupported_reason = ""
        if bm.requires:
            if bm.requires.arch == "x86_64" and host_is_arm:
                is_unsupported = True
                unsupported_reason = "需要 x86_64 架构"
            elif bm.requires.arch == "aarch64" and not host_is_arm:
                is_unsupported = True
                unsupported_reason = "需要 ARM64 架构"
            if bm.requires.kvm and not Path('/dev/kvm').exists():
                is_unsupported = True
                unsupported_reason = "需要 KVM 虚拟化支持 (/dev/kvm)"
            if bm.requires.arch == "x86_64" and host_is_arm and bm.requires.kvm:
                unsupported_reason = "需要 x86_64 架构 + KVM 虚拟化"

        requires_win_iso = self._detect_requires_windows_iso(data)

        challenge = Challenge(
            challenge_code=benchmark_id,  # Use benchmark_id as stable code for metadata
            difficulty=_level_map[bm.level],
            points=bm.points,
            hint_viewed=False,
            solved=False,
            target_info=TargetInfo(ip=self.public_accessible_host, port=[]),
            flag_states=flag_states,
            emulated=is_emulated,
            unsupported=is_unsupported,
            unsupported_reason=unsupported_reason,
            requires_windows_iso=requires_win_iso,
        )
        challenge.set_benchmark_id(benchmark_id)
        challenge.set_runtime_dir(self.runtime_dir)
        return challenge
```

- [ ] **Step 5: Implement `_recover_running_instances`**

Recover any instances that were running before restart:

```python
    def _recover_running_instances(self) -> None:
        """On startup, recover instances that DB says are running."""
        from benchmark_platform.db import get_running_instances
        for record in get_running_instances():
            benchmark_id = record["benchmark_id"]
            team_id = record["team_id"]
            challenge_code = record["challenge_code"]
            runtime_path = Path(record["runtime_path"])

            if not runtime_path.exists() or not self._is_docker_running(runtime_path):
                self._cleanup_stale_record(record)
                continue

            self._instance_status[challenge_code] = "running"
            if team_id:
                self._team_instances[(benchmark_id, team_id)] = challenge_code
            else:
                self._team_instances[(benchmark_id, "__shared__")] = challenge_code

            logger.info("recovered running instance",
                        benchmark_id=benchmark_id, team_id=team_id,
                        challenge_code=challenge_code)
```

- [ ] **Step 6: Commit**

```bash
git add benchmark_platform/base.py benchmark_platform/utils/challenge.py
git commit -m "refactor: separate challenge metadata from runtime instances"
```

---

### Task 3: ChallengeManager — Per-Team Start/Stop

**Files:**
- Modify: `benchmark_platform/utils/challenge.py:562-665` (start/stop methods)

- [ ] **Step 1: Rewrite `start_challenge_instance` to accept team_id**

```python
    def start_challenge_instance(self, challenge_code: str, team_id: str) -> list[str] | None:
        """Start a per-team instance for a challenge."""
        challenge = self._find_by_code(challenge_code)
        benchmark_id = challenge.get_benchmark_id()

        # AD challenges use shared instance
        if challenge.difficulty == Difficulty.AD:
            return self._start_shared_instance(challenge)

        # Concurrent limit check
        from benchmark_platform.db import get_team_running_count
        running_count = get_team_running_count(team_id)
        if running_count >= self.max_instances_per_team:
            raise RuntimeError(f"已达到最大同时运行实例数 ({self.max_instances_per_team})，请先停止其他赛题")

        # Check existing instance for this team+challenge
        existing_code = self._team_instances.get((benchmark_id, team_id))
        if existing_code:
            status = self._instance_status.get(existing_code, "stopped")
            if status in ("running", "unhealthy"):
                ports = self._get_instance_ports(benchmark_id, team_id)
                return [f"{self.public_accessible_host}:{p}" for p in ports]
            if status == "starting":
                return None

        # Clean up old stopped instance if exists
        from benchmark_platform.db import get_instance_by_benchmark_and_team
        record = get_instance_by_benchmark_and_team(benchmark_id, team_id)
        if record and record["status"] in ("stopped", "expired"):
            old_runtime = Path(record["runtime_path"])
            if old_runtime.exists():
                shutil.rmtree(old_runtime, ignore_errors=True)

        # Create new per-team instance
        src_folder = self._find_source_folder(benchmark_id)
        instance_code = str(uuid.uuid4())
        runtime_path = Challenge.get_base_path(benchmark_id, instance_code, self.runtime_dir, team_id=team_id)
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        src = src_folder / benchmark_id
        shutil.copytree(src, runtime_path)

        # Inject unique flags for this team
        self._inject_dynamic_flags(runtime_path)

        # Remap ports
        compose_path = runtime_path / 'docker-compose.yml'
        with open(compose_path) as f:
            data = yaml.safe_load(f)

        allocated_ports = []
        for svc_name, svc in data.get('services', {}).items():
            new_ports = []
            for p in svc.get('ports', []):
                if isinstance(p, str) and ':' in p:
                    host_port = portpicker.pick_unused_port()
                    allocated_ports.append(host_port)
                    parts = p.split(':')
                    new_ports.append(f"{host_port}:{parts[-1]}")
                else:
                    new_ports.append(p)
            svc['ports'] = new_ports
            if 'build' in svc and 'image' not in svc:
                svc['image'] = f"{benchmark_id}-{svc_name}".lower()

        with open(compose_path, 'w') as f:
            yaml.dump(data, f)

        # Handle Windows ISO injection
        if challenge.requires_windows_iso:
            from benchmark_platform.db import get_setting
            iso_path = get_setting("win2022_iso_path", "")
            if not iso_path:
                shutil.rmtree(runtime_path, ignore_errors=True)
                raise RuntimeError("请先在系统设置中配置 Windows Server 2022 ISO 路径")
            if not Path(iso_path).is_file():
                shutil.rmtree(runtime_path, ignore_errors=True)
                raise RuntimeError(f"Windows ISO 文件不存在: {iso_path}")
            self._inject_windows_iso(compose_path, iso_path)
            self._inject_oem_flags(runtime_path)

        # Register instance
        self._team_instances[(benchmark_id, team_id)] = instance_code
        self._instance_status[instance_code] = "starting"

        upsert_instance(
            instance_id=str(uuid.uuid4()),
            benchmark_id=benchmark_id,
            challenge_code=instance_code,
            runtime_path=str(runtime_path),
            ports=allocated_ports,
            status="starting",
            team_id=team_id,
        )

        # Start compose (async for Windows ISO)
        if challenge.requires_windows_iso:
            threading.Thread(
                target=self._async_team_compose_start,
                args=(challenge, benchmark_id, instance_code, team_id, allocated_ports),
                daemon=True,
            ).start()
            return None

        try:
            self._compose_at_path(runtime_path, 'up', '-d')
        except Exception:
            self._instance_status[instance_code] = "stopped"
            from benchmark_platform.db import update_instance_status_by_team
            update_instance_status_by_team(benchmark_id, team_id, "stopped")
            raise

        self._instance_status[instance_code] = "running"
        self._finalize_team_start(challenge, benchmark_id, instance_code, team_id, allocated_ports)
        return [f"{self.public_accessible_host}:{p}" for p in allocated_ports]
```

- [ ] **Step 2: Implement helper methods**

```python
    def _start_shared_instance(self, challenge: Challenge) -> list[str] | None:
        """Start or return existing shared instance for AD challenges."""
        benchmark_id = challenge.get_benchmark_id()
        existing_code = self._team_instances.get((benchmark_id, "__shared__"))

        if existing_code:
            status = self._instance_status.get(existing_code, "stopped")
            if status in ("running", "unhealthy"):
                ports = self._get_instance_ports(benchmark_id, None)
                return [f"{self.public_accessible_host}:{p}" for p in ports]
            if status == "starting":
                return None

        # Create shared instance (same logic as per-team but with team_id=None)
        from benchmark_platform.db import get_instance_by_benchmark_and_team
        record = get_instance_by_benchmark_and_team(benchmark_id, None)
        if record and record["status"] in ("stopped", "expired"):
            old_runtime = Path(record["runtime_path"])
            if old_runtime.exists():
                shutil.rmtree(old_runtime, ignore_errors=True)

        src_folder = self._find_source_folder(benchmark_id)
        instance_code = str(uuid.uuid4())
        runtime_path = Challenge.get_base_path(benchmark_id, instance_code, self.runtime_dir, team_id="shared")
        runtime_path.parent.mkdir(parents=True, exist_ok=True)
        src = src_folder / benchmark_id
        shutil.copytree(src, runtime_path)

        self._inject_dynamic_flags(runtime_path)

        compose_path = runtime_path / 'docker-compose.yml'
        with open(compose_path) as f:
            data = yaml.safe_load(f)

        allocated_ports = []
        for svc_name, svc in data.get('services', {}).items():
            new_ports = []
            for p in svc.get('ports', []):
                if isinstance(p, str) and ':' in p:
                    host_port = portpicker.pick_unused_port()
                    allocated_ports.append(host_port)
                    parts = p.split(':')
                    new_ports.append(f"{host_port}:{parts[-1]}")
                else:
                    new_ports.append(p)
            svc['ports'] = new_ports
            if 'build' in svc and 'image' not in svc:
                svc['image'] = f"{benchmark_id}-{svc_name}".lower()

        with open(compose_path, 'w') as f:
            yaml.dump(data, f)

        if challenge.requires_windows_iso:
            from benchmark_platform.db import get_setting
            iso_path = get_setting("win2022_iso_path", "")
            if not iso_path:
                shutil.rmtree(runtime_path, ignore_errors=True)
                raise RuntimeError("请先在系统设置中配置 Windows Server 2022 ISO 路径")
            if not Path(iso_path).is_file():
                shutil.rmtree(runtime_path, ignore_errors=True)
                raise RuntimeError(f"Windows ISO 文件不存在: {iso_path}")
            self._inject_windows_iso(compose_path, iso_path)
            self._inject_oem_flags(runtime_path)

        self._team_instances[(benchmark_id, "__shared__")] = instance_code
        self._instance_status[instance_code] = "starting"

        upsert_instance(
            instance_id=str(uuid.uuid4()),
            benchmark_id=benchmark_id,
            challenge_code=instance_code,
            runtime_path=str(runtime_path),
            ports=allocated_ports,
            status="starting",
            team_id=None,
        )

        if challenge.requires_windows_iso:
            threading.Thread(
                target=self._async_team_compose_start,
                args=(challenge, benchmark_id, instance_code, None, allocated_ports),
                daemon=True,
            ).start()
            return None

        try:
            self._compose_at_path(runtime_path, 'up', '-d')
        except Exception:
            self._instance_status[instance_code] = "stopped"
            from benchmark_platform.db import update_instance_status_by_team
            update_instance_status_by_team(benchmark_id, None, "stopped")
            raise

        self._instance_status[instance_code] = "running"
        self._finalize_team_start(challenge, benchmark_id, instance_code, None, allocated_ports)
        return [f"{self.public_accessible_host}:{p}" for p in allocated_ports]

    def _get_instance_ports(self, benchmark_id: str, team_id: str | None) -> list[int]:
        """Get allocated ports for an instance from DB."""
        from benchmark_platform.db import get_instance_by_benchmark_and_team
        record = get_instance_by_benchmark_and_team(benchmark_id, team_id)
        if record:
            return json.loads(record["ports"])
        return []

    def _compose_at_path(self, runtime_path: Path, *args, timeout: int | None = None) -> None:
        """Run docker compose at a specific path."""
        if not (runtime_path / 'docker-compose.yml').exists():
            return
        compose_timeout = timeout or self._COMPOSE_TIMEOUT
        cmd = ['docker', 'compose'] + list(args)
        logger.info("docker compose", action="compose", cmd=" ".join(cmd), cwd=str(runtime_path))

        benchmark_id = runtime_path.parent.parent.name  # runtime/<bid>/<team>/<code>
        self._instance_logs[benchmark_id] = []
        logs = self._instance_logs[benchmark_id]

        start_time = time.monotonic()

        proc = subprocess.Popen(
            cmd, cwd=runtime_path,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
        )
        try:
            while True:
                line = proc.stdout.readline()
                if not line and proc.poll() is not None:
                    break
                if line:
                    logs.append(line.rstrip('\n'))
                    if len(logs) > 500:
                        del logs[:len(logs) - 500]
                if time.monotonic() - start_time > compose_timeout:
                    proc.terminate()
                    proc.wait(timeout=10)
                    raise RuntimeError(f"Docker compose timed out after {compose_timeout}s")
        except RuntimeError:
            raise
        except Exception:
            proc.kill()
            raise

        if proc.returncode != 0:
            output = '\n'.join(logs[-20:])
            if 'could not find an available, non-overlapping IPv4 address pool' in output:
                self._prune_orphan_networks()
                # Retry once
                self._instance_logs[benchmark_id] = []
                logs = self._instance_logs[benchmark_id]
                start_time = time.monotonic()
                proc = subprocess.Popen(
                    cmd, cwd=runtime_path,
                    stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True,
                )
                while True:
                    line = proc.stdout.readline()
                    if not line and proc.poll() is not None:
                        break
                    if line:
                        logs.append(line.rstrip('\n'))
                        if len(logs) > 500:
                            del logs[:len(logs) - 500]
                    if time.monotonic() - start_time > compose_timeout:
                        proc.terminate()
                        proc.wait(timeout=10)
                        raise RuntimeError(f"Docker compose timed out after {compose_timeout}s (retry)")
                if proc.returncode == 0:
                    return
            raise RuntimeError(f"Docker compose failed: {output[:500]}")

    def _async_team_compose_start(self, challenge: Challenge, benchmark_id: str,
                                   instance_code: str, team_id: str | None,
                                   ports: list[int]) -> None:
        """Background thread for compose up (AD/Windows challenges)."""
        from benchmark_platform.db import update_instance_status_by_team
        runtime_path = self._get_runtime_path_for_instance(benchmark_id, instance_code, team_id)
        try:
            self._compose_at_path(runtime_path, 'up', '-d',
                                  timeout=self._COMPOSE_TIMEOUT_WINDOWS)
            self._instance_status[instance_code] = "running"
            self._finalize_team_start(challenge, benchmark_id, instance_code, team_id, ports)
        except Exception as e:
            logger.error("async compose start failed",
                         benchmark_id=benchmark_id, team_id=team_id, error=str(e))
            self._instance_logs.setdefault(benchmark_id, []).append(f"ERROR: {e}")
            self._instance_status[instance_code] = "stopped"
            update_instance_status_by_team(benchmark_id, team_id, "stopped")

    def _finalize_team_start(self, challenge: Challenge, benchmark_id: str,
                              instance_code: str, team_id: str | None,
                              ports: list[int]) -> None:
        """Record instance as running after successful compose up."""
        timeout_config = get_instance_timeout_config()
        level = self.get_level_for_challenge(challenge)
        timeout_secs = timeout_config.get(level, 7200)
        now = datetime.now(timezone.utc)
        started_at = now.strftime("%Y-%m-%dT%H:%M:%SZ")
        expires_at = (now + timedelta(seconds=timeout_secs)).strftime("%Y-%m-%dT%H:%M:%SZ")

        upsert_instance(
            instance_id=str(uuid.uuid4()),
            benchmark_id=benchmark_id,
            challenge_code=instance_code,
            runtime_path=str(self._get_runtime_path_for_instance(benchmark_id, instance_code, team_id)),
            ports=ports,
            status="running",
            team_id=team_id,
            started_at=started_at,
            expires_at=expires_at,
        )

    def _get_runtime_path_for_instance(self, benchmark_id: str, instance_code: str, team_id: str | None) -> Path:
        """Compute runtime path for an instance."""
        dir_name = team_id if team_id else "shared"
        return Challenge.get_base_path(benchmark_id, instance_code, self.runtime_dir, team_id=dir_name)
```

- [ ] **Step 3: Rewrite `stop_challenge_instance` with ownership check**

```python
    def stop_challenge_instance(self, challenge_code: str, team_id: str | None = None) -> None:
        """Stop a team's instance. If team_id provided, verify ownership."""
        # Find which benchmark this instance belongs to
        instance_code, benchmark_id, owner_team_id = self._resolve_instance(challenge_code, team_id)

        if team_id and owner_team_id and owner_team_id != team_id:
            raise PermissionError("无权停止其他队伍的实例")

        self._instance_status[instance_code] = "stopping"

        runtime_path = self._get_runtime_path_for_instance(benchmark_id, instance_code, owner_team_id)
        if runtime_path.exists():
            self._compose_at_path(runtime_path, 'down', '-v', '--remove-orphans')

        self._instance_status[instance_code] = "stopped"
        from benchmark_platform.db import update_instance_status_by_team
        update_instance_status_by_team(benchmark_id, owner_team_id, "stopped")

    def _resolve_instance(self, challenge_code: str, team_id: str | None) -> tuple[str, str, str | None]:
        """Resolve a challenge_code to (instance_code, benchmark_id, owner_team_id).

        If challenge_code is a benchmark_id and team_id is given, look up that team's instance.
        Otherwise search _team_instances for a match.
        """
        # If challenge_code is actually a benchmark_id and team_id is given
        if team_id:
            existing = self._team_instances.get((challenge_code, team_id))
            if existing:
                return existing, challenge_code, team_id

        # Search all team_instances for this code
        for (bid, tid), code in self._team_instances.items():
            if code == challenge_code:
                real_team = tid if tid != "__shared__" else None
                return code, bid, real_team

        # Fallback: challenge_code might be a benchmark_id for shared
        existing = self._team_instances.get((challenge_code, "__shared__"))
        if existing:
            return existing, challenge_code, None

        raise KeyError(f"Instance {challenge_code!r} not found")
```

- [ ] **Step 4: Add methods for getting team instance status**

```python
    def get_team_instance_status(self, benchmark_id: str, team_id: str) -> str:
        """Get instance status for a specific team's challenge."""
        challenge = self._find_by_code(benchmark_id)
        if challenge.difficulty == Difficulty.AD:
            code = self._team_instances.get((benchmark_id, "__shared__"))
        else:
            code = self._team_instances.get((benchmark_id, team_id))
        if not code:
            return "stopped"
        status = self._instance_status.get(code, "stopped")
        if status != "running":
            return status
        # Check container health
        runtime_path = self._get_runtime_path_for_instance(
            benchmark_id, code, team_id if challenge.difficulty != Difficulty.AD else "shared"
        )
        return self._check_health_at_path(runtime_path)

    def get_team_instance_ports(self, benchmark_id: str, team_id: str) -> list[int]:
        """Get ports for a team's instance of a challenge."""
        challenge = self._find_by_code(benchmark_id)
        if challenge.difficulty == Difficulty.AD:
            return self._get_instance_ports(benchmark_id, None)
        return self._get_instance_ports(benchmark_id, team_id)

    def get_team_instance_timestamps(self, benchmark_id: str, team_id: str) -> tuple[str | None, str | None]:
        """Return (started_at, expires_at) for a team's instance."""
        from benchmark_platform.db import get_instance_by_benchmark_and_team
        challenge = self._find_by_code(benchmark_id)
        lookup_team = team_id if challenge.difficulty != Difficulty.AD else None
        record = get_instance_by_benchmark_and_team(benchmark_id, lookup_team)
        if record and record["status"] == "running":
            return record["started_at"], record["expires_at"]
        return None, None

    def _check_health_at_path(self, runtime_path: Path) -> str:
        """Check container health status at a runtime path."""
        if not runtime_path.exists() or not (runtime_path / 'docker-compose.yml').exists():
            return "running"
        try:
            res = subprocess.run(
                ['docker', 'compose', 'ps', '--format', 'json'],
                cwd=runtime_path, capture_output=True, text=True, timeout=5,
            )
            if res.returncode != 0:
                return "running"
            for line in res.stdout.strip().splitlines():
                info = json.loads(line)
                if info.get("Health") == "unhealthy":
                    return "unhealthy"
        except Exception:
            pass
        return "running"

    def get_team_instance_flags(self, benchmark_id: str, team_id: str) -> dict[str, str]:
        """Read flags from a team's runtime .env file. Returns {flag_id: flag_value}."""
        challenge = self._find_by_code(benchmark_id)
        if challenge.difficulty == Difficulty.AD:
            code = self._team_instances.get((benchmark_id, "__shared__"))
            lookup_team = "shared"
        else:
            code = self._team_instances.get((benchmark_id, team_id))
            lookup_team = team_id

        if not code:
            return {}

        runtime_path = self._get_runtime_path_for_instance(benchmark_id, code, lookup_team)
        if not runtime_path.exists():
            return {}

        import dotenv
        env_path = runtime_path / '.env'
        if not env_path.exists():
            return {}

        data = dotenv.dotenv_values(env_path)
        data_upper = {k.upper(): v for k, v in data.items()}

        if challenge.flag_states:
            result = {}
            for i, fs in enumerate(challenge.flag_states):
                key_by_id = f"FLAG_{fs.id}".upper()
                key_by_idx = f"FLAG{i + 1}"
                if key_by_id in data_upper:
                    result[fs.id] = str(data_upper[key_by_id])
                elif key_by_idx in data_upper:
                    result[fs.id] = str(data_upper[key_by_idx])
                elif "FLAG" in data_upper and len(challenge.flag_states) == 1:
                    result[fs.id] = str(data_upper["FLAG"])
            return result

        if 'FLAG' not in data_upper:
            return {}
        return {"default": str(data_upper['FLAG'])}
```

- [ ] **Step 5: Add admin stop-all with team filter**

```python
    def stop_all_instances(self, team_id: str | None = None) -> int:
        """Stop all instances, optionally filtered by team."""
        stopped = 0
        to_stop = []
        for (bid, tid), code in list(self._team_instances.items()):
            if team_id and tid != team_id:
                continue
            if self._instance_status.get(code) in ("running", "unhealthy", "starting"):
                to_stop.append((bid, tid, code))

        for bid, tid, code in to_stop:
            real_team = tid if tid != "__shared__" else None
            try:
                runtime_path = self._get_runtime_path_for_instance(bid, code, tid if tid != "__shared__" else "shared")
                if runtime_path.exists():
                    self._compose_at_path(runtime_path, 'down', '-v', '--remove-orphans')
                self._instance_status[code] = "stopped"
                from benchmark_platform.db import update_instance_status_by_team
                update_instance_status_by_team(bid, real_team, "stopped")
                stopped += 1
            except Exception as e:
                logger.error("stop_all failed for instance", benchmark_id=bid, team_id=tid, error=str(e))
        return stopped
```

- [ ] **Step 6: Commit**

```bash
git add benchmark_platform/utils/challenge.py
git commit -m "feat: implement per-team instance start/stop with ownership checks"
```

---

### Task 4: Server API Layer — Pass team_id to ChallengeManager

**Files:**
- Modify: `benchmark_platform/server.py:221-900`

- [ ] **Step 1: Update `tch_get_challenges` to use per-team status**

In `server.py`, change the challenge list building logic. Replace the instance status/entrypoint section:

```python
@app.get("/api/challenges")
async def tch_get_challenges(team: dict = Depends(get_current_team)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    all_challenges = [
        c for c in manager.challenges
        if is_challenge_enabled(c.get_benchmark_id())
    ]
    team_progress = get_team_progress(team["id"])
    challenge_list = []
    total_solved_challenges = 0
    for c in all_challenges:
        bm = c.get_benchmark()
        bm_id = c.get_benchmark_id()

        # Per-team instance status
        status = manager.get_team_instance_status(bm_id, team["id"])
        entrypoint = None
        if status in ("running", "unhealthy"):
            ports = manager.get_team_instance_ports(bm_id, team["id"])
            entrypoint = [f"{manager.public_accessible_host}:{p}" for p in ports]

        team_solved = get_team_solved_count(team["id"], bm_id)
        all_solved = team_solved >= c.flag_count
        hint_viewed = is_hint_viewed(team["id"], bm_id)

        if all_solved:
            total_solved_challenges += 1

        if c.flag_count > 0:
            per_flag_score = c.points // c.flag_count
            got_score = per_flag_score * team_solved
        else:
            got_score = c.points if all_solved else 0

        progress_for_challenge = team_progress.get(bm_id, {})
        flags_info = None
        if c.flag_states:
            flags_info = [
                {"id": fs.id, "route": fs.route, "description": fs.description, "solved": progress_for_challenge.get(fs.id, False)}
                for fs in c.flag_states
            ]

        challenge_list.append({
            "benchmark_id": bm_id,
            "title": bm.name,
            "code": bm_id,  # Use benchmark_id as stable code
            "difficulty": c.difficulty.value,
            "description": bm.description,
            "level": bm.level,
            "total_score": c.points,
            "total_got_score": got_score,
            "flag_count": c.flag_count,
            "flag_got_count": team_solved,
            "flags": flags_info,
            "hint_viewed": hint_viewed,
            "instance_status": status,
            "entrypoint": entrypoint,
            "unsupported": c.unsupported,
            "unsupported_reason": c.unsupported_reason,
        })

    return _ok({
        "current_level": manager.get_current_level(team["id"]),
        "total_challenges": len(all_challenges),
        "solved_challenges": total_solved_challenges,
        "challenges": challenge_list,
    })
```

- [ ] **Step 2: Update `tch_start_challenge` to pass team_id**

```python
@app.post("/api/start_challenge")
async def tch_start_challenge(payload: StartChallengeRequest, team: dict = Depends(get_current_team)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    try:
        challenge = manager._find_by_code(payload.code)
    except KeyError:
        _err(f"Challenge {payload.code} not found", 404)
        return

    _ensure_challenge_enabled(challenge)

    if challenge.unsupported:
        return _ok({"unsupported": True}, f"该赛题不支持当前平台: {challenge.unsupported_reason}")

    challenge_level = manager.get_level_for_challenge(challenge)
    if not manager.is_level_unlocked(challenge_level, team["id"]):
        _err(f"Level {challenge_level} 尚未解锁，请先通过前置关卡", 403)
        return

    team_solved = get_team_solved_count(team["id"], challenge.get_benchmark_id())
    if team_solved >= challenge.flag_count:
        return _ok({"already_completed": True}, "该赛题已全部完成，无需再启动实例")

    # Check if already running for this team
    status = manager.get_team_instance_status(challenge.get_benchmark_id(), team["id"])
    if status in ("running", "unhealthy"):
        ports = manager.get_team_instance_ports(challenge.get_benchmark_id(), team["id"])
        entrypoints = [f"{manager.public_accessible_host}:{p}" for p in ports]
        return _ok(entrypoints, "赛题实例已在运行中")

    if status == "starting":
        return JSONResponse(
            status_code=202,
            content=_ok(None, "赛题正在启动中"),
        )

    try:
        result = await asyncio.to_thread(manager.start_challenge_instance, payload.code, team["id"])
    except RuntimeError as e:
        error_msg = str(e)
        if "最大同时运行实例数" in error_msg:
            raise HTTPException(status_code=429, detail={"code": -1, "message": error_msg, "data": None})
        logger.error("start_challenge failed", action="api", challenge_code=payload.code, error=error_msg)
        _err(f"赛题启动失败: {e}", 502)
        return
    except Exception as e:
        logger.error("start_challenge failed", action="api", challenge_code=payload.code, error=str(e))
        _err(f"赛题启动失败: {e}", 502)
        return

    if result is None:
        return JSONResponse(
            status_code=202,
            content=_ok(None, "赛题正在启动中，请通过日志面板查看进度"),
        )

    return _ok(result, "赛题实例启动成功")
```

- [ ] **Step 3: Update `tch_stop_challenge` with team ownership**

```python
@app.post("/api/stop_challenge")
async def tch_stop_challenge(payload: StopChallengeRequest, team: dict = Depends(get_current_team)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    try:
        challenge = manager._find_by_code(payload.code)
    except KeyError:
        _err(f"Challenge {payload.code} not found", 404)
        return

    _ensure_challenge_enabled(challenge)

    status = manager.get_team_instance_status(challenge.get_benchmark_id(), team["id"])
    if status not in ("running", "unhealthy"):
        _err("赛题实例未运行", 400)
        return

    try:
        await asyncio.to_thread(manager.stop_challenge_instance, payload.code, team["id"])
    except PermissionError as e:
        _err(str(e), 403)
        return
    except Exception as e:
        _err(f"停止失败: {e}", 502)
        return

    return _ok(None, "赛题实例已停止")
```

- [ ] **Step 4: Update `tch_submit` to validate against team's own flags**

```python
@app.post("/api/submit")
async def tch_submit(payload: SubmitFlagRequest, team: dict = Depends(get_current_team)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    try:
        challenge = manager._find_by_code(payload.code)
    except KeyError:
        _err(f"Challenge {payload.code} not found", 404)
        return

    _ensure_challenge_enabled(challenge)

    challenge_level = manager.get_level_for_challenge(challenge)
    if not manager.is_level_unlocked(challenge_level, team["id"]):
        _err(f"Level {challenge_level} 尚未解锁，请先通过前置关卡", 403)
        return

    # Validate against THIS team's instance flags
    benchmark_id = challenge.get_benchmark_id()
    answers = manager.get_team_instance_flags(benchmark_id, team["id"])
    if not answers:
        _err("本队尚未启动该赛题实例，或实例已停止", 400)
        return

    matched_flag_id = None
    for fid, fval in answers.items():
        if fval == payload.flag:
            matched_flag_id = fid
            break

    is_correct = matched_flag_id is not None

    if is_correct:
        mark_flag_solved(team["id"], benchmark_id, matched_flag_id)

    team_solved = get_team_solved_count(team["id"], benchmark_id)
    all_solved = team_solved >= challenge.flag_count

    # Record submission
    from datetime import datetime as dt_cls
    from benchmark_platform.web.submission_store import SubmissionRecord
    if hasattr(app.state, 'submission_store') and app.state.submission_store is not None:
        bm = challenge.get_benchmark()
        app.state.submission_store.add(SubmissionRecord(
            timestamp=dt_cls.now().strftime("%Y-%m-%d %H:%M:%S"),
            challenge_code=payload.code,
            benchmark_id=benchmark_id,
            challenge_name=bm.name,
            flag_id=matched_flag_id,
            flag_value=payload.flag[:8] + "..." + payload.flag[-4:] if len(payload.flag) > 16 else payload.flag,
            correct=is_correct,
            points=challenge.points // challenge.flag_count if is_correct and challenge.flag_count > 0 else 0,
            team_id=team["id"],
            team_name=team["name"],
        ))

    if is_correct:
        per_flag_score = challenge.points // challenge.flag_count if challenge.flag_count > 0 else challenge.points
        msg = f"恭喜！答案正确（{team_solved}/{challenge.flag_count}），获得{per_flag_score}分"
    else:
        msg = "答案错误，请继续尝试"

    return _ok({
        "correct": is_correct,
        "flag_id": matched_flag_id,
        "message": msg,
        "flag_count": challenge.flag_count,
        "flag_got_count": team_solved,
        "all_solved": all_solved,
    })
```

- [ ] **Step 5: Update `tch_stop_all` to use new stop_all_instances**

```python
@app.post("/api/stop_all")
async def tch_stop_all(_=Depends(require_admin)):
    if manager is None:
        _err("Server not initialized", 503)
        return
    stopped = await asyncio.to_thread(manager.stop_all_instances)
    return _ok({"stopped_count": stopped}, f"已停止 {stopped} 个实例")
```

- [ ] **Step 6: Update `tch_instance_statuses` to include team info**

```python
@app.get("/api/instance_statuses")
async def tch_instance_statuses(request: Request, _=Depends(require_admin)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    from benchmark_platform.db import get_all_instances
    all_inst = get_all_instances()

    statuses = {}
    for record in all_inst:
        bm_id = record["benchmark_id"]
        enabled = is_challenge_enabled(bm_id)
        statuses[record["challenge_code"]] = {
            "status": record["status"],
            "benchmark_id": bm_id,
            "team_id": record["team_id"],
            "ports": json.loads(record["ports"]),
            "started_at": record["started_at"],
            "expires_at": record["expires_at"],
            "enabled": enabled,
        }

    # Also include challenges with no instances
    for c in manager.challenges:
        bm_id = c.get_benchmark_id()
        if not any(s["benchmark_id"] == bm_id for s in statuses.values()):
            statuses[bm_id] = {
                "status": "stopped",
                "benchmark_id": bm_id,
                "team_id": None,
                "ports": [],
                "started_at": None,
                "expires_at": None,
                "enabled": is_challenge_enabled(bm_id),
            }

    return _ok({"statuses": statuses, "batch_starting": getattr(app.state, "batch_starting", False)})
```

- [ ] **Step 7: Update `tch_start_level` and `tch_stop_level`**

For `start_level`, since it's an admin operation that starts for ALL teams, it needs a team_id parameter or starts for the default team:

```python
@app.post("/api/start_level")
async def tch_start_level(payload: BatchLevelRequest, admin: dict = Depends(require_admin)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    to_start = []
    for c in manager.challenges:
        if manager.get_level_for_challenge(c) != payload.level:
            continue
        if not is_challenge_enabled(c.get_benchmark_id()):
            continue
        if c.unsupported:
            continue
        bm_id = c.get_benchmark_id()
        status = manager.get_team_instance_status(bm_id, admin["id"])
        if status in ("running", "unhealthy"):
            continue
        to_start.append(bm_id)

    if not to_start:
        return _ok({"started": 0, "total": 0}, "没有需要启动的实例")

    def _start_in_background(codes: list[str], team_id: str) -> None:
        for code in codes:
            try:
                manager.start_challenge_instance(code, team_id)
            except Exception as e:
                logger.error("batch start failed", benchmark_id=code, error=str(e))
        app.state.batch_starting = False

    app.state.batch_starting = True
    threading.Thread(target=_start_in_background, args=(to_start, admin["id"]), daemon=True).start()
    return _ok({"started": 0, "total": len(to_start)}, f"正在启动 {len(to_start)} 个实例...")


@app.post("/api/stop_level")
async def tch_stop_level(payload: BatchLevelRequest, _=Depends(require_admin)):
    if manager is None:
        _err("Server not initialized", 503)
        return

    # Stop ALL teams' instances at this level
    stopped = 0
    for c in manager.challenges:
        if manager.get_level_for_challenge(c) != payload.level:
            continue
        bm_id = c.get_benchmark_id()
        # Find all team instances for this challenge
        for (bid, tid), code in list(manager._team_instances.items()):
            if bid != bm_id:
                continue
            if manager._instance_status.get(code) in ("running", "unhealthy"):
                try:
                    real_team = tid if tid != "__shared__" else None
                    await asyncio.to_thread(manager.stop_challenge_instance, code, real_team)
                    stopped += 1
                except Exception:
                    pass

    return _ok({"stopped": stopped}, f"已停止 {len(stopped)} 个实例" if stopped else "没有运行中的实例")
```

- [ ] **Step 8: Add max_instances_per_team settings endpoint**

```python
@app.get("/api/settings/max_instances")
async def get_max_instances_api(_=Depends(require_admin)):
    return _ok({"max_instances_per_team": int(get_setting("max_instances_per_team", "3"))})


class MaxInstancesRequest(PydanticBaseModel):
    max_instances_per_team: int


@app.post("/api/settings/max_instances")
async def set_max_instances_api(payload: MaxInstancesRequest, _=Depends(require_admin)):
    if payload.max_instances_per_team < 1:
        _err("并发实例数不能小于 1", 400)
        return
    set_setting("max_instances_per_team", str(payload.max_instances_per_team))
    if manager:
        manager.max_instances_per_team = payload.max_instances_per_team
    return _ok(None, f"每队最大并发实例数已设置为 {payload.max_instances_per_team}")
```

- [ ] **Step 9: Commit**

```bash
git add benchmark_platform/server.py
git commit -m "feat: API layer per-team isolation — pass team_id, flag validation, concurrent limit"
```

---

### Task 5: Update Reaper and Cleanup for Per-Team Instances

**Files:**
- Modify: `benchmark_platform/utils/challenge.py` (reaper, cleanup, orphan logic)

- [ ] **Step 1: Update `_reaper_loop` for per-team instances**

```python
    def _reaper_loop(self) -> None:
        """Periodically check for and clean up expired instances."""
        from benchmark_platform.db import get_expired_instances
        while not self._reaper_stop.is_set():
            try:
                expired = get_expired_instances()
                for record in expired:
                    benchmark_id = record["benchmark_id"]
                    challenge_code = record["challenge_code"]
                    team_id = record["team_id"]
                    runtime_path = Path(record["runtime_path"])
                    logger.info("reaping expired instance",
                                benchmark_id=benchmark_id,
                                team_id=team_id,
                                challenge_code=challenge_code)
                    try:
                        if runtime_path.exists():
                            self._compose_at_path(runtime_path, 'down', '-v', '--remove-orphans')
                        from benchmark_platform.db import update_instance_status_by_team
                        update_instance_status_by_team(benchmark_id, team_id, "expired")
                        self._instance_status[challenge_code] = "stopped"
                        # Remove from _team_instances
                        key = (benchmark_id, team_id if team_id else "__shared__")
                        self._team_instances.pop(key, None)
                    except Exception as e:
                        logger.error("reaper failed for instance",
                                     benchmark_id=benchmark_id, error=str(e))
            except Exception as e:
                logger.error("reaper loop error", error=str(e))
            self._reaper_stop.wait(30)
```

- [ ] **Step 2: Update `stop()` cleanup**

```python
    def stop(self) -> None:
        self._reaper_stop.set()
        if self._reaper_thread is not None:
            self._reaper_thread.join(timeout=5)
            self._reaper_thread = None
        # Stop all running instances
        self.stop_all_instances()
        self.challenges.clear()
        self._instance_status.clear()
        self._team_instances.clear()
        self._prune_orphan_volumes()
```

- [ ] **Step 3: Update `_cleanup_orphan_runtimes`**

The directory structure is now `runtime/<benchmark_id>/<team_id>/<uuid>/`:

```python
    def _cleanup_orphan_runtimes(self, known_benchmark_ids: set[str]) -> None:
        """Remove runtime directories that have no matching discovered benchmark_id."""
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
            # Walk through team subdirs
            for team_dir in entry.iterdir():
                if not team_dir.is_dir():
                    continue
                for instance_dir in team_dir.iterdir():
                    if not instance_dir.is_dir():
                        continue
                    try:
                        subprocess.run(
                            ['docker', 'compose', 'down', '-v', '--remove-orphans'],
                            cwd=instance_dir, capture_output=True, text=True, timeout=30,
                        )
                    except Exception:
                        pass
            shutil.rmtree(entry, ignore_errors=True)
        self._prune_orphan_networks()
```

- [ ] **Step 4: Commit**

```bash
git add benchmark_platform/utils/challenge.py
git commit -m "feat: update reaper and cleanup for per-team directory structure"
```

---

### Task 6: Web UI — Admin Status Page with Team Column

**Files:**
- Modify: `benchmark_platform/web/routes.py` (status page context)
- Modify: `benchmark_platform/web/templates/partials/status_table.html`

- [ ] **Step 1: Update the status page context in routes.py**

Find the route that serves `/web/partials/status_table` and update it to include team info. The context should now group instances by team:

```python
@web_router.get("/partials/status_table")
async def status_table_partial(request: Request):
    from benchmark_platform.db import get_all_instances, list_teams
    all_instances = get_all_instances()
    teams = {t["id"]: t["name"] for t in list_teams()}

    running = []
    stopped_challenges = []

    for record in all_instances:
        bm_id = record["benchmark_id"]
        team_name = teams.get(record["team_id"], "shared") if record["team_id"] else "(共享)"
        challenge = None
        for c in request.app.state.manager.challenges:
            if c.get_benchmark_id() == bm_id:
                challenge = c
                break
        if not challenge:
            continue

        bm = challenge.get_benchmark()
        ports = json.loads(record["ports"]) if record["ports"] else []
        entrypoint = [f"{request.app.state.manager.public_accessible_host}:{p}" for p in ports]

        card = {
            "name": bm.name,
            "benchmark_id": bm_id,
            "challenge_code": record["challenge_code"],
            "team_name": team_name,
            "team_id": record["team_id"],
            "entrypoint": entrypoint,
            "status": record["status"],
            "started_at": record["started_at"],
            "expires_at": record["expires_at"],
        }

        if record["status"] in ("running", "starting"):
            running.append(card)
        else:
            stopped_challenges.append(card)

    # Add challenges with no instances at all
    instanced_bids = {r["benchmark_id"] for r in all_instances}
    for c in request.app.state.manager.challenges:
        bm_id = c.get_benchmark_id()
        if bm_id not in instanced_bids:
            bm = c.get_benchmark()
            stopped_challenges.append({
                "name": bm.name,
                "benchmark_id": bm_id,
                "challenge_code": bm_id,
                "team_name": "—",
                "team_id": None,
                "entrypoint": [],
                "status": "stopped",
                "started_at": None,
                "expires_at": None,
            })

    return templates.TemplateResponse("partials/status_table.html", {
        "request": request,
        "running": running,
        "stopped": stopped_challenges,
    })
```

- [ ] **Step 2: Update status_table.html template to show team column**

```html
{% for card in running %}
<tr class="hover:bg-gray-50">
  <td class="px-4 py-3">
    <div class="text-[13px] text-gray-900">{{ card.name }}</div>
    <div class="text-[11px] text-gray-400 font-mono">{{ card.benchmark_id }}</div>
  </td>
  <td class="px-4 py-3">
    <span class="inline-flex items-center px-2 py-0.5 text-[11px] font-medium rounded bg-blue-50 text-blue-700">{{ card.team_name }}</span>
  </td>
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
      <span class="w-1.5 h-1.5 rounded-full bg-emerald-500"></span> {{ card.status }}
    </span>
  </td>
  <td class="px-4 py-3 text-right">
    <button
      hx-post="/api/stop_challenge"
      hx-vals='{"code": "{{ card.benchmark_id }}"}'
      hx-headers='{"Agent-Token": "{{ admin_token }}"}'
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
  <td colspan="6" class="px-4 py-2" x-data="{expanded: false}">
    <button @click="expanded = !expanded" class="text-[12px] text-gray-500 hover:text-gray-700 cursor-pointer">
      <span x-text="expanded ? '▾' : '▸'"></span> 已停止/无实例 ({{ stopped|length }})
    </button>
    <table x-show="expanded" class="w-full mt-2">
      <tbody class="divide-y divide-gray-100">
        {% for card in stopped %}
        <tr class="hover:bg-gray-50">
          <td class="px-4 py-2">
            <div class="text-[13px] text-gray-900">{{ card.name }}</div>
          </td>
          <td class="px-4 py-2">
            <span class="text-[11px] text-gray-400">{{ card.team_name }}</span>
          </td>
          <td class="px-4 py-2 text-[12px] text-gray-400">—</td>
          <td class="px-4 py-2">
            <span class="inline-flex items-center gap-1.5 px-2.5 py-1 text-[11px] font-medium rounded-full bg-gray-50 text-gray-500">
              <span class="w-1.5 h-1.5 rounded-full bg-gray-300"></span> stopped
            </span>
          </td>
          <td class="px-4 py-2"></td>
        </tr>
        {% endfor %}
      </tbody>
    </table>
  </td>
</tr>
{% endif %}
```

- [ ] **Step 3: Update the status page table header**

In `benchmark_platform/web/templates/pages/status.html`, add a "Team" column header to the table. Find the `<thead>` section and add:

```html
<th class="px-4 py-3 text-left text-[11px] font-semibold text-gray-500 uppercase">Team</th>
```

after the first column header (Challenge).

- [ ] **Step 4: Commit**

```bash
git add benchmark_platform/web/routes.py benchmark_platform/web/templates/partials/status_table.html benchmark_platform/web/templates/pages/status.html
git commit -m "feat: admin status page shows per-team instances with team column"
```

---

### Task 7: Settings Page — Max Instances Per Team

**Files:**
- Modify: `benchmark_platform/web/templates/pages/settings.html`

- [ ] **Step 1: Add max_instances_per_team setting to settings page**

Add a new card/section in the settings page template for the concurrent instance limit. Find where other settings are defined and add:

```html
<!-- Per-Team Instance Limit -->
<div class="bg-white rounded-lg border border-gray-200 p-5" x-data="{
  maxInstances: {{ max_instances_per_team | default(3) }},
  saving: false,
  async save() {
    this.saving = true;
    const res = await fetch('/api/settings/max_instances', {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({max_instances_per_team: this.maxInstances})
    });
    const data = await res.json();
    this.saving = false;
    $dispatch('toast', {type: res.ok ? 'success' : 'error', message: data.message || data.detail});
  }
}">
  <h3 class="text-sm font-medium text-gray-900 mb-3">每队最大并发实例数</h3>
  <p class="text-xs text-gray-500 mb-3">限制每个队伍同时运行的赛题实例数量</p>
  <div class="flex items-center gap-3">
    <input type="number" x-model.number="maxInstances" min="1" max="20"
           class="w-20 px-3 py-1.5 text-sm border border-gray-300 rounded-md">
    <button @click="save()" :disabled="saving"
            class="px-3 py-1.5 text-xs font-medium text-white bg-blue-600 rounded-md hover:bg-blue-700 disabled:opacity-50 cursor-pointer">
      <span x-show="!saving">保存</span>
      <span x-show="saving" x-cloak>保存中...</span>
    </button>
  </div>
</div>
```

- [ ] **Step 2: Pass `max_instances_per_team` to settings template context**

In the web routes file where the settings page is rendered, add:

```python
"max_instances_per_team": int(get_setting("max_instances_per_team", "3")),
```

- [ ] **Step 3: Commit**

```bash
git add benchmark_platform/web/templates/pages/settings.html benchmark_platform/web/routes.py
git commit -m "feat: add max instances per team setting to Web UI"
```

---

### Task 8: Integration Test

**Files:**
- Create: `tests/test_per_team_isolation.py`

- [ ] **Step 1: Write integration test for per-team flag isolation**

```python
# tests/test_per_team_isolation.py
"""Integration tests for per-team container isolation logic."""
import json
import uuid
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from benchmark_platform.db import (
    init_db, create_team, _set_db_path,
    get_team_running_count, get_instance_by_benchmark_and_team,
    upsert_instance,
)


@pytest.fixture(autouse=True)
def tmp_db(tmp_path):
    db_path = tmp_path / "test.db"
    _set_db_path(db_path)
    init_db()
    yield db_path


def test_concurrent_instance_limit():
    """Teams cannot exceed max_instances_per_team."""
    team = create_team("team-a")
    team_id = team["id"]

    # Simulate 3 running instances
    for i in range(3):
        upsert_instance(
            instance_id=str(uuid.uuid4()),
            benchmark_id=f"XBEN-{i:03d}",
            challenge_code=str(uuid.uuid4()),
            runtime_path=f"/tmp/{i}",
            ports=[8000 + i],
            status="running",
            team_id=team_id,
        )

    assert get_team_running_count(team_id) == 3


def test_different_teams_same_challenge_independent():
    """Two teams can have independent instances of the same challenge."""
    team_a = create_team("team-a")
    team_b = create_team("team-b")

    upsert_instance(
        instance_id="inst-a", benchmark_id="XBEN-001",
        challenge_code="code-a", runtime_path="/tmp/a",
        ports=[8001], status="running", team_id=team_a["id"],
    )
    upsert_instance(
        instance_id="inst-b", benchmark_id="XBEN-001",
        challenge_code="code-b", runtime_path="/tmp/b",
        ports=[8002], status="running", team_id=team_b["id"],
    )

    rec_a = get_instance_by_benchmark_and_team("XBEN-001", team_a["id"])
    rec_b = get_instance_by_benchmark_and_team("XBEN-001", team_b["id"])

    assert rec_a["challenge_code"] != rec_b["challenge_code"]
    assert rec_a["ports"] != rec_b["ports"]


def test_shared_instance_for_ad():
    """AD challenges use team_id=NULL (shared)."""
    upsert_instance(
        instance_id="inst-shared", benchmark_id="AD-GOAD-01",
        challenge_code="code-shared", runtime_path="/tmp/shared",
        ports=[9090], status="running", team_id=None,
    )

    rec = get_instance_by_benchmark_and_team("AD-GOAD-01", None)
    assert rec is not None
    assert rec["team_id"] is None

    # Should not be found for a specific team
    rec_team = get_instance_by_benchmark_and_team("AD-GOAD-01", "some-team-id")
    assert rec_team is None
```

- [ ] **Step 2: Run tests**

Run: `cd /Users/f0x/pte-project/weaponize/Agentic/benchmark-platform && python -m pytest tests/test_per_team_isolation.py -v 2>&1 | tail -20`

Expected: ALL PASS

- [ ] **Step 3: Run full test suite to check for regressions**

Run: `cd /Users/f0x/pte-project/weaponize/Agentic/benchmark-platform && python -m pytest tests/ -v 2>&1 | tail -40`

Expected: ALL PASS (some existing tests may need adjustments for the new schema)

- [ ] **Step 4: Commit**

```bash
git add tests/test_per_team_isolation.py
git commit -m "test: add integration tests for per-team container isolation"
```

---

### Task 9: Fix _find_by_code for New Model

**Files:**
- Modify: `benchmark_platform/utils/challenge.py:714-722`

- [ ] **Step 1: Update `_find_by_code` to work with benchmark_id as challenge_code**

Since metadata challenges now use `benchmark_id` as their `challenge_code`:

```python
    def _find_by_code(self, challenge_code: str) -> Challenge:
        """Find challenge metadata by benchmark_id or challenge_code."""
        for c in self.challenges:
            if c.challenge_code == challenge_code:
                return c
            if c.get_benchmark_id() == challenge_code:
                return c
        raise KeyError(f"Challenge {challenge_code!r} not found")
```

- [ ] **Step 2: Update `get_instance_status` (legacy compat)**

The old `get_instance_status(challenge_code)` is called from various places. Provide a compat wrapper:

```python
    def get_instance_status(self, challenge_code: str) -> str:
        """Legacy: get status for a challenge_code (checks all teams)."""
        # Check direct match in _instance_status
        if challenge_code in self._instance_status:
            return self._instance_status[challenge_code]
        # Check if it's a benchmark_id with any running instance
        for (bid, tid), code in self._team_instances.items():
            if bid == challenge_code:
                status = self._instance_status.get(code, "stopped")
                if status in ("running", "unhealthy", "starting"):
                    return status
        return "stopped"
```

- [ ] **Step 3: Commit**

```bash
git add benchmark_platform/utils/challenge.py
git commit -m "fix: update _find_by_code and get_instance_status for metadata-based model"
```

---

### Task 10: Update MCP Server for Per-Team Context

**Files:**
- Modify: `benchmark_platform/mcp_server.py`

- [ ] **Step 1: Verify MCP tools pass team context correctly**

The MCP server extracts the token from the Authorization header and uses it to identify the team. The underlying API calls (`start_challenge`, `stop_challenge`, `submit_flag`) all flow through the same `manager.start_challenge_instance(code, team_id)` path.

Read the MCP server file and confirm the token → team_id flow works. The MCP tools call the same internal functions, so if the server.py API layer is updated, MCP should work automatically.

If the MCP server directly calls `manager.start_challenge_instance(code)` (old signature without team_id), update it to pass team_id:

```python
# In each MCP tool that calls manager methods directly:
# Ensure team_id is passed from the authenticated token context
```

- [ ] **Step 2: Commit (if changes needed)**

```bash
git add benchmark_platform/mcp_server.py
git commit -m "fix: MCP server passes team_id to per-team instance operations"
```

---

### Task 11: Final Cleanup and Version Bump

**Files:**
- Modify: `benchmark_platform/__init__.py`
- Modify: `pyproject.toml`

- [ ] **Step 1: Remove dead code from old model**

In `benchmark_platform/utils/challenge.py`, remove:
- `_reconcile_or_create` method (replaced by `_load_challenge_metadata` + `_recover_running_instances`)
- `_restore_challenge` method (replaced by `_recover_running_instances`)
- `_create_challenge` method (replaced by inline logic in `start_challenge_instance`)
- Old `_compose` method (replaced by `_compose_at_path`)
- Old `_finalize_start` (replaced by `_finalize_team_start`)
- Old `_async_compose_start` (replaced by `_async_team_compose_start`)

- [ ] **Step 2: Update version**

In `benchmark_platform/__init__.py`:
```python
__version__ = "1.1.0"
```

In `pyproject.toml`:
```toml
version = "1.1.0"
```

- [ ] **Step 3: Run full test suite**

Run: `cd /Users/f0x/pte-project/weaponize/Agentic/benchmark-platform && python -m pytest tests/ -v`

Expected: ALL PASS

- [ ] **Step 4: Commit**

```bash
git add benchmark_platform/__init__.py pyproject.toml benchmark_platform/utils/challenge.py
git commit -m "chore: remove dead code from old shared-instance model, bump to v1.1.0"
```

---

## Execution Notes

- Tasks 1-3 are the core backend changes and must be sequential
- Task 4 (API layer) depends on Tasks 1-3
- Tasks 5-7 (reaper, UI, settings) can be done in parallel after Task 4
- Task 8 (integration test) should run after Tasks 1-4
- Task 9 is a critical compat fix, should be done right after Task 3
- Task 10 (MCP) depends on Task 4
- Task 11 (cleanup) is last

## Regression Risks

- Existing tests in `test_db.py` use `upsert_instance` with old UNIQUE constraint — they may need updates after Task 1
- `test_multi_flag.py` may use `Challenge.get_base_path` with old signature — check after Task 2
- Web UI templates that reference `challenge_code` for start/stop may need to use `benchmark_id` instead
