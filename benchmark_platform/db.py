# benchmark_platform/db.py
"""SQLite database for team management and per-team progress."""

import json
import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import local
from typing import Dict, List, Optional

_DB_PATH = Path("data/benchmark.db")
_local = local()


def _set_db_path(path: Path) -> None:
    """Override DB path (for testing)."""
    global _DB_PATH
    _DB_PATH = path
    if hasattr(_local, "conn"):
        del _local.conn


def _get_conn() -> sqlite3.Connection:
    if not hasattr(_local, "conn") or _local.conn is None:
        _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(_DB_PATH), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA journal_mode=WAL")
        conn.execute("PRAGMA foreign_keys=ON")
        _local.conn = conn
    return _local.conn


def init_db() -> None:
    conn = _get_conn()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS teams (
            id         TEXT PRIMARY KEY,
            name       TEXT UNIQUE NOT NULL,
            token      TEXT UNIQUE NOT NULL,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );
        CREATE TABLE IF NOT EXISTS team_progress (
            team_id        TEXT NOT NULL,
            benchmark_id   TEXT NOT NULL,
            flag_id        TEXT NOT NULL,
            solved         INTEGER NOT NULL DEFAULT 0,
            solved_at      TEXT,
            PRIMARY KEY (team_id, benchmark_id, flag_id)
        );
        CREATE TABLE IF NOT EXISTS team_hints (
            team_id        TEXT NOT NULL,
            benchmark_id   TEXT NOT NULL,
            viewed_at      TEXT NOT NULL DEFAULT (datetime('now')),
            PRIMARY KEY (team_id, benchmark_id)
        );
        CREATE TABLE IF NOT EXISTS settings (
            key   TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );
        CREATE TABLE IF NOT EXISTS challenge_visibility (
            benchmark_id TEXT PRIMARY KEY,
            enabled      INTEGER NOT NULL DEFAULT 1,
            updated_at   TEXT NOT NULL DEFAULT (datetime('now'))
        );
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
    """)
    # Migrate old schema: rename challenge_code → benchmark_id if needed
    try:
        cols = [r[1] for r in conn.execute("PRAGMA table_info(team_progress)").fetchall()]
        if "challenge_code" in cols and "benchmark_id" not in cols:
            conn.execute("ALTER TABLE team_progress RENAME COLUMN challenge_code TO benchmark_id")
            conn.commit()
        cols_h = [r[1] for r in conn.execute("PRAGMA table_info(team_hints)").fetchall()]
        if "challenge_code" in cols_h and "benchmark_id" not in cols_h:
            conn.execute("ALTER TABLE team_hints RENAME COLUMN challenge_code TO benchmark_id")
            conn.commit()
    except Exception:
        pass
    conn.commit()

    # Migrate instance_lifecycle: ensure correct schema with team_id + compound UNIQUE
    try:
        cols_il = [r[1] for r in conn.execute("PRAGMA table_info(instance_lifecycle)").fetchall()]
        needs_recreate = "team_id" not in cols_il
        if not needs_recreate:
            # Check if old UNIQUE(benchmark_id) constraint exists (needs compound UNIQUE instead)
            schema = conn.execute(
                "SELECT sql FROM sqlite_master WHERE name='instance_lifecycle'"
            ).fetchone()[0]
            if "benchmark_id   TEXT NOT NULL UNIQUE" in schema or "UNIQUE(benchmark_id, team_id)" not in schema:
                needs_recreate = True
        if needs_recreate:
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


def create_team(name: str) -> dict:
    conn = _get_conn()
    team_id = str(uuid.uuid4())
    token = secrets.token_hex(16)
    try:
        conn.execute(
            "INSERT INTO teams (id, name, token) VALUES (?, ?, ?)",
            (team_id, name, token),
        )
        conn.commit()
    except sqlite3.IntegrityError:
        raise ValueError(f"Team '{name}' already exists")
    return {"id": team_id, "name": name, "token": token}


def list_teams() -> list:
    conn = _get_conn()
    rows = conn.execute("""
        SELECT t.id, t.name, t.token, t.created_at,
               COALESCE(SUM(p.solved), 0) as solved_flags
        FROM teams t
        LEFT JOIN team_progress p ON t.id = p.team_id AND p.solved = 1
        GROUP BY t.id
        ORDER BY t.created_at ASC
    """).fetchall()
    return [dict(r) for r in rows]


def get_team_by_token(token: str):
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, name, token, created_at FROM teams WHERE token = ?",
        (token,),
    ).fetchone()
    return dict(row) if row else None


def get_or_create_default_team(token: Optional[str] = None) -> dict:
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, name, token, created_at FROM teams WHERE name = 'default'"
    ).fetchone()
    if row:
        team = dict(row)
        if token and team["token"] != token:
            conn.execute("UPDATE teams SET token = ? WHERE id = ?", (token, team["id"]))
            conn.commit()
            team["token"] = token
        return team
    if token:
        team_id = str(uuid.uuid4())
        conn.execute(
            "INSERT INTO teams (id, name, token) VALUES (?, ?, ?)",
            (team_id, "default", token),
        )
        conn.commit()
        return {"id": team_id, "name": "default", "token": token}
    return create_team("default")


def mark_flag_solved(team_id: str, benchmark_id: str, flag_id: str) -> None:
    conn = _get_conn()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT OR IGNORE INTO team_progress (team_id, benchmark_id, flag_id, solved, solved_at) VALUES (?, ?, ?, 1, ?)",
        (team_id, benchmark_id, flag_id, now),
    )
    conn.commit()


def get_team_solved_count(team_id: str, benchmark_id: str) -> int:
    conn = _get_conn()
    row = conn.execute(
        "SELECT COUNT(*) as cnt FROM team_progress WHERE team_id = ? AND benchmark_id = ? AND solved = 1",
        (team_id, benchmark_id),
    ).fetchone()
    return row["cnt"]


def is_hint_viewed(team_id: str, benchmark_id: str) -> bool:
    conn = _get_conn()
    row = conn.execute(
        "SELECT 1 FROM team_hints WHERE team_id = ? AND benchmark_id = ?",
        (team_id, benchmark_id),
    ).fetchone()
    return row is not None


def mark_hint_viewed(team_id: str, benchmark_id: str) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR IGNORE INTO team_hints (team_id, benchmark_id) VALUES (?, ?)",
        (team_id, benchmark_id),
    )
    conn.commit()


def get_team_progress(team_id: str) -> dict:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT benchmark_id, flag_id, solved FROM team_progress WHERE team_id = ? AND solved = 1",
        (team_id,),
    ).fetchall()
    result: dict = {}
    for r in rows:
        bm_id = r["benchmark_id"]
        if bm_id not in result:
            result[bm_id] = {}
        result[bm_id][r["flag_id"]] = bool(r["solved"])
    return result


def get_team_quiz_progress(team_id: str) -> dict:
    """Return all quiz attempts (correct and incorrect) for accuracy calculation."""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT benchmark_id, flag_id, solved FROM team_progress WHERE team_id = ?",
        (team_id,),
    ).fetchall()
    result: dict = {}
    for r in rows:
        bm_id = r["benchmark_id"]
        if bm_id not in result:
            result[bm_id] = {}
        result[bm_id][r["flag_id"]] = bool(r["solved"])
    return result


def reset_team_progress(team_id: str) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM team_progress WHERE team_id = ?", (team_id,))
    conn.execute("DELETE FROM team_hints WHERE team_id = ?", (team_id,))
    conn.commit()


def get_setting(key: str, default: str = "") -> str:
    conn = _get_conn()
    row = conn.execute("SELECT value FROM settings WHERE key = ?", (key,)).fetchone()
    return row["value"] if row else default


def set_setting(key: str, value: str) -> None:
    conn = _get_conn()
    conn.execute(
        "INSERT OR REPLACE INTO settings (key, value) VALUES (?, ?)",
        (key, value),
    )
    conn.commit()


def is_challenge_enabled(benchmark_id: str) -> bool:
    """题目对 agent 可见性。未在表中视为开启 (默认行为)。"""
    conn = _get_conn()
    try:
        row = conn.execute(
            "SELECT enabled FROM challenge_visibility WHERE benchmark_id = ?",
            (benchmark_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return True
    return True if row is None else bool(row["enabled"])


def set_challenge_enabled(benchmark_id: str, enabled: bool) -> None:
    conn = _get_conn()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        "INSERT INTO challenge_visibility (benchmark_id, enabled, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(benchmark_id) DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at",
        (benchmark_id, 1 if enabled else 0, now),
    )
    conn.commit()


def set_challenges_enabled_bulk(benchmark_ids: List[str], enabled: bool) -> int:
    if not benchmark_ids:
        return 0
    conn = _get_conn()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    flag = 1 if enabled else 0
    conn.executemany(
        "INSERT INTO challenge_visibility (benchmark_id, enabled, updated_at) VALUES (?, ?, ?) "
        "ON CONFLICT(benchmark_id) DO UPDATE SET enabled = excluded.enabled, updated_at = excluded.updated_at",
        [(bid, flag, now) for bid in benchmark_ids],
    )
    conn.commit()
    return len(benchmark_ids)


def get_challenge_visibility() -> dict:
    """返回 {benchmark_id: enabled_bool}, 仅包含表中显式记录过的条目。"""
    conn = _get_conn()
    rows = conn.execute(
        "SELECT benchmark_id, enabled FROM challenge_visibility"
    ).fetchall()
    return {r["benchmark_id"]: bool(r["enabled"]) for r in rows}


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
           ON CONFLICT(id) DO UPDATE SET
             benchmark_id = excluded.benchmark_id,
             team_id = excluded.team_id,
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


def delete_instance(instance_id: str) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM instance_lifecycle WHERE id = ?", (instance_id,))
    conn.commit()


def get_instance_by_benchmark_id(benchmark_id: str) -> Optional[dict]:
    conn = _get_conn()
    row = conn.execute(
        "SELECT * FROM instance_lifecycle WHERE benchmark_id = ?",
        (benchmark_id,),
    ).fetchone()
    return dict(row) if row else None


def get_running_instances() -> List[dict]:
    conn = _get_conn()
    rows = conn.execute(
        "SELECT * FROM instance_lifecycle WHERE status = 'running'"
    ).fetchall()
    return [dict(r) for r in rows]


def get_expired_instances() -> List[dict]:
    conn = _get_conn()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows = conn.execute(
        "SELECT * FROM instance_lifecycle WHERE status = 'running' AND expires_at < ?",
        (now,),
    ).fetchall()
    return [dict(r) for r in rows]


def update_instance_status(benchmark_id: str, status: str,
                           started_at: Optional[str] = None,
                           expires_at: Optional[str] = None) -> None:
    conn = _get_conn()
    now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    conn.execute(
        """UPDATE instance_lifecycle
           SET status = ?, started_at = ?, expires_at = ?, updated_at = ?
           WHERE benchmark_id = ?""",
        (status, started_at, expires_at, now, benchmark_id),
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
    sets = ["status = ?", "updated_at = ?"]
    params: list = [status, now]
    if started_at is not None:
        sets.append("started_at = ?")
        params.append(started_at)
    if expires_at is not None:
        sets.append("expires_at = ?")
        params.append(expires_at)
    set_sql = ", ".join(sets)
    if team_id is None:
        params.append(benchmark_id)
        conn.execute(
            f"UPDATE instance_lifecycle SET {set_sql} WHERE benchmark_id = ? AND team_id IS NULL",
            params,
        )
    else:
        params.extend([benchmark_id, team_id])
        conn.execute(
            f"UPDATE instance_lifecycle SET {set_sql} WHERE benchmark_id = ? AND team_id = ?",
            params,
        )
    conn.commit()


_DEFAULT_INSTANCE_TIMEOUTS = {1: 3600, 2: 7200, 3: 14400}


def get_instance_timeout_config() -> Dict[int, int]:
    result = {}
    for level in (1, 2, 3):
        val = get_setting(f"instance_timeout_level_{level}", None)
        if val is not None:
            result[level] = int(val)
        else:
            result[level] = _DEFAULT_INSTANCE_TIMEOUTS[level]
    return result


def set_instance_timeout_config(config: Dict[int, int]) -> None:
    for level in (1, 2, 3):
        if level in config:
            set_setting(f"instance_timeout_level_{level}", str(config[level]))


def get_level_gate_config() -> dict:
    return {
        "mode": get_setting("level_gate_mode", "all"),
        "threshold": int(get_setting("level_gate_threshold", "100")),
    }


def set_level_gate_config(mode: str, threshold: int) -> dict:
    if mode not in ("all", "percentage", "count"):
        raise ValueError(f"Invalid mode: {mode}")
    if mode == "percentage" and not (1 <= threshold <= 100):
        raise ValueError("Percentage threshold must be between 1 and 100")
    if mode == "count" and threshold < 1:
        raise ValueError("Count threshold must be at least 1")
    set_setting("level_gate_mode", mode)
    set_setting("level_gate_threshold", str(threshold))
    return {"mode": mode, "threshold": threshold}


def get_team_quiz_scores() -> list[dict]:
    """Get MCQ scores per team from team_progress for quiz benchmarks."""
    conn = _get_conn()
    rows = conn.execute("""
        SELECT tp.team_id, t.name as team_name,
               COUNT(*) as answered,
               SUM(CASE WHEN tp.solved = 1 THEN 1 ELSE 0 END) as correct
        FROM team_progress tp
        JOIN teams t ON t.id = tp.team_id
        WHERE tp.benchmark_id LIKE 'SAMPLE-QUIZ%'
           OR tp.benchmark_id LIKE 'CYBERMETRIC%'
           OR tp.benchmark_id LIKE 'SECBENCH%'
           OR tp.benchmark_id LIKE 'CTIBENCH%'
           OR tp.benchmark_id LIKE 'MMLU%'
           OR tp.benchmark_id LIKE 'CISSP%'
        GROUP BY tp.team_id
    """).fetchall()
    return [dict(r) for r in rows]


def get_solve_time_stats() -> list[dict]:
    conn = _get_conn()
    rows = conn.execute("""
        SELECT
            p.benchmark_id,
            p.team_id,
            t.name as team_name,
            p.solved_at,
            il.started_at,
            CAST((julianday(p.solved_at) - julianday(il.started_at)) * 86400 AS INTEGER) as solve_seconds
        FROM team_progress p
        JOIN instance_lifecycle il ON il.benchmark_id = p.benchmark_id AND il.team_id = p.team_id
        JOIN teams t ON t.id = p.team_id
        WHERE p.solved = 1 AND p.solved_at IS NOT NULL AND il.started_at IS NOT NULL
        ORDER BY p.benchmark_id, solve_seconds
    """).fetchall()
    return [dict(r) for r in rows]
