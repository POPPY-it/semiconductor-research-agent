"""会话与报告存储（SQLite，线程安全：锁 + 自动提交）。"""
from __future__ import annotations

import json
import sqlite3
import threading
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
CREATE TABLE IF NOT EXISTS qa_conversations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    title TEXT NOT NULL DEFAULT '新对话',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS qa_messages (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    conversation_id INTEGER NOT NULL,
    role TEXT NOT NULL,
    content TEXT NOT NULL,
    sources TEXT DEFAULT '[]',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS mcp_servers (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    command TEXT NOT NULL,
    args TEXT NOT NULL DEFAULT '[]',
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
        # isolation_level=None → 自动提交，避免跨线程事务冲突；加锁兜底并发写
        self._conn = sqlite3.connect(
            str(db_path), check_same_thread=False, isolation_level=None
        )
        self._lock = threading.Lock()
        self._conn.executescript(SCHEMA)

    def create(self, topic: str, report_type: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO sessions (topic, report_type, status, created_at) "
                "VALUES (?, ?, ?, datetime('now', 'localtime'))",
                (topic, report_type, STATUS_QUEUED),
            )
        return cur.lastrowid

    def set_status(self, session_id: int, status: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE sessions SET status = ?, finished_at = CASE WHEN ? IN ('done','error') "
                "THEN datetime('now','localtime') ELSE finished_at END WHERE id = ?",
                (status, status, session_id),
            )

    def save_report(self, session_id: int, verdict: dict, rounds: int, path: str, md: str) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO reports (session_id, verdict, revision_rounds, report_path, report_md, created_at) "
                "VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))",
                (session_id, json.dumps(verdict, ensure_ascii=False), rounds, path, md),
            )

    def recover_stale(self) -> int:
        """进程重启恢复：把中断在 queued/running 的会话标记为 error（可重试）。"""
        with self._lock:
            cur = self._conn.execute(
                "UPDATE sessions SET status = 'error', finished_at = datetime('now','localtime') "
                "WHERE status IN ('queued', 'running')"
            )
        return cur.rowcount

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

    # ---- 多轮问答会话（P1）----

    def create_conversation(self, title: str) -> int:
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO qa_conversations (title, created_at) VALUES (?, datetime('now','localtime'))",
                (title[:60] or "新对话",),
            )
        return cur.lastrowid

    def add_qa_message(self, conversation_id: int, role: str, content: str, sources: list | None = None) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO qa_messages (conversation_id, role, content, sources, created_at) "
                "VALUES (?, ?, ?, ?, datetime('now','localtime'))",
                (conversation_id, role, content, json.dumps(sources or [], ensure_ascii=False)),
            )

    def get_qa_history(self, conversation_id: int, limit: int = 20) -> list[dict]:
        rows = self._conn.execute(
            "SELECT role, content, sources FROM qa_messages WHERE conversation_id = ? ORDER BY id DESC LIMIT ?",
            (conversation_id, limit),
        ).fetchall()
        return [
            {"role": r[0], "content": r[1], "sources": json.loads(r[2] or "[]")}
            for r in reversed(rows)
        ]

    def list_conversations(self, limit: int = 50) -> list[dict]:
        rows = self._conn.execute(
            "SELECT c.id, c.title, c.created_at, "
            "(SELECT COUNT(*) FROM qa_messages m WHERE m.conversation_id = c.id) AS msg_count "
            "FROM qa_conversations c ORDER BY c.id DESC LIMIT ?",
            (limit,),
        ).fetchall()
        return [
            {"id": r[0], "title": r[1], "created_at": r[2], "msg_count": r[3]}
            for r in rows
        ]

    # ---- MCP Server 注册表（网页端可管理）----

    def seed_mcp_defaults(self, defaults: list[dict]) -> None:
        """内置默认 Server（github/fetch），仅在表空时播种。"""
        count = self._conn.execute("SELECT COUNT(*) FROM mcp_servers").fetchone()[0]
        if count:
            return
        with self._lock:
            for d in defaults:
                self._conn.execute(
                    "INSERT OR IGNORE INTO mcp_servers (name, command, args, created_at) "
                    "VALUES (?, ?, ?, datetime('now','localtime'))",
                    (d["name"], d["command"], json.dumps(d.get("args", []))),
                )

    def list_mcp_servers(self) -> list[dict]:
        rows = self._conn.execute(
            "SELECT name, command, args, created_at FROM mcp_servers ORDER BY id"
        ).fetchall()
        return [
            {"name": r[0], "command": r[1], "args": json.loads(r[2] or "[]"), "created_at": r[3]}
            for r in rows
        ]

    def add_mcp_server(self, name: str, command: str, args: list[str]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO mcp_servers (name, command, args, created_at) "
                "VALUES (?, ?, ?, datetime('now','localtime'))",
                (name, command, json.dumps(args or [])),
            )

    def delete_mcp_server(self, name: str) -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM mcp_servers WHERE name = ?", (name,))
        return cur.rowcount
