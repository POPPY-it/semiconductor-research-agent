"""SQLite 存储：文章去重入库 + 采集运行日志。"""
from __future__ import annotations

import json
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS articles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT NOT NULL,
    published_at TEXT DEFAULT '',
    extra TEXT DEFAULT '{}',
    fetched_at TEXT NOT NULL,
    UNIQUE(source, url)
);
CREATE INDEX IF NOT EXISTS idx_articles_source ON articles(source);
CREATE TABLE IF NOT EXISTS collect_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    source TEXT NOT NULL,
    status TEXT NOT NULL,
    message TEXT DEFAULT '',
    items INTEGER DEFAULT 0,
    ran_at TEXT NOT NULL
);
"""


class SQLiteStore:
    def __init__(self, db_path: str | Path):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self.db_path = str(db_path)
        self._conn = sqlite3.connect(self.db_path)
        self._conn.executescript(SCHEMA)
        self._conn.commit()

    def upsert_articles(self, items: list[dict]) -> int:
        """插入文章，(source,url) 去重；返回新增条数。"""
        new_count = 0
        cur = self._conn.cursor()
        for it in items:
            cur.execute(
                """
                INSERT OR IGNORE INTO articles
                    (source, title, url, published_at, extra, fetched_at)
                VALUES (?, ?, ?, ?, ?, datetime('now', 'localtime'))
                """,
                (
                    it.get("source", ""),
                    it.get("title", ""),
                    it.get("url", ""),
                    it.get("published_at", ""),
                    json.dumps(it.get("extra", {}), ensure_ascii=False),
                ),
            )
            if cur.rowcount == 1:
                new_count += 1
        self._conn.commit()
        return new_count

    def log(self, source: str, status: str, message: str = "", items: int = 0) -> None:
        self._conn.execute(
            "INSERT INTO collect_log (source, status, message, items, ran_at) "
            "VALUES (?, ?, ?, ?, datetime('now', 'localtime'))",
            (source, status, message, items),
        )
        self._conn.commit()

    def count(self) -> int:
        return self._conn.execute("SELECT COUNT(*) FROM articles").fetchone()[0]

    def close(self) -> None:
        self._conn.close()
