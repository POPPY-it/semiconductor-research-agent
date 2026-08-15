"""跨会话长期记忆（对标 Mem0）：抽取 → 存储 → 语义召回。

三步走：
1. extract：对话结束后用 LLM 抽取"值得记住"的用户偏好/关注方向/重要事实
2. store：写入 SQLite（持久化）+ 向量索引（语义召回）
3. search：新对话时按问题语义召回相关记忆，注入上下文

设计：单用户产品默认 user_id="default"；embedder 可注入（语义），缺省回退关键词召回。
"""
from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id TEXT NOT NULL DEFAULT 'default',
    content TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_memories_user ON memories(user_id);
"""


class MemoryStore:
    def __init__(self, db_path: str | Path, embedder=None, vector_dir: str | Path | None = None):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(db_path), check_same_thread=False, isolation_level=None)
        self._lock = threading.Lock()
        self._conn.executescript(SCHEMA)
        self.embedder = embedder
        self._collection = None
        if embedder is not None and vector_dir is not None:
            from agent.knowledge.store import ChromaStore

            self._collection = ChromaStore(vector_dir, collection="memories")

    # ---- 抽取 ----
    @staticmethod
    def extract(client, conversation: str) -> list[str]:
        """LLM 抽取可长期记忆的事实（用户偏好/关注方向/重要结论）。"""
        prompt = (
            "你是记忆抽取器。从对话中抽取值得长期记住的、关于用户的信息："
            "研究偏好、关注的技术/公司/领域、重要结论或决策。\n"
            "每条用一句简短中文；没有值得记的就输出 []。只输出 JSON 字符串数组，不要其他文字。\n\n"
            f"对话内容：\n{conversation[:3000]}"
        )
        try:
            resp = client.chat.completions.create(
                model=client.model_id,
                messages=[{"role": "user", "content": prompt}],
                temperature=0,
                max_tokens=200,
            )
            text = resp.choices[0].message.content.strip()
            start, end = text.find("["), text.rfind("]")
            if start == -1 or end == -1:
                return []
            items = json.loads(text[start : end + 1])
            return [str(x).strip() for x in items if str(x).strip()]
        except Exception:  # noqa: BLE001 —— 抽取失败不阻断主流程
            return []

    # ---- 存储 ----
    def add(self, content: str, user_id: str = "default") -> None:
        content = content.strip()
        if not content:
            return
        with self._lock:
            cur = self._conn.execute(
                "INSERT INTO memories (user_id, content, created_at) VALUES (?, ?, datetime('now','localtime'))",
                (user_id, content),
            )
            if self._collection is not None:
                try:
                    from agent.knowledge.embedder import FastembedEmbedder

                    emb = self.embedder.embed([content])[0]
                    self._collection.add([str(cur.lastrowid)], [content], [emb])
                except Exception:  # noqa: BLE001 —— 向量索引失败不阻塞
                    pass

    # ---- 召回 ----
    def search(self, query: str, top_k: int = 4, user_id: str = "default") -> list[str]:
        rows = self._conn.execute(
            "SELECT content FROM memories WHERE user_id = ? ORDER BY id DESC LIMIT 200",
            (user_id,),
        ).fetchall()
        all_texts = [r[0] for r in rows]
        if not all_texts:
            return []
        if self._collection is not None:
            try:
                from agent.knowledge.embedder import FastembedEmbedder

                qv = self.embedder.embed([query])[0]
                hits = self._collection.search(qv, top_k=min(top_k, len(all_texts)))
                return [all_texts[int(h.doc_id)] for h in hits if h.doc_id.isdigit()]
            except Exception:  # noqa: BLE001 —— 回退关键词
                pass
        # 关键词召回（缺省/回退）：query 与记忆的字符重叠度 + 近因
        scored = []
        q_terms = set(query.lower())
        for i, t in enumerate(all_texts):
            overlap = len(q_terms & set(t.lower()))
            if overlap > 0:
                scored.append((overlap, len(all_texts) - i, t))  # 重叠度 + 越新越好
        scored.sort(key=lambda x: (-x[0], -x[1]))
        return [t for _, _, t in scored[:top_k]]

    def list_all(self, limit: int = 50, user_id: str = "default") -> list[str]:
        rows = self._conn.execute(
            "SELECT content FROM memories WHERE user_id = ? ORDER BY id DESC LIMIT ?",
            (user_id, limit),
        ).fetchall()
        return [r[0] for r in rows]

    def clear(self, user_id: str = "default") -> int:
        with self._lock:
            cur = self._conn.execute("DELETE FROM memories WHERE user_id = ?", (user_id,))
            if self._collection is not None:
                try:
                    self._collection.reset()  # 同步清空向量索引，避免脏召回
                except Exception:  # noqa: BLE001
                    pass
        return cur.rowcount

    def close(self) -> None:
        self._conn.close()
