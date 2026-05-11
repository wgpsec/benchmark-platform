# benchmark_platform/db.py
"""SQLite database for team management and per-team progress."""

import secrets
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from threading import local

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
        ORDER BY solved_flags DESC, t.created_at ASC
    """).fetchall()
    return [dict(r) for r in rows]


def get_team_by_token(token: str):
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, name, token, created_at FROM teams WHERE token = ?",
        (token,),
    ).fetchone()
    return dict(row) if row else None


def get_or_create_default_team() -> dict:
    conn = _get_conn()
    row = conn.execute(
        "SELECT id, name, token, created_at FROM teams WHERE name = 'default'"
    ).fetchone()
    if row:
        return dict(row)
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


def reset_team_progress(team_id: str) -> None:
    conn = _get_conn()
    conn.execute("DELETE FROM team_progress WHERE team_id = ?", (team_id,))
    conn.execute("DELETE FROM team_hints WHERE team_id = ?", (team_id,))
    conn.commit()
