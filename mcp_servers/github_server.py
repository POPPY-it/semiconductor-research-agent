"""MCP Server：GitHub 开源仓库搜索（官方 REST API，匿名 10 次/分钟）。"""
from fastmcp import FastMCP

import requests

mcp = FastMCP("github")


@mcp.tool()
def search_github_repos(query: str, limit: int = 5) -> str:
    """搜索 GitHub 开源仓库（按 star 排序），返回名称/star/语言/简介/链接。

    Args:
        query: 搜索关键词，如 "LLM agent" 或 "RAG"。
        limit: 返回条数，默认 5。
    """
    resp = requests.get(
        "https://api.github.com/search/repositories",
        params={"q": query, "sort": "stars", "per_page": limit},
        headers={"Accept": "application/vnd.github+json"},
        timeout=20,
    )
    resp.raise_for_status()
    items = resp.json().get("items", [])
    lines = []
    for it in items:
        lines.append(
            f"- {it['full_name']} ⭐{it['stargazers_count']} | {it.get('language')} | "
            f"{(it.get('description') or '')[:120]}\n  {it['html_url']}"
        )
    return "\n".join(lines) or "（无结果）"


if __name__ == "__main__":
    mcp.run()
