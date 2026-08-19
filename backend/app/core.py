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
    MEMORY_DB: Path = ROOT / "data" / "memory.db"
    TRACE_DIR: Path = ROOT / "agent" / "traces"
    APP_QUEUE: str = os.getenv("APP_QUEUE", "thread")  # thread | rq
    REDIS_URL: str = os.getenv("REDIS_URL", "redis://127.0.0.1:6379/0")

    # ---- 企业级配置（W8 加固）----
    # 质检交付策略：caveat=附警示横幅交付 / reject=不通过则不交付
    QA_POLICY: str = os.getenv("QA_POLICY", "caveat")
    # 确定性数字引用门禁（GPT 审查 §4.3 整改）：报告的数字级引用率（数字后 80 字符内
    # 是否有来源链接）低于该阈值时门禁不通过——与 LLM 质检独立叠加，不依赖提示词约束。
    # 低于阈值且 QA_POLICY=reject 时拒交；caveat 时横幅注明门禁未通过。
    MIN_NUMBER_CITATION_RATE: float = float(os.getenv("MIN_NUMBER_CITATION_RATE", "0.3"))
    # 证据包门禁（差距收敛第 1 项）：报告 URL 必须来自检索结果（URL 落地率），
    # 低于该阈值视为模型编造 URL——确定性检出，与 LLM 质检独立。
    MIN_URL_GROUNDING_RATE: float = float(os.getenv("MIN_URL_GROUNDING_RATE", "0.8"))
    # claim 支持率门禁（差距收敛第 5 项）：报告带单位数字的论断中，其数字须在检索
    # 证据中出现过（防"链接真实但内容不含该数字"）；低于阈值门禁不通过。
    MIN_CLAIM_SUPPORT_RATE: float = float(os.getenv("MIN_CLAIM_SUPPORT_RATE", "0.5"))
    # 单任务 token 预算（估算字符数）：超预算熔断。
    # 真实负载校准（W8 实测）：日报含 2 轮修订约消耗 110~160 万字符 → 默认 400 万留余量。
    # 接入实时搜索工具后（2026-08-17 实测）：研究+质检一轮约消耗 390~400 万字符
    # （搜索返回内容进入上下文累积），调至 600 万并为搜索场景保留修订余量。
    TOKEN_BUDGET_CHARS: int = int(os.getenv("TOKEN_BUDGET_CHARS", "6000000"))
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
    # 故障注入（P1-2 验收钩子）：逗号分隔的 URL 域名片段，命中即模拟外部 API 失败，
    # 用于演示「arXiv 挂掉任务仍能用知识库+SEC 出报告」。空=不注入。
    SIMULATED_API_FAILURES: str = os.getenv("SIMULATED_API_FAILURES", "")
    # MCP：要接入的 MCP Server 列表（逗号分隔），当前支持 github/fetch
    MCP_SERVERS: str = os.getenv("MCP_SERVERS", "github,fetch")
    # HTTP MCP（可选）：搜索代理网关（如 Serper/Tavily/Exa 聚合）。
    # Token 只从环境读取，**禁止提交 git**；MCP_HTTP_TOOLS 为允许挂载的工具名
    # （按后缀匹配网关工具名，如 serper_news 匹配 search_proxy_serper_news）。
    MCP_HTTP_URL: str = os.getenv("MCP_HTTP_URL", "")
    MCP_HTTP_TOKEN: str = os.getenv("MCP_HTTP_TOKEN", "")
    MCP_HTTP_TOOLS: str = os.getenv(
        "MCP_HTTP_TOOLS", "serper_news,tavily_search,serper_scholar,serper_patents"
    )
    GITHUB_TOKEN: str = os.getenv("GITHUB_TOKEN", "")

    @classmethod
    def auth_enabled(cls) -> bool:
        return bool(cls.API_TOKEN)

    @classmethod
    def fallback_llm_configured(cls) -> bool:
        return bool(cls.FALLBACK_LLM_API_KEY and cls.FALLBACK_LLM_BASE_URL and cls.FALLBACK_LLM_MODEL)


settings = Settings()
