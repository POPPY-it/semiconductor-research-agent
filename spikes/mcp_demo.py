"""MCP 集成实测（P1-2 版）：每个 MCP 工具是独立 Tool → GitHub 搜索 + 网页抓取。"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import mcp_servers  # noqa: E402
from agent.mcp_client import build_mcp_tools  # noqa: E402
from backend.app.core import settings  # noqa: E402


def main() -> None:
    names = [n.strip() for n in settings.MCP_SERVERS.split(",") if n.strip()]
    specs = [mcp_servers.build_spec(n) for n in names]
    tools = build_mcp_tools(specs)
    by_name = {t.name: t for t in tools}

    print("=== 独立 MCP 工具（不再用 mcp_call 调度器）===")
    for t in tools:
        print(f"- {t.name}（必填: {[k for k, v in t.inputs.items() if not v.get('nullable')]}）")

    print("\n=== GitHub 仓库搜索 ===")
    print(by_name["search_github_repos"](query="LLM agent framework", limit=3))

    print("\n=== 网页正文抓取 ===")
    print(by_name["fetch_to_markdown"](url="https://www.ithome.com/0/989/706.htm")[:500])


if __name__ == "__main__":
    main()
