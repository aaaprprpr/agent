from __future__ import annotations

import asyncio
import os
from pathlib import Path
from typing import Any


PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CONFIG_PATH = PROJECT_ROOT / "configs" / "mcp.yaml"
MAX_TOP_K = 10


def _load_yaml(path: Path) -> dict:
    try:
        import yaml
    except ImportError as exc:
        raise RuntimeError("PyYAML is required to load MCP configuration") from exc
    if not path.is_file():
        raise FileNotFoundError(f"MCP config file not found: {path}")
    with path.open("r", encoding="utf-8") as handle:
        payload = yaml.safe_load(handle)
    if not isinstance(payload, dict):
        raise ValueError("configs/mcp.yaml must contain an object")
    return payload


def _resolve_env(raw_env: Any) -> dict[str, str]:
    if raw_env is None:
        return {}
    if not isinstance(raw_env, dict):
        raise ValueError("MCP server env must be an object")
    result: dict[str, str] = {}
    for key, value in raw_env.items():
        if not isinstance(key, str):
            continue
        if value is None:
            continue
        text = str(value)
        if text.startswith("${") and text.endswith("}"):
            variable_name = text[2:-1]
            if not variable_name:
                continue
            resolved = os.environ.get(variable_name)
            if resolved is None:
                raise ValueError(f"environment variable is required for MCP server: {variable_name}")
            result[key] = resolved
        else:
            result[key] = text
    return result


def _server_config(config: dict) -> dict:
    mcp_config = config.get("mcp")
    if not isinstance(mcp_config, dict):
        raise ValueError("configs/mcp.yaml must define an mcp object")
    servers = mcp_config.get("servers")
    default_server = mcp_config.get("default_server")
    if not isinstance(servers, dict) or not isinstance(default_server, str):
        raise ValueError("configs/mcp.yaml must define mcp.default_server and mcp.servers")
    server = servers.get(default_server)
    if not isinstance(server, dict):
        raise ValueError(f"MCP default server does not exist: {default_server}")
    if not bool(server.get("enabled", False)):
        raise RuntimeError(
            "MCP web search is not configured. Enable configs/mcp.yaml:mcp.servers."
            f"{default_server}.enabled and provide a working MCP search server."
        )
    return server


def _tool_name(server: dict, tools_response: Any) -> str:
    configured = server.get("search_tool")
    if isinstance(configured, str) and configured.strip():
        return configured.strip()
    tools = getattr(tools_response, "tools", [])
    for tool in tools:
        name = getattr(tool, "name", "")
        if isinstance(name, str) and "search" in name.lower():
            return name
    raise ValueError("MCP server did not expose a configured or discoverable search tool")


def _tool_arguments(server: dict, query: str, top_k: int) -> dict:
    query_arg = server.get("query_arg", "query")
    top_k_arg = server.get("top_k_arg", "count")
    if not isinstance(query_arg, str) or not query_arg:
        raise ValueError("MCP query_arg must be a non-empty string")
    static_args = server.get("static_args", {})
    arguments: dict[str, Any] = {}
    if static_args is not None:
        if not isinstance(static_args, dict):
            raise ValueError("MCP static_args must be an object")
        arguments.update(static_args)
    arguments[query_arg] = query
    if isinstance(top_k_arg, str) and top_k_arg:
        arguments[top_k_arg] = top_k
    return arguments


def _content_block_to_dict(block: Any) -> dict:
    block_type = getattr(block, "type", type(block).__name__)
    item = {"type": block_type}
    text = getattr(block, "text", None)
    if isinstance(text, str):
        item["text"] = text
    mime_type = getattr(block, "mimeType", None) or getattr(block, "mime_type", None)
    if isinstance(mime_type, str):
        item["mime_type"] = mime_type
    data = getattr(block, "data", None)
    if isinstance(data, str):
        item["data"] = data
    return item


def _serialize_tool_result(result: Any) -> dict:
    structured = getattr(result, "structuredContent", None)
    if structured is None:
        structured = getattr(result, "structured_content", None)
    content = [_content_block_to_dict(item) for item in getattr(result, "content", [])]
    text_blocks = [item["text"] for item in content if isinstance(item.get("text"), str)]
    return {
        "is_error": bool(getattr(result, "isError", False) or getattr(result, "is_error", False)),
        "structured_content": structured,
        "content": content,
        "text": "\n".join(text_blocks).strip(),
    }


async def _call_stdio(server: dict, tool_name: str | None, arguments: dict) -> dict:
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise RuntimeError('Install MCP SDK first: pip install "mcp>=1.27,<2"') from exc
    command = server.get("command")
    if not isinstance(command, str) or not command.strip():
        raise ValueError("stdio MCP server requires command")
    args = server.get("args", [])
    if not isinstance(args, list) or not all(isinstance(item, str) for item in args):
        raise ValueError("stdio MCP server args must be a list of strings")
    env = {**os.environ, **_resolve_env(server.get("env"))}
    params = StdioServerParameters(command=command, args=args, env=env)
    async with stdio_client(params) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools_response = await session.list_tools()
            selected_tool = tool_name or _tool_name(server, tools_response)
            result = await session.call_tool(selected_tool, arguments=arguments)
    return {"tool_name": selected_tool, "result": _serialize_tool_result(result)}


async def _call_streamable_http(server: dict, tool_name: str | None, arguments: dict) -> dict:
    try:
        from mcp import ClientSession
        from mcp.client.streamable_http import streamable_http_client
    except ImportError as exc:
        raise RuntimeError('Install MCP SDK first: pip install "mcp>=1.27,<2"') from exc
    url = server.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("streamable_http MCP server requires url")
    async with streamable_http_client(url) as (read_stream, write_stream, _):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools_response = await session.list_tools()
            selected_tool = tool_name or _tool_name(server, tools_response)
            result = await session.call_tool(selected_tool, arguments=arguments)
    return {"tool_name": selected_tool, "result": _serialize_tool_result(result)}


async def _call_sse(server: dict, tool_name: str | None, arguments: dict) -> dict:
    try:
        from mcp import ClientSession
        from mcp.client.sse import sse_client
    except ImportError as exc:
        raise RuntimeError('Install MCP SDK first: pip install "mcp>=1.27,<2"') from exc
    url = server.get("url")
    if not isinstance(url, str) or not url.strip():
        raise ValueError("sse MCP server requires url")
    async with sse_client(url) as (read_stream, write_stream):
        async with ClientSession(read_stream, write_stream) as session:
            await session.initialize()
            tools_response = await session.list_tools()
            selected_tool = tool_name or _tool_name(server, tools_response)
            result = await session.call_tool(selected_tool, arguments=arguments)
    return {"tool_name": selected_tool, "result": _serialize_tool_result(result)}


async def _call_mcp(server: dict, arguments: dict) -> dict:
    tool_name = server.get("search_tool")
    if isinstance(tool_name, str):
        tool_name = tool_name.strip() or None
    else:
        tool_name = None
    transport = server.get("transport", "stdio")
    if transport == "stdio":
        return await _call_stdio(server, tool_name, arguments)
    if transport in {"streamable_http", "http"}:
        return await _call_streamable_http(server, tool_name, arguments)
    if transport == "sse":
        return await _call_sse(server, tool_name, arguments)
    raise ValueError("MCP transport must be stdio, streamable_http, or sse")


def mcp_web_search(query: str, top_k: int = 5) -> dict:
    if not isinstance(query, str) or not query.strip():
        raise ValueError("query must be a non-empty string")
    if not isinstance(top_k, int) or isinstance(top_k, bool) or top_k <= 0:
        raise ValueError("top_k must be a positive integer")
    if top_k > MAX_TOP_K:
        raise ValueError(f"top_k must not exceed {MAX_TOP_K}")
    config = _load_yaml(DEFAULT_CONFIG_PATH)
    server = _server_config(config)
    arguments = _tool_arguments(server, query.strip(), top_k)
    response = asyncio.run(_call_mcp(server, arguments))
    return {
        "query": query.strip(),
        "top_k": top_k,
        "mcp_tool_name": response["tool_name"],
        "mcp_arguments": arguments,
        **response["result"],
    }
