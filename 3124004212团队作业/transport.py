"""两种工具通道：本地直连用于零依赖演示，MCP 用于正式智能体。"""
from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from datetime import timedelta
from pathlib import Path

from .tools import TOOL_NAMES, TaskTools, local_schemas


class LocalTransport:
    def __init__(self, data_dir):
        self.tools = TaskTools(data_dir)
        self.schemas = local_schemas()

    async def call(self, name: str, arguments: dict) -> dict:
        if name not in TOOL_NAMES:
            return {"ok": False, "error": "不存在的工具"}
        if not isinstance(arguments, dict):
            return {"ok": False, "error": "工具参数必须是 JSON 对象"}
        try:
            return getattr(self.tools, name)(**arguments)
        except (TypeError, ValueError) as exc:
            return {"ok": False, "error": str(exc)}


class MCPTransport:
    def __init__(self, session, schemas):
        self.session = session
        self.schemas = schemas

    async def call(self, name: str, arguments: dict) -> dict:
        if name not in TOOL_NAMES:
            return {"ok": False, "error": "不存在的工具"}
        if not isinstance(arguments, dict):
            return {"ok": False, "error": "工具参数必须是 JSON 对象"}
        result = await self.session.call_tool(name, arguments=arguments)
        text = "\n".join(block.text for block in result.content if getattr(block, "type", "") == "text")
        if result.isError:
            return {"ok": False, "error": text or "MCP 工具执行失败"}
        structured = getattr(result, "structuredContent", None)
        if isinstance(structured, dict):
            return structured
        try:
            value = json.loads(text)
            if isinstance(value, dict):
                return value
        except ValueError:
            pass
        return {"ok": False, "error": "工具返回了无法识别的结果"}


@asynccontextmanager
async def open_transport(kind: str, data_dir: Path):
    if kind == "local":
        yield LocalTransport(data_dir)
        return
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError:
        raise RuntimeError("缺少 MCP 依赖，请运行 python -m pip install -r requirements.txt") from None
    server = Path(__file__).resolve().parents[1] / "mcp_server.py"
    # 只向工具子进程传递运行必需的环境，API Key 留在 Agent 进程中。
    env = {key: os.environ[key] for key in
           ("PATH", "SYSTEMROOT", "WINDIR", "TEMP", "TMP", "PYTHONPATH", "TZ", "LANG", "LC_ALL") if key in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    params = StdioServerParameters(command=sys.executable,
                                  args=[str(server), "--data-dir", str(data_dir)], env=env)
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write, read_timeout_seconds=timedelta(seconds=30)) as session:
            await session.initialize()
            result = await session.list_tools()
            schemas = [{"type": "function", "function": {"name": tool.name,
                        "description": tool.description or "", "parameters": tool.inputSchema}}
                       for tool in result.tools if tool.name in TOOL_NAMES]
            if {item["function"]["name"] for item in schemas} != set(TOOL_NAMES):
                raise RuntimeError("MCP 服务端的工具列表不完整")
            yield MCPTransport(session, schemas)
