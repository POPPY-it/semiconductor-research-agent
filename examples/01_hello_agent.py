"""
Day 1 里程碑：跑通第一个基于 smolagents 的 Agent（DeepSeek 驱动）。

后续整个项目的骨架都是从这里长出来的：
- 自定义 Tool（半导体行业数据源）→ 数据层的雏形
- CodeAgent 内核 → 研究/数据/质检 Agent 的基座
"""
import os

from dotenv import load_dotenv

load_dotenv()  # 读取项目根目录 .env

from smolagents import CodeAgent, OpenAIModel, tool

# ---- 1. LLM：DeepSeek（OpenAI 兼容协议，经 smolagents 内置 OpenAIModel 直连，零额外抽象层） ----
model = OpenAIModel(
    model_id=os.getenv("DEEPSEEK_MODEL", "deepseek-chat"),
    api_base=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
    api_key=os.environ["DEEPSEEK_API_KEY"],
)

# ---- 2. 自定义 Tool：半导体行业数据源（当前为 Mock，后续替换为真实采集管道） ----
@tool
def get_semiconductor_news(date: str) -> str:
    """查询指定日期（YYYY-MM-DD）的半导体行业新闻摘要，返回带具体数字的中文要点。

    Args:
        date: 要查询的日期，格式为 YYYY-MM-DD。
    """
    # TODO(M1): 替换为真实数据层 —— 采集管道 + 数据库
    return (
        f"{date} 半导体快讯：台积电 2nm 产能爬坡超预期，预计 2026 年量产；"
        "SEMI 上调 2025 年全球半导体设备支出预期至 1200 亿美元；"
        "存储芯片现货价连续第四周上涨，DRAM 涨幅 3.2%。"
    )


# ---- 3. CodeAgent：让模型写代码调用工具 ----
agent = CodeAgent(tools=[get_semiconductor_news], model=model, max_steps=6)

if __name__ == "__main__":
    result = agent.run(
        "今天是 2025-08-14。请用新闻工具查询今日半导体快讯，"
        "然后写一段不超过 100 字的中文行业速览，必须保留具体数字。"
    )
    print("\n===== Agent 最终输出 =====\n")
    print(result)
