"""SQLite access for story_sessions (Story Mode V1.5)."""
from __future__ import annotations

import sqlite3
import threading
from pathlib import Path
from typing import Any, Dict, List, Optional

DEFAULT_DB = Path("data/db/kirara.db")
MIGRATION = Path("migrations/add_story_db.sql")

_lock = threading.RLock()
_conn: Optional[sqlite3.Connection] = None


def db_path() -> Path:
    return DEFAULT_DB


def connect(path: Optional[Path] = None) -> sqlite3.Connection:
    global _conn
    with _lock:
        if _conn is not None:
            return _conn
        p = path or DEFAULT_DB
        p.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(p), check_same_thread=False)
        conn.row_factory = sqlite3.Row
        sql = ""
        if MIGRATION.is_file():
            sql = MIGRATION.read_text(encoding="utf-8")
        else:
            sql = """
            CREATE TABLE IF NOT EXISTS story_sessions (
                session_id TEXT PRIMARY KEY,
                group_id TEXT NOT NULL,
                initiator_qq TEXT NOT NULL,
                status TEXT DEFAULT 'ACTIVE',
                scene_type TEXT,
                scene_desc TEXT,
                participants TEXT,
                turn_count INTEGER DEFAULT 0,
                max_turns INTEGER DEFAULT 7,
                history_log TEXT,
                recipient_meta TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            );
            """
        conn.executescript(sql)
        conn.commit()
        _conn = conn
        return conn


def row_to_dict(row: Optional[sqlite3.Row]) -> Optional[Dict[str, Any]]:
    if row is None:
        return None
    return {k: row[k] for k in row.keys()}


def execute(sql: str, params: tuple = ()) -> None:
    conn = connect()
    with _lock:
        conn.execute(sql, params)
        conn.commit()


def fetchone(sql: str, params: tuple = ()) -> Optional[Dict[str, Any]]:
    conn = connect()
    with _lock:
        cur = conn.execute(sql, params)
        return row_to_dict(cur.fetchone())


def fetchall(sql: str, params: tuple = ()) -> List[Dict[str, Any]]:
    conn = connect()
    with _lock:
        cur = conn.execute(sql, params)
        return [row_to_dict(r) for r in cur.fetchall() if r]
