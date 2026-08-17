"""MCP Server：网页正文抓取（trafilatura 提取，转纯文本/Markdown）。"""
from fastmcp import FastMCP

import requests

mcp = FastMCP("fetch")


@mcp.tool()
def fetch_to_markdown(url: str) -> str:
    """抓取网页正文并转纯文本（用于检索网页内容）。

    Args:
        url: 目标网页地址。
    """
    import trafilatura

    # SEC 强制要求描述性 User-Agent（浏览器 UA 会被 403）
    ua = (
        "SemiconductorResearchAgent/0.1 (campus recruiting project; contact: research@example.com)"
        if "sec.gov" in url
        else (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/151.0.0.0 Safari/537.36"
        )
    )
    resp = requests.get(url, headers={"User-Agent": ua}, timeout=20, allow_redirects=True)
    resp.raise_for_status()
    text = trafilatura.extract(resp.content, include_comments=False, include_tables=True)
    return (text or "（无法提取正文）")[:4000]


if __name__ == "__main__":
    mcp.run()
