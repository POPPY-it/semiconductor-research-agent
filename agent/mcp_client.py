"""MCP 客户端：连接 MCP Server（stdio），把其工具统一暴露为 smolagents 的 mcp_call 调度工具。

设计：discover 阶段连一次每个 Server 列出工具构建 catalog；调用时按需启动对应 Server。
"""
from __future__ import annotations

import asyncio
import json
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from smolagents import Tool


def _connect_and_list(spec: StdioServerParameters) -> list[Any]:
    async def _run():
        async with stdio_client(spec) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return result.tools

    return asyncio.run(_run())


def _call_tool(spec: StdioServerParameters, tool_name: str, arguments: dict) -> str:
    async def _run():
        async with stdio_client(spec) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.call_tool(tool_name, arguments)
                if result.content:
                    parts = []
                    for c in result.content:
                        if hasattr(c, "text"):
                            parts.append(c.text)
                        else:
                            parts.append(str(c))
                    return "\n".join(parts)
                return str(result)

    return asyncio.run(_run())


def discover(specs: list[StdioServerParameters]) -> dict[str, dict]:
    """catalog: tool_name -> {"spec":..., "description":...}。"""
    catalog: dict[str, dict] = {}
    for spec in specs:
        try:
            tools = _connect_and_list(spec)
        except Exception as e:  # noqa: BLE001 —— 单个 Server 失败不阻塞整体
            print(f"[MCP] 连接 {spec.args[-1] if spec.args else '?'} 失败: {e}")
            continue
        for t in tools:
            catalog[t.name] = {"spec": spec, "description": t.description or ""}
    return catalog


def build_mcp_tool(specs: list[StdioServerParameters]) -> Tool:
    """构建一个 smolagents Tool：mcp_call(tool_name, arguments)。"""
    catalog = discover(specs)
    names = ", ".join(sorted(catalog)) if catalog else "（无可用 MCP 工具）"

    class MCPCallTool(Tool):
        name = "mcp_call"
        description = (
            f"调用外部 MCP 生态工具。可用工具名：{names}。"
            "tool_name 传工具名；arguments 传 JSON 字符串参数（无参数传 {}）。"
        )
        inputs = {
            "tool_name": {"type": "string", "description": f"要调用的 MCP 工具名，可选：{names}"},
            "arguments": {"type": "string", "nullable": True, "description": 'JSON 字符串参数，如 {"query": "LLM agent"}'},
        }
        output_type = "string"

        def forward(self, tool_name: str, arguments: str = "{}") -> str:
            entry = catalog.get(tool_name)
            if entry is None:
                return f"未知 MCP 工具 {tool_name}，可用：{names}"
            try:
                args = json.loads(arguments) if arguments else {}
            except json.JSONDecodeError:
                return f"arguments 必须是合法 JSON，收到：{arguments}"
            if not isinstance(args, dict):
                return "arguments 必须是 JSON 对象"
            try:
                return _call_tool(entry["spec"], tool_name, args)
            except Exception as e:  # noqa: BLE001
                return f"MCP 调用 {tool_name} 失败: {e}"

    return MCPCallTool()
