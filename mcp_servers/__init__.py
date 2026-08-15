"""MCP Server 注册表：名称 → 启动参数（Python 子进程 + stdio）。"""
from __future__ import annotations

import os
import sys
from pathlib import Path

from mcp import StdioServerParameters

HERE = Path(__file__).resolve().parent


def build_spec(name: str) -> StdioServerParameters:
    script = {"github": "github_server.py", "fetch": "fetch_server.py"}.get(name)
    if script is None:
        raise ValueError(f"未知 MCP Server: {name}")
    env = os.environ.copy()
    return StdioServerParameters(
        command=sys.executable,
        args=[str(HERE / script)],
        env=env,
    )


DEFAULT_SERVERS = ["github", "fetch"]
