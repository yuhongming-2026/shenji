"""权限策略引擎 — 参考 claw-code 的 5 级模型，简化为 3 级模式 + 工具分级。

模式:
  - readonly: 只允许 read 级别工具
  - ask: 询问用户确认（默认）
  - auto: 全部自动批准

工具级别:
  - read: 只读操作（只读模式下自动允许）
  - write: 修改数据（询问模式下需确认）
  - export: 导出/下载（询问模式下需确认）
  - danger: 删除/危险操作（询问模式下需确认）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

# ── 工具权限映射 ──
_tool_permissions: dict[str, str] = {}

# ── 会话级别的"始终允许"记忆 ──
_always_allow: dict[str, set[str]] = {}  # session_id -> {tool_name, ...}

# ── 全局工具黑名单（参考 claw-code ToolPermissionContext.deny_names/deny_prefixes）────
_deny_names: frozenset = frozenset()
_deny_prefixes: tuple[str, ...] = ()
_deny_reasons: dict[str, str] = {}


def set_denylist(deny_names: list[str] | None = None, deny_prefixes: list[str] | None = None, deny_reasons: dict[str, str] | None = None):
    """设置全局工具黑名单（参考 claw-code ToolPermissionContext.blocks()）。

    Args:
        deny_names: 精确禁止的工具名列表
        deny_prefixes: 禁止的工具名前缀列表
        deny_reasons: 拒绝原因映射 {tool_name: reason}
    """
    global _deny_names, _deny_prefixes, _deny_reasons
    _deny_names = frozenset(name.lower() for name in (deny_names or []))
    _deny_prefixes = tuple(prefix.lower() for prefix in (deny_prefixes or []))
    _deny_reasons = deny_reasons or {}


def is_tool_blocked(tool_name: str) -> tuple[bool, str]:
    """检查工具是否在黑名单中（参考 claw-code ToolPermissionContext.blocks()）。
    返回 (是否被阻止, 原因)。
    """
    lowered = tool_name.lower()
    if lowered in _deny_names:
        return True, _deny_reasons.get(lowered, f'工具 "{tool_name}" 已被管理员禁用')
    for prefix in _deny_prefixes:
        if lowered.startswith(prefix):
            return True, _deny_reasons.get(prefix, f'工具前缀 "{prefix}" 已被管理员禁用')
    return False, ''


def get_denylist() -> dict:
    """获取当前黑名单配置。"""
    return {
        'deny_names': list(_deny_names),
        'deny_prefixes': list(_deny_prefixes),
        'deny_reasons': _deny_reasons,
    }


def init_tool_permissions():
    """从 BUILTIN_TOOLS 加载工具权限映射。"""
    global _tool_permissions
    from modules.ai.builtin_tools import BUILTIN_TOOLS
    _tool_permissions = {}
    for t in BUILTIN_TOOLS:
        _tool_permissions[t['name']] = t.get('permission', 'read')


def get_tool_permission(tool_name: str) -> str:
    """获取工具的权限级别。未知工具默认为 'write'。"""
    if not _tool_permissions:
        init_tool_permissions()
    return _tool_permissions.get(tool_name, 'write')


def get_always_allowed(session_id: str) -> set[str]:
    """获取指定会话的始终允许列表。"""
    return _always_allow.setdefault(session_id, set())


def add_always_allow(session_id: str, tool_name: str):
    """将会话中的某工具加入始终允许列表。"""
    _always_allow.setdefault(session_id, set()).add(tool_name)


def check_permission(
    tool_name: str,
    tool_args: dict,
    mode: str,  # 'readonly' | 'ask' | 'auto'
    session_id: str = '',
) -> PermissionResult:
    """检查工具调用是否需要用户确认。

    Returns:
        PermissionResult with `allowed`, `needs_approval`, `message` fields.
    """
    perm_level = get_tool_permission(tool_name)
    always_allowed = get_always_allowed(session_id)

    # ── 黑名单检查（参考 claw-code ToolPermissionContext.blocks()）──
    blocked, block_reason = is_tool_blocked(tool_name)
    if blocked:
        return PermissionResult(
            allowed=False, needs_approval=False,
            tool_name=tool_name, perm_level=perm_level,
            message=block_reason,
        )

    # 自动模式：全部允许
    if mode == 'auto':
        return PermissionResult(allowed=True, needs_approval=False, tool_name=tool_name, perm_level=perm_level)

    # 始终允许列表
    if tool_name in always_allowed:
        return PermissionResult(allowed=True, needs_approval=False, tool_name=tool_name, perm_level=perm_level, always_allowed=True)

    # 只读模式：仅 read 级别通过
    if mode == 'readonly':
        if perm_level == 'read':
            return PermissionResult(allowed=True, needs_approval=False, tool_name=tool_name, perm_level=perm_level)
        return PermissionResult(
            allowed=False,
            needs_approval=False,
            tool_name=tool_name,
            perm_level=perm_level,
            message=f'当前为只读模式，「{tool_name}」需要 {perm_level} 权限，已被拒绝。请切换到"询问模式"或"自动模式"后再试。',
        )

    # 询问模式：read 自动通过，其他需要确认
    if mode == 'ask':
        if perm_level == 'read':
            return PermissionResult(allowed=True, needs_approval=False, tool_name=tool_name, perm_level=perm_level)
        return PermissionResult(
            allowed=False,
            needs_approval=True,
            tool_name=tool_name,
            perm_level=perm_level,
            tool_args=tool_args,
            message=f'Agent 想要执行「{tool_name}」（{perm_level} 级别操作），需要您的确认。',
        )

    # 未知模式，默认拒绝
    return PermissionResult(allowed=False, needs_approval=False, tool_name=tool_name, message=f'未知权限模式: {mode}')


@dataclass
class PermissionResult:
    allowed: bool = False
    needs_approval: bool = False
    tool_name: str = ''
    perm_level: str = 'read'
    tool_args: dict = field(default_factory=dict)
    message: str = ''
    always_allowed: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            'allowed': self.allowed,
            'needs_approval': self.needs_approval,
            'tool_name': self.tool_name,
            'perm_level': self.perm_level,
            'message': self.message,
            'always_allowed': self.always_allowed,
        }


def describe_mode(mode: str) -> dict:
    """返回权限模式的描述信息。"""
    modes = {
        'readonly': {
            'id': 'readonly',
            'name': '只读模式',
            'icon': 'eye',
            'description': '只能查看数据，不能修改、导出或删除',
            'color': 'info',
        },
        'ask': {
            'id': 'ask',
            'name': '询问模式',
            'icon': 'question-circle',
            'description': '每次修改操作前征求您的同意（推荐）',
            'color': 'warning',
        },
        'auto': {
            'id': 'auto',
            'name': '自动模式',
            'icon': 'lightning',
            'description': '所有操作自动执行，无需确认',
            'color': 'success',
        },
    }
    return modes.get(mode, modes['readonly'])
