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
    CHART_DIR: Path = ROOT / "reports" / "charts"
    APP_QUEUE: str = os.getenv("APP_QUEUE", "thread")  # thread | rq
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    # ---- 企业级配置（W8 加固）----
    # 质检交付策略：caveat=附警示横幅交付 / reject=不通过则不交付
    QA_POLICY: str = os.getenv("QA_POLICY", "caveat")
    # 单任务 token 预算（估算字符数）：超预算熔断。
    # 真实负载校准（W8 实测）：日报含 2 轮修订约消耗 110~160 万字符 → 默认 400 万留余量
    TOKEN_BUDGET_CHARS: int = int(os.getenv("TOKEN_BUDGET_CHARS", "4000000"))
    # Cookie 签名密钥（留空则从 API_TOKEN 派生，生产环境请显式配置强随机值）
    COOKIE_SECRET: str = os.getenv(
        "COOKIE_SECRET", os.getenv("API_TOKEN", "dev-insecure-secret")
    )
    AUTH_COOKIE: str = "agent_auth"
    AUTH_COOKIE_TTL: int = int(os.getenv("AUTH_COOKIE_TTL", "86400"))
    # 主/备 LLM（不设则回落到 DEEPSEEK_*）
    LLM_API_KEY: str = os.getenv("LLM_API_KEY", os.getenv("DEEPSEEK_API_KEY", ""))
    LLM_BASE_URL: str = os.getenv("LLM_BASE_URL", os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    LLM_MODEL: str = os.getenv("LLM_MODEL", os.getenv("DEEPSEEK_MODEL", "deepseek-chat"))
    FALLBACK_LLM_API_KEY: str = os.getenv("FALLBACK_LLM_API_KEY", "")
    FALLBACK_LLM_BASE_URL: str = os.getenv("FALLBACK_LLM_BASE_URL", "")
    FALLBACK_LLM_MODEL: str = os.getenv("FALLBACK_LLM_MODEL", "")
    # Semantic Scholar API Key（可选，免费申请；未设置走匿名额度，易触发限流）
    SEMANTIC_SCHOLAR_API_KEY: str = os.getenv("SEMANTIC_SCHOLAR_API_KEY", "")
    # MCP：要接入的 MCP Server 列表（逗号分隔），当前支持 github/fetch
    MCP_SERVERS: str = os.getenv("MCP_SERVERS", "github,fetch")
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

    @classmethod
    def auth_enabled(cls) -> bool:
        return bool(cls.API_TOKEN)

    @classmethod
    def fallback_llm_configured(cls) -> bool:
        return bool(cls.FALLBACK_LLM_API_KEY and cls.FALLBACK_LLM_BASE_URL and cls.FALLBACK_LLM_MODEL)


settings = Settings()
