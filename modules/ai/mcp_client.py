"""MCP 客户端 — 连接外部 MCP 服务（HTTP JSON-RPC）。"""
from __future__ import annotations

import json
import urllib.error
import urllib.request
from typing import Any

from modules.ai.registry import get_extension, list_extensions


def list_mcp_servers() -> list[dict]:
    return list_extensions('mcp')


def _mcp_request(server_cfg: dict, method: str, params: dict | None = None) -> Any:
    url = server_cfg.get('url', '').strip()
    if not url:
        raise RuntimeError(f'MCP {server_cfg.get("id")} 未配置 url')

    body = json.dumps({
        'jsonrpc': '2.0',
        'id': 1,
        'method': method,
        'params': params or {},
    }).encode('utf-8')

    headers = {'Content-Type': 'application/json'}
    for k, v in (server_cfg.get('headers') or {}).items():
        headers[k] = v

    req = urllib.request.Request(url, data=body, headers=headers)
    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        if 'error' in data:
            raise RuntimeError(data['error'].get('message', str(data['error'])))
        return data.get('result')
    except urllib.error.HTTPError as e:
        raise RuntimeError(e.read().decode('utf-8') if e.fp else str(e)) from e


def discover_tools(mcp_id: str) -> list[dict]:
    """从 MCP 服务发现工具列表。"""
    cfg = get_extension('mcp', mcp_id)
    if not cfg:
        return []
    if cfg.get('tools'):
        return cfg['tools']
    try:
        result = _mcp_request(cfg, 'tools/list')
        return result.get('tools', []) if isinstance(result, dict) else []
    except Exception:
        return cfg.get('tools', [])


def call_mcp_tool(mcp_id: str, tool_name: str, args: dict) -> Any:
    cfg = get_extension('mcp', mcp_id)
    if not cfg:
        raise ValueError(f'MCP 服务不存在: {mcp_id}')
    result = _mcp_request(cfg, 'tools/call', {
        'name': tool_name,
        'arguments': args,
    })
    if isinstance(result, dict) and 'content' in result:
        parts = result['content']
        if parts and isinstance(parts[0], dict):
            return parts[0].get('text', result)
    return result
