"""服务层预研版（W2）：FastAPI + SSE 流式执行 Agent。

验证目标：`agent.run(stream=True)` 生成器 → sse-starlette → 前端逐步收到执行过程。
W5 将在此基础上加：任务队列、会话管理、鉴权、历史存储。
"""
import json
import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from pydantic import BaseModel
from sse_starlette.sse import EventSourceResponse

ROOT = Path(__file__).resolve().parents[2]
load_dotenv(ROOT / ".env")

from smolagents import CodeAgent, OpenAIModel, tool  # noqa: E402

app = FastAPI(title="Semiconductor Research Agent API")


@tool
def get_semiconductor_news(date: str) -> str:
    """查询指定日期（YYYY-MM-DD）的半导体行业新闻摘要，返回带具体数字的中文要点。

    Args:
        date: 要查询的日期，格式为 YYYY-MM-DD。
    """
    return (
        f"{date} 半导体快讯：台积电 2nm 产能爬坡超预期，预计 2026 年量产；"
        "SEMI 上调 2025 年全球半导体设备支出预期至 1200 亿美元。"
    )


_model = OpenAIModel(
    model_id=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    api_base=os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    api_key=os.environ["DEEPSEEK_API_KEY"],
)


def get_agent() -> CodeAgent:
    return CodeAgent(tools=[get_semiconductor_news], model=_model, max_steps=8)


class TaskRequest(BaseModel):
    task: str


def _clean(value, limit: int = 2000) -> str | None:
    if value is None:
        return None
    if hasattr(value, "content"):
        value = value.content
    return str(value)[:limit]


def serialize_step(step) -> dict:
    """把 smolagents run(stream=True) 产出的各类步骤对象转为可 JSON 化的字典。"""
    data: dict = {"kind": type(step).__name__}
    for attr in ("step_number", "output", "model_output", "action_output", "error"):
        if hasattr(step, attr):
            val = _clean(getattr(step, attr))
            if val:
                data[attr] = val
    return data


@app.post("/api/agent/stream")
async def agent_stream(req: TaskRequest):
    agent = get_agent()

    def gen():
        yield {"event": "task", "data": json.dumps({"task": req.task}, ensure_ascii=False)}
        for step in agent.run(req.task, stream=True):
            yield {"event": "step", "data": json.dumps(serialize_step(step), ensure_ascii=False)}
        yield {"event": "done", "data": "{}"}

    return EventSourceResponse(gen())


@app.get("/api/health")
async def health():
    return {"status": "ok"}
