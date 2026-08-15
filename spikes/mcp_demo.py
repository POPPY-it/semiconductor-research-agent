"""MCP 集成实测：直接调用 mcp_call 调度工具 → GitHub 搜索 + 网页抓取。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mcp_servers  # noqa: E402
from agent.mcp_client import build_mcp_tool  # noqa: E402
from backend.app.core import settings  # noqa: E402


def main() -> None:
    names = [n.strip() for n in settings.MCP_SERVERS.split(",") if n.strip()]
    specs = [mcp_servers.build_spec(n) for n in names]
    tool = build_mcp_tool(specs)

    print("=== 可用 MCP 工具 ===")
    print(tool.description)

    print("\n=== GitHub 仓库搜索 ===")
    print(tool("search_github_repos", '{"query": "LLM agent framework", "limit": 3}'))

    print("\n=== 网页正文抓取 ===")
    print(tool("fetch_to_markdown", '{"url": "https://www.ithome.com/0/989/706.htm"}')[:500])


if __name__ == "__main__":
    main()
