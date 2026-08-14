"""数据管道单元测试：适配器接口、去重入库、采集日志（用假采集器，无网络）。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from data.collectors.base import BaseCollector, CollectError  # noqa: E402
from data.pipeline import run_collect_once  # noqa: E402
from data.storage import SQLiteStore  # noqa: E402

import data.collectors  # noqa: E402,F401 确保注册表可导入


class FakeOkCollector(BaseCollector):
    name = "fake_ok"

    def fetch(self):
        return [
            {
                "source": "fake_ok",
                "title": "测试文章 A",
                "url": "https://example.com/a",
                "published_at": "2026-08-14",
                "extra": {"k": "v"},
            }
        ]


class FakeFailCollector(BaseCollector):
    name = "fake_fail"
    retries = 1
    retry_delay = 0

    def fetch(self):
        raise RuntimeError("boom")


def test_storage_dedupe(tmp_path):
    store = SQLiteStore(tmp_path / "test.db")
    items = [
        {"source": "s", "title": "t", "url": "https://x/1", "published_at": "", "extra": {}},
        {"source": "s", "title": "t2", "url": "https://x/2", "published_at": "", "extra": {}},
    ]
    assert store.upsert_articles(items) == 2
    assert store.upsert_articles(items) == 0  # 全部去重
    assert store.count() == 2
    store.close()


def test_pipeline_once_with_fake_collectors(tmp_path, monkeypatch):
    import data.pipeline as pipeline

    monkeypatch.setattr(pipeline, "ALL_COLLECTORS", [FakeOkCollector(), FakeFailCollector()])
    results = pipeline.run_collect_once(db_path=tmp_path / "p.db")
    by_name = {r["source"]: r for r in results}
    assert by_name["fake_ok"]["status"] == "ok"
    assert by_name["fake_ok"]["new"] == 1
    assert by_name["fake_fail"]["status"] == "error"

    store = SQLiteStore(tmp_path / "p.db")
    assert store.count() == 1
    logs = store._conn.execute(
        "SELECT source, status FROM collect_log ORDER BY id"
    ).fetchall()
    assert ("fake_ok", "ok") in logs and ("fake_fail", "error") in logs
    store.close()


def test_retry_then_raise():
    collector = FakeFailCollector()
    try:
        collector.collect()
        raised = False
    except CollectError:
        raised = True
    assert raised  # retries+1 次尝试后仍失败则抛出 CollectError
