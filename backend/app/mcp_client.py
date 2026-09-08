"""Arena MCP client — Anthropic's open Model Context Protocol.

Optional dep: pip install mcp
Servers are configured in config.yaml -> mcp_servers: [{id, command, args, env}]
"""

from __future__ import annotations

import asyncio
from typing import Any

from . import config as config_mod


class McpError(Exception):
    """User-friendly MCP failure (safe to show in UI)."""


def is_available() -> bool:
    try:
        import mcp  # noqa: F401
        return True
    except ImportError:
        return False


def _servers() -> list[dict[str, Any]]:
    return config_mod.get_config().mcp_servers or []


def _find(server_id: str) -> dict[str, Any]:
    for s in _servers():
        if str(s.get("id")) == server_id:
            return s
    raise McpError(f"Unknown MCP server '{server_id}'. Add it under mcp_servers in config.yaml.")


async def _with_session(server: dict[str, Any], fn, timeout: int):
    from mcp import ClientSession, StdioServerParameters
    from mcp.client.stdio import stdio_client

    params = StdioServerParameters(
        command=str(server.get("command", "")),
        args=[str(a) for a in (server.get("args") or [])],
        env={str(k): str(v) for k, v in (server.get("env") or {}).items()},
    )
    async with stdio_client(params) as (read, write):
        async with ClientSession(read, write) as session:
            await asyncio.wait_for(session.initialize(), timeout)
            return await asyncio.wait_for(fn(session), timeout)


async def list_server_tools(server_id: str, timeout: int = 20) -> list[str]:
    if not is_available():
        raise McpError("MCP package not installed. Run: pip install mcp")
    server = _find(server_id)

    async def _go(session):
        tools = await session.list_tools()
        return [t.name for t in (tools.tools or [])]

    try:
        return await _with_session(server, _go, timeout)
    except FileNotFoundError:
        raise McpError(f"MCP server command not found: {server.get('command')}") from None
    except McpError:
        raise
    except Exception as exc:  # noqa: BLE001 — server failure → friendly error
        raise McpError(f"MCP '{server_id}' failed: {str(exc)[:300]}") from exc


async def call_tool(server_id: str, tool: str, args: dict[str, Any] | None,
                    timeout: int = 30) -> str:
    if not is_available():
        raise McpError("MCP package not installed. Run: pip install mcp")
    server = _find(server_id)

    async def _go(session):
        res = await session.call_tool(tool, dict(args or {}))
        texts = []
        for block in (res.content or []):
            if getattr(block, "type", "") == "text":
                texts.append(getattr(block, "text", ""))
            else:
                texts.append(str(block))
        return "\n".join(texts)[:8000] or "(no output)"

    try:
        return await _with_session(server, _go, timeout)
    except FileNotFoundError:
        raise McpError(f"MCP server command not found: {server.get('command')}") from None
    except McpError:
        raise
    except Exception as exc:  # noqa: BLE001 — server failure → friendly error
        raise McpError(f"MCP '{server_id}' failed: {str(exc)[:300]}") from exc


async def status() -> dict[str, Any]:
    if not is_available():
        return {"installed": False, "servers": [], "hint": "pip install mcp"}
    out = []
    for s in _servers():
        sid = str(s.get("id"))
        try:
            tools = await list_server_tools(sid, timeout=15)
            out.append({"id": sid, "ok": True, "tools": tools})
        except McpError as exc:
            out.append({"id": sid, "ok": False, "error": str(exc)[:200]})
    return {"installed": True, "servers": out}
