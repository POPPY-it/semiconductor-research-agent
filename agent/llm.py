"""LLM 治理：token 预算熔断 + 主备模型工厂。"""
from __future__ import annotations

from backend.app.core import settings  # core 内部已 load_dotenv

from smolagents import OpenAIModel


class BudgetExceededError(RuntimeError):
    """单任务 token 预算超限（熔断）。"""


class BudgetedModel:
    """包装 Model：累计估算输入字符数，超预算抛 BudgetExceededError。

    估算口径：字符数 / 3 ≈ token（中文约 0.6~1 token/字，取保守值）。
    """

    def __init__(self, model, budget_chars: int):
        self._model = model
        self.budget_chars = budget_chars
        self.used_chars = 0
        self.model_id = getattr(model, "model_id", "unknown")

    @property
    def used_ratio(self) -> float:
        return self.used_chars / self.budget_chars

    @staticmethod
    def _msg_chars(m) -> int:
        if isinstance(m, dict):
            return len(str(m.get("content", "")))
        return len(str(getattr(m, "content", "") or ""))

    def _check(self, messages) -> None:
        est = (
            sum(self._msg_chars(m) for m in messages)
            if isinstance(messages, (list, tuple))
            else 0
        )
        if self.used_chars + est > self.budget_chars:
            raise BudgetExceededError(
                f"token 预算超限：已用 {self.used_chars}/{self.budget_chars} 估算字符"
            )
        self.used_chars += est

    def generate(self, messages, **kwargs):
        self._check(messages)
        result = self._model.generate(messages, **kwargs)
        content = getattr(result, "content", None)
        if isinstance(content, str):
            self.used_chars += len(content)
        return result

    def __getattr__(self, name):
        return getattr(self._model, name)


def build_model() -> OpenAIModel:
    return OpenAIModel(
        model_id=settings.LLM_MODEL,
        api_base=settings.LLM_BASE_URL,
        api_key=settings.LLM_API_KEY,
    )


def build_budgeted_model() -> BudgetedModel:
    return BudgetedModel(build_model(), budget_chars=settings.TOKEN_BUDGET_CHARS)


def build_fallback_model() -> OpenAIModel | None:
    if not settings.fallback_llm_configured():
        return None
    return OpenAIModel(
        model_id=settings.FALLBACK_LLM_MODEL,
        api_base=settings.FALLBACK_LLM_BASE_URL,
        api_key=settings.FALLBACK_LLM_API_KEY,
    )


def is_connection_error(exc: Exception) -> bool:
    """异常链中是否含连接/超时类错误（用于触发备用模型）。"""
    cur: BaseException | None = exc
    while cur is not None:
        name = type(cur).__name__
        if any(k in name for k in ("Connect", "Timeout", "APITimeout", "RateLimit")):
            return True
        cur = cur.__cause__ or cur.__context__
    return False
