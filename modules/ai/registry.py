"""扩展注册中心 — 扫描 extensions/ 下的 Skill、MCP、小程序、工作流、Agent。"""
from __future__ import annotations

import importlib.util
import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable

_BASE = Path(__file__).resolve().parent.parent.parent
EXT_ROOT = _BASE / 'extensions'

_cache: dict[str, list[dict]] = {}
_handlers: dict[str, Callable] = {}


def _read_json(path: Path) -> dict | None:
    try:
        with open(path, encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return None


def _load_handler(handler_path: str) -> Callable | None:
    if handler_path in _handlers:
        return _handlers[handler_path]
    if ':' not in handler_path:
        return None
    rel, func_name = handler_path.rsplit(':', 1)
    file_path = EXT_ROOT / rel.replace('/', os_sep := '/')
    if not file_path.exists():
        file_path = _BASE / rel
    if not file_path.exists():
        return None
    spec = importlib.util.spec_from_file_location(f'ext_{file_path.stem}', file_path)
    if not spec or not spec.loader:
        return None
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    fn = getattr(mod, func_name, None)
    if callable(fn):
        _handlers[handler_path] = fn
    return fn


def reload_extensions() -> dict[str, int]:
    """重新扫描 extensions 目录。"""
    global _cache, _handlers
    _cache = {}
    _handlers.clear()

    counts = {'skill': 0, 'mcp': 0, 'miniprogram': 0, 'workflow': 0, 'agent': 0}

    if not EXT_ROOT.exists():
        EXT_ROOT.mkdir(parents=True, exist_ok=True)
        return counts

    for sub, ext_type in [
        ('skills', 'skill'),
        ('mcp', 'mcp'),
        ('miniprograms', 'miniprogram'),
        ('workflows', 'workflow'),
        ('agents', 'agent'),
    ]:
        folder = EXT_ROOT / sub
        if not folder.exists():
            continue
        items = []
        for path in sorted(folder.rglob('*.json')):
            data = _read_json(path)
            if not data:
                continue
            data.setdefault('type', ext_type)
            data['_path'] = str(path.relative_to(_BASE))
            data['_dir'] = str(path.parent.relative_to(_BASE))
            items.append(data)
            counts[ext_type] += 1
        _cache[ext_type] = items

    # YAML 工作流
    wf_folder = EXT_ROOT / 'workflows'
    if wf_folder.exists():
        import yaml
        for path in sorted(wf_folder.glob('*.yaml')) + sorted(wf_folder.glob('*.yml')):
            try:
                with open(path, encoding='utf-8') as f:
                    data = yaml.safe_load(f) or {}
                data.setdefault('type', 'workflow')
                data['_path'] = str(path.relative_to(_BASE))
                _cache.setdefault('workflow', []).append(data)
                counts['workflow'] += 1
            except Exception:
                pass

    return counts


def list_extensions(ext_type: str | None = None) -> list[dict]:
    if not _cache:
        reload_extensions()
    if ext_type:
        return list(_cache.get(ext_type, []))
    result = []
    for items in _cache.values():
        result.extend(items)
    return result


def get_extension(ext_type: str, ext_id: str) -> dict | None:
    for item in list_extensions(ext_type):
        if item.get('id') == ext_id:
            return item
    return None


def list_tools() -> list[dict]:
    """汇总所有可调用工具（Skill + MCP + 内置）。"""
    from modules.ai.builtin_tools import BUILTIN_TOOLS

    tools = [dict(t) for t in BUILTIN_TOOLS]
    for skill in list_extensions('skill'):
        tools.append({
            'name': skill.get('id', ''),
            'description': skill.get('description', skill.get('name', '')),
            'parameters': skill.get('parameters', {'type': 'object', 'properties': {}}),
            'source': 'skill',
            'ext_id': skill.get('id'),
        })
    for mcp in list_extensions('mcp'):
        for tool in mcp.get('tools', []):
            tools.append({
                'name': f"mcp_{mcp.get('id')}_{tool.get('name', '')}",
                'description': tool.get('description', ''),
                'parameters': tool.get('inputSchema', {'type': 'object', 'properties': {}}),
                'source': 'mcp',
                'mcp_id': mcp.get('id'),
                'tool_name': tool.get('name'),
            })
    return tools


def run_skill(skill_id: str, args: dict, context: dict | None = None) -> Any:
    skill = get_extension('skill', skill_id)
    if not skill:
        raise ValueError(f'Skill 不存在: {skill_id}')
    handler_path = skill.get('handler')
    if handler_path:
        fn = _load_handler(handler_path)
        if fn:
            return fn(args=args, context=context or {})
    # 无 handler 时返回技能元数据（模板技能）
    return {'skill': skill_id, 'args': args, 'note': '请实现 handler 函数'}


def run_tool(name: str, args: dict, context: dict | None = None) -> Any:
    from modules.ai.builtin_tools import run_builtin

    builtin_result = run_builtin(name, args, context)
    if builtin_result is not None:
        return builtin_result

    if name.startswith('mcp_'):
        parts = name.split('_', 2)
        if len(parts) >= 3:
            from modules.ai.mcp_client import call_mcp_tool
            return call_mcp_tool(parts[1], parts[2], args)

    skill = get_extension('skill', name)
    if skill:
        return run_skill(name, args, context)

    raise ValueError(f'未知工具: {name}')


# ── ToolPool（参考 claw-code tool_pool.py / tools.py 的 assemble_tool_pool 模式）──

@dataclass
class ToolPool:
    """工具池 — 按权限上下文和模式过滤后的工具集合（参考 claw-code ToolPool）。"""
    tools: list[dict] = field(default_factory=list)
    simple_mode: bool = False
    include_mcp: bool = True
    permission_mode: str = 'ask'
    blocked_count: int = 0

    def as_markdown(self) -> str:
        lines = [
            '# 审计 Agent 工具池',
            '',
            f'工具总数: {len(self.tools)}',
            f'黑名单过滤: {self.blocked_count} 个',
            f'MCP 工具: {"包含" if self.include_mcp else "排除"}',
            f'权限模式: {self.permission_mode}',
        ]
        for t in self.tools[:20]:
            perm = t.get('permission', 'read')
            lines.append(f'- {t["name"]} [{perm}] — {t.get("description", "")[:60]}')
        return '\n'.join(lines)

    def get_tool_names(self) -> list[str]:
        return [t['name'] for t in self.tools]

    def get_by_permission(self, perm_level: str) -> list[dict]:
        return [t for t in self.tools if t.get('permission') == perm_level]


def assemble_tool_pool(
    simple_mode: bool = False,
    include_mcp: bool = True,
    permission_mode: str = 'ask',
) -> ToolPool:
    """组装工具池（参考 claw-code assemble_tool_pool()）。

    Args:
        simple_mode: 仅返回核心工具
        include_mcp: 包含 MCP 工具
        permission_mode: 按权限模式过滤
    """
    from modules.ai.builtin_tools import BUILTIN_TOOLS
    from modules.ai.permission import is_tool_blocked

    tools = []
    blocked = 0

    for t in BUILTIN_TOOLS:
        name = t['name']

        # 黑名单检查（参考 claw-code ToolPermissionContext.blocks()）
        is_blocked, _ = is_tool_blocked(name)
        if is_blocked:
            blocked += 1
            continue

        # 简单模式：仅保留核心工具
        if simple_mode and t.get('permission') not in ('read', 'write'):
            continue

        # 只读模式：排出非 read 工具
        if permission_mode == 'readonly' and t.get('permission') != 'read':
            continue

        tools.append(dict(t))

    # 添加 Skill 工具
    for skill in list_extensions('skill'):
        name = skill.get('id', '')
        is_blocked, _ = is_tool_blocked(name)
        if is_blocked:
            blocked += 1
            continue
        tools.append({
            'name': name,
            'description': skill.get('description', ''),
            'parameters': skill.get('parameters', {}),
            'source': 'skill',
            'permission': 'write',
        })

    # 添加 MCP 工具
    if include_mcp:
        for mcp in list_extensions('mcp'):
            for mcp_tool in mcp.get('tools', []):
                full_name = f"mcp_{mcp.get('id')}_{mcp_tool.get('name', '')}"
                is_blocked, _ = is_tool_blocked(full_name)
                if is_blocked:
                    blocked += 1
                    continue
                tools.append({
                    'name': full_name,
                    'description': mcp_tool.get('description', ''),
                    'parameters': mcp_tool.get('inputSchema', {}),
                    'source': 'mcp',
                    'permission': 'write',
                    'mcp_id': mcp.get('id'),
                    'tool_name': mcp_tool.get('name'),
                })

    return ToolPool(
        tools=tools,
        simple_mode=simple_mode,
        include_mcp=include_mcp,
        permission_mode=permission_mode,
        blocked_count=blocked,
    )
