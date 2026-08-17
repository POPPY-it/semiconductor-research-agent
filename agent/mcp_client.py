"""MCP 客户端（P1-2 治理版）：把每个 MCP 工具映射成**独立** smolagents Tool。

旧设计是单个 `mcp_call(tool_name, json)` 调度器——模型要先背工具名再拼 JSON，
参数校验也在模型侧。现在：

- discover 阶段连一次每个 Server 列出工具，收集 name / description / inputSchema；
- 每个 MCP 工具生成一个独立 Tool（名字、描述、inputs 直接来自 inputSchema，
  必填字段标 required，其余 nullable）；
- forward 内统一异常兜底 → 返回给模型的降级文案，不抛到编排器外面。

说明（如实口径）：调用时仍按需拉起 stdio 子进程（演示规模够用；
生产级长驻连接需要异步常驻会话池，本仓库未做）。
"""
from __future__ import annotations

import asyncio
import re
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


def _server_name(spec: StdioServerParameters) -> str:
    """从启动脚本名推断 server 名（github_server.py → github）。"""
    for arg in (spec.args or []):
        m = re.search(r"([A-Za-z0-9_]+?)(?:_server)?\.py$", arg)
        if m:
            return m.group(1)
    return "mcp"


def discover(specs: list[StdioServerParameters]) -> dict[str, dict]:
    """catalog: tool_name -> {"spec", "description", "inputSchema", "server"}。

    不同 Server 的工具重名时，后注册的用 {server}__{name} 避免冲突。
    """
    catalog: dict[str, dict] = {}
    for spec in specs:
        server = _server_name(spec)
        try:
            tools = _connect_and_list(spec)
        except Exception as e:  # noqa: BLE001 —— 单个 Server 失败不阻塞整体
            print(f"[MCP] 连接 {server} 失败: {e}")
            continue
        for t in tools:
            key = t.name
            if key in catalog:
                key = f"{server}__{t.name}"
            catalog[key] = {
                "spec": spec,
                "description": t.description or "",
                "inputSchema": getattr(t, "inputSchema", None) or {},
                "server": server,
            }
    return catalog


def _mcp_tool(name: str, entry: dict) -> Tool:
    """单个 MCP 工具 → 独立 smolagents Tool（schema 从 MCP inputSchema 映射）。"""
    schema = entry.get("inputSchema") or {}
    required = set((schema.get("required") or []) if isinstance(schema, dict) else [])
    props = (schema.get("properties") or {}) if isinstance(schema, dict) else {}
    # MCP inputSchema 类型 → smolagents 允许的类型（其余一律落为 string，避免构造失败）
    _ALLOWED = {"string", "integer", "number", "boolean", "array", "object", "null"}
    tool_inputs: dict[str, dict] = {}
    for pname, p in props.items():
        ptype = p.get("type", "string")
        if not isinstance(ptype, str) or ptype not in _ALLOWED:
            ptype = "string"
        tool_inputs[pname] = {
            "type": ptype,
            "description": p.get("description", ""),
            "nullable": pname not in required,
        }
    server = entry.get("server", "mcp")
    # 注意：类体里不能 `name = name`（类体不查外层函数作用域），故用 tool_* 别名
    tool_name = name
    tool_desc = (
        f"{entry.get('description') or f'MCP 工具 {tool_name}'}（来自 MCP Server：{server}。"
        "调用失败时返回降级说明，可改用 search_knowledge / query_filings 兜底）"
    )

    class MCPTool(Tool):
        name = tool_name
        description = tool_desc
        inputs = tool_inputs
        output_type = "string"
        # MCP 参数动态生成，forward 用 **kwargs 兜底 → 跳过签名强校验
        skip_forward_signature_validation = True

        def forward(self, **kwargs: Any) -> str:
            # 只取 schema 内声明的参数，避免模型传多余字段
            args = {k: v for k, v in kwargs.items() if k in props and v is not None}
            try:
                return _call_tool(entry["spec"], tool_name, args)
            except Exception as e:  # noqa: BLE001
                return (
                    f"MCP 工具 {tool_name} 调用失败：{type(e).__name__}: {e}。"
                    "可改用 search_knowledge / query_filings 获取已入库资料"
                )

    cls_name = "MCPTool_" + re.sub(r"\W", "_", tool_name)
    MCPTool.__name__ = cls_name
    return MCPTool()


def build_mcp_tools(specs: list[StdioServerParameters]) -> list[Tool]:
    """每个 MCP 工具 → 一个独立 smolagents Tool（不再用 mcp_call 调度器）。"""
    catalog = discover(specs)
    return [_mcp_tool(name, entry) for name, entry in catalog.items()]
