"""服务层配置：从环境/.env 读取。"""
from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")


class Settings:
    API_TOKEN: str = os.getenv("API_TOKEN", "")
    DB_PATH: Path = Path(os.getenv("APP_DB_PATH", str(ROOT / "data" / "app.db")))
    ARTICLES_DB: Path = ROOT / "data" / "articles.db"
    VECTOR_DIR: Path = ROOT / "data" / "vectorstore" / "main"
    MODEL_DIR: Path = ROOT / "data" / "models"
    REPORT_DIR: Path = ROOT / "reports" / "output"
    APP_QUEUE: str = os.getenv("APP_QUEUE", "thread")  # thread | rq
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    @classmethod
    def auth_enabled(cls) -> bool:
        return bool(cls.API_TOKEN)


settings = Settings()
