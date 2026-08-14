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
    content TEXT DEFAULT '',
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
        self._migrate()
        self._conn.commit()

    def _migrate(self) -> None:
        """轻量迁移：为已存在的库补 content 列。"""
        cols = {row[1] for row in self._conn.execute("PRAGMA table_info(articles)")}
        if "content" not in cols:
            self._conn.execute("ALTER TABLE articles ADD COLUMN content TEXT DEFAULT ''")

    def upsert_articles(self, items: list[dict]) -> int:
        """插入文章，(source,url) 去重；返回新增条数。"""
        new_count = 0
        cur = self._conn.cursor()
        for it in items:
            cur.execute(
                """
                INSERT OR IGNORE INTO articles
                    (source, title, url, published_at, extra, content, fetched_at)
                VALUES (?, ?, ?, ?, ?, ?, datetime('now', 'localtime'))
                """,
                (
                    it.get("source", ""),
                    it.get("title", ""),
                    it.get("url", ""),
                    it.get("published_at", ""),
                    json.dumps(it.get("extra", {}), ensure_ascii=False),
                    it.get("content", ""),
                ),
            )
            if cur.rowcount == 1:
                new_count += 1
        self._conn.commit()
        return new_count

    def update_content(self, url: str, content: str) -> None:
        self._conn.execute("UPDATE articles SET content = ? WHERE url = ?", (content, url))
        self._conn.commit()

    def query_articles(
        self,
        source: str | None = None,
        keyword: str | None = None,
        only_with_content: bool = False,
        limit: int = 50,
    ) -> list[dict]:
        sql = "SELECT source, title, url, published_at, extra, content FROM articles WHERE 1=1"
        args: list = []
        if source:
            sql += " AND source = ?"
            args.append(source)
        if keyword:
            sql += " AND (title LIKE ? OR content LIKE ?)"
            args += [f"%{keyword}%", f"%{keyword}%"]
        if only_with_content:
            sql += " AND content != ''"
        sql += " ORDER BY id DESC LIMIT ?"
        args.append(limit)
        rows = self._conn.execute(sql, args).fetchall()
        return [
            {
                "source": r[0],
                "title": r[1],
                "url": r[2],
                "published_at": r[3],
                "extra": json.loads(r[4] or "{}"),
                "content": r[5],
            }
            for r in rows
        ]

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
