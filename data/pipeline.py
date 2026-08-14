"""数据采集管道：一次性采集 + APScheduler 每日定时。"""
from __future__ import annotations

import logging
from pathlib import Path

from .collectors import ALL_COLLECTORS
from .collectors.base import CollectError
from .storage import SQLiteStore

logger = logging.getLogger(__name__)

DEFAULT_DB = Path(__file__).resolve().parents[1] / "data" / "articles.db"


def run_collect_once(db_path: str | Path = DEFAULT_DB) -> list[dict]:
    """跑一遍全部采集器，去重入库；返回每个源的结果统计。"""
    store = SQLiteStore(db_path)
    results: list[dict] = []
    try:
        for collector in ALL_COLLECTORS:
            try:
                items = collector.collect()
                new_count = store.upsert_articles(items)
                store.log(collector.name, "ok", items=len(items))
                results.append(
                    {"source": collector.name, "status": "ok", "fetched": len(items), "new": new_count}
                )
                logger.info("[%s] fetched=%d new=%d", collector.name, len(items), new_count)
            except CollectError as e:
                store.log(collector.name, "error", message=str(e))
                results.append({"source": collector.name, "status": "error", "message": str(e)[:200]})
    finally:
        store.close()
    return results


def schedule_daily(hour: int = 8, minute: int = 0, db_path: str | Path = DEFAULT_DB) -> None:
    """每日定时采集（进程内调度，常驻运行）。"""
    from apscheduler.schedulers.blocking import BlockingScheduler
    from apscheduler.triggers.cron import CronTrigger

    scheduler = BlockingScheduler(timezone="Asia/Shanghai")
    scheduler.add_job(
        run_collect_once,
        CronTrigger(hour=hour, minute=minute),
        args=[db_path],
        id="daily_collect",
        replace_existing=True,
    )
    logger.info("定时采集已启动：每天 %02d:%02d (Asia/Shanghai)", hour, minute)
    scheduler.start()
