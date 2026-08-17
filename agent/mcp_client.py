"""MCP 客户端（P1-2 治理版）：把每个 MCP 工具映射成**独立** smolagents Tool。

支持两种传输：
- stdio：本地子进程（github / fetch，`build_mcp_tools`）；
- http：Streamable HTTP 端点（如搜索代理网关，`build_mcp_http_tools`）。

旧设计是单个 `mcp_call(tool_name, json)` 调度器——模型要先背工具名再拼 JSON，
参数校验也在模型侧。现在：

- discover 阶段连一次每个 Server 列出工具，收集 name / description / inputSchema；
- 每个 MCP 工具生成一个独立 Tool（名字、描述、inputs 直接来自 inputSchema，
  必填字段标 required，其余 nullable）；
- forward 内统一异常兜底 → 返回给模型的降级文案，不抛到编排器外面；
- HTTP 调用带总超时（asyncio.wait_for），网关无容量/超时返回降级文案。

说明（如实口径）：调用时仍按需建立连接（stdio 子进程 / http 会话），演示规模够用；
生产级长驻连接需要异步常驻会话池，本仓库未做。
"""
from __future__ import annotations

import asyncio
import re
from typing import Any

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamablehttp_client
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


# ---------------------------------------------------------------- HTTP 传输

def _http_connect_and_list(url: str, headers: dict | None) -> list[Any]:
    async def _run():
        async with streamablehttp_client(url, headers=headers) as streams:
            read, write, _ = streams
            async with ClientSession(read, write) as session:
                await session.initialize()
                result = await session.list_tools()
                return result.tools

    return asyncio.run(_run())


def _http_call_tool(url: str, headers: dict | None, tool_name: str, arguments: dict, timeout: float = 45.0) -> str:
    """HTTP 调用带总超时：网关无容量（503）/超时 → 抛异常由 forward 降级。"""

    async def _run():
        async with streamablehttp_client(url, headers=headers) as streams:
            read, write, _ = streams
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

    return asyncio.run(asyncio.wait_for(_run(), timeout=timeout))


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
    """单个 MCP 工具 → 独立 smolagents Tool（schema 从 MCP inputSchema 映射）。

    entry 支持两种传输：
    - {"transport": "stdio", "spec": StdioServerParameters, ...}
    - {"transport": "http", "url": str, "headers": dict, ...}
    """
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
    transport = entry.get("transport", "stdio")
    # 工具输出治理：实时搜索（HTTP 网关）返回全文很长，会快速烧光 token 预算——
    # 统一截断到 MAX_OUTPUT_CHARS，并在尾部标注截断信息（面试口径：工具输出也是治理对象）。
    max_out = int(entry.get("max_output_chars", 2500))

    # 注意：类体里不能 `name = name`（类体不查外层函数作用域），故用 tool_* 别名
    tool_name = name
    tool_desc = (
        f"{entry.get('description') or f'MCP 工具 {tool_name}'}（来自 MCP Server：{server}，"
        f"{transport} 传输。调用失败时返回降级说明，可改用 search_knowledge / query_filings 兜底）"
    )

    def _invoke(args: dict) -> str:
        if transport == "http":
            result = _http_call_tool(entry["url"], entry.get("headers"), tool_name, args)
        else:
            result = _call_tool(entry["spec"], tool_name, args)
        if len(result) > max_out:
            return result[:max_out] + f"\n…[已截断：原始 {len(result)} 字符，仅保留前 {max_out}]"
        return result

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
                return _invoke(args)
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


# ---------------------------------------------------------------- HTTP MCP（搜索网关）

def discover_http(url: str, headers: dict | None = None) -> dict[str, dict]:
    """HTTP MCP 端点 catalog：tool_name -> {"transport": "http", "url", "headers", ...}。"""
    try:
        tools = _http_connect_and_list(url, headers)
    except Exception as e:  # noqa: BLE001 —— 端点失败不阻塞整体
        print(f"[MCP] 连接 HTTP 端点 {url} 失败: {e}")
        return {}
    catalog: dict[str, dict] = {}
    for t in tools:
        catalog[t.name] = {
            "transport": "http",
            "url": url,
            "headers": headers,
            "description": t.description or "",
            "inputSchema": getattr(t, "inputSchema", None) or {},
            "server": url.split("//")[-1].split("/")[0],
        }
    return catalog


def build_mcp_http_tools(
    url: str, headers: dict | None = None, allow: list[str] | None = None
) -> list[Tool]:
    """HTTP MCP 端点的工具 → 独立 Tool 列表。

    allow：只保留工具名**以给定后缀结尾**的工具（网关工具名形如
    `search_proxy_serper_news`，传 "serper_news" 即匹配），避免一次挂 24 个
    工具加重模型选择负担。None = 全部挂载。
    """
    catalog = discover_http(url, headers)
    if allow:
        allow = [a for a in allow if a]
        if allow:
            catalog = {
                k: v for k, v in catalog.items() if any(k.endswith("_" + a) or k == a for a in allow)
            }
    return [_mcp_tool(name, entry) for name, entry in catalog.items()]
