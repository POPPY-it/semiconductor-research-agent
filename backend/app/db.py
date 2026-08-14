"""会话与报告存储（SQLite）。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS sessions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    topic TEXT NOT NULL,
    report_type TEXT NOT NULL DEFAULT 'weekly',
    status TEXT NOT NULL DEFAULT 'queued',
    created_at TEXT NOT NULL,
    finished_at TEXT
);
CREATE TABLE IF NOT EXISTS reports (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    session_id INTEGER NOT NULL,
    verdict TEXT DEFAULT '',
    revision_rounds INTEGER DEFAULT 0,
    report_path TEXT DEFAULT '',
    report_md TEXT DEFAULT '',
    created_at TEXT NOT NULL
);
"""

STATUS_QUEUED = "queued"
STATUS_RUNNING = "running"
STATUS_DONE = "done"
STATUS_ERROR = "error"


class SessionStore:
    def __init__(self, db_path: str | Path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def create(self, topic: str, report_type: str) -> int:
        cur = self._conn.execute(
            "INSERT INTO sessions (topic, report_type, status, created_at) "
            "VALUES (?, ?, ?, datetime('now', 'localtime'))",
            (topic, report_type, STATUS_QUEUED),
        )
        self._conn.commit()
        return cur.lastrowid

    def set_status(self, session_id: int, status: str) -> None:
        self._conn.execute(
            "UPDATE sessions SET status = ?, finished_at = CASE WHEN ? IN ('done','error') "
            "THEN datetime('now','localtime') ELSE finished_at END WHERE id = ?",
            (status, status, session_id),
        )
        self._conn.commit()

    def save_report(self, session_id: int, verdict: dict, rounds: int, path: str, md: str) -> None:
        self._conn.execute(
            "INSERT INTO reports (session_id, verdict, revision_rounds, report_path, report_md, created_at) "
            "VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))",
            (session_id, json.dumps(verdict, ensure_ascii=False), rounds, path, md),
        )
        self._conn.commit()

    def get(self, session_id: int) -> dict | None:
        row = self._conn.execute(
            "SELECT id, topic, report_type, status, created_at, finished_at FROM sessions WHERE id = ?",
            (session_id,),
        ).fetchone()
        if not row:
            return None
        report = self._conn.execute(
            "SELECT verdict, revision_rounds, report_path, created_at FROM reports "
            "WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        out = {
            "id": row[0],
            "topic": row[1],
            "report_type": row[2],
            "status": row[3],
            "created_at": row[4],
            "finished_at": row[5],
        }
        if report:
            out["report"] = {
                "verdict": json.loads(report[0] or "{}"),
                "revision_rounds": report[1],
                "report_path": report[2],
                "created_at": report[3],
            }
        return out

    def get_report_md(self, session_id: int) -> str:
        row = self._conn.execute(
            "SELECT report_md FROM reports WHERE session_id = ? ORDER BY id DESC LIMIT 1",
            (session_id,),
        ).fetchone()
        return row[0] if row else ""

    def list(self, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT id, topic, report_type, status, created_at FROM sessions ORDER BY id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {
                "id": r[0],
                "topic": r[1],
                "report_type": r[2],
                "status": r[3],
                "created_at": r[4],
            }
            for r in rows
        ]

    def close(self) -> None:
        self._conn.close()
