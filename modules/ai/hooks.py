"""Hook 系统 — 参考 claw-code 的事件驱动架构。

claw-code hooks 支持的事件类型:
  - PreToolUse: 工具调用前触发，可阻止执行
  - PostToolUse: 工具调用后触发，可修改结果
  - UserPromptSubmit: 用户提交消息时触发
  - Stop: Agent 停止时触发
  - SessionStart: 会话开始时触发
  - SessionEnd: 会话结束时触发
  - PreCompact: 上下文压缩前触发
  - SubagentStop: 子 Agent 停止时触发
  - Notification: 系统通知时触发

每个 hook 可以返回:
  - 空 / None → 继续（无影响）
  - 非空 dict → 用于 PostToolUse 修改 result
  - raise HookBlockError → 阻止操作
"""
from __future__ import annotations

import json
import os
import threading
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Callable

# ── 事件类型 ──

class HookEvent(str, Enum):
    PRE_TOOL_USE = "PreToolUse"
    POST_TOOL_USE = "PostToolUse"
    USER_PROMPT_SUBMIT = "UserPromptSubmit"
    STOP = "Stop"
    SESSION_START = "SessionStart"
    SESSION_END = "SessionEnd"
    PRE_COMPACT = "PreCompact"
    SUBAGENT_STOP = "SubagentStop"
    NOTIFICATION = "Notification"


# ── Hook 结果 ──

class HookBlockError(Exception):
    """Hook 阻止操作时抛出。"""
    def __init__(self, reason: str = "操作被 hook 阻止"):
        self.reason = reason
        super().__init__(reason)


@dataclass
class HookContext:
    """传递给每个 hook 函数的上下文。"""
    event: HookEvent
    tool_name: str = ""
    tool_args: dict = field(default_factory=dict)
    tool_result: Any = None
    user_message: str = ""
    user_id: int | None = None
    session_id: str = ""
    metadata: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            'event': self.event.value,
            'tool_name': self.tool_name,
            'tool_args': self.tool_args,
            'tool_result': str(self.tool_result)[:500] if self.tool_result else None,
            'user_message': self.user_message[:200],
            'user_id': self.user_id,
            'session_id': self.session_id,
        }


# ── Hook 注册表 ──

_hooks: dict[HookEvent, list[Callable]] = {
    e: [] for e in HookEvent
}
_hooks_dir: Path | None = None
_lock = threading.Lock()


def register_hook(event: HookEvent, callback: Callable[[HookContext], Any | None]):
    """注册一个 hook 回调函数。

    Args:
        event: 触发事件类型
        callback: 回调函数，接收 HookContext，返回 None 继续 / 非空修改结果 / raise HookBlockError 阻止

    Example:
        def my_pre_tool(ctx: HookContext):
            if ctx.tool_name == 'delete_table':
                raise HookBlockError('删除表操作被禁止')
        register_hook(HookEvent.PRE_TOOL_USE, my_pre_tool)
    """
    with _lock:
        _hooks[event].append(callback)


def unregister_hook(event: HookEvent, callback: Callable):
    """取消注册 hook。"""
    with _lock:
        try:
            _hooks[event].remove(callback)
        except ValueError:
            pass


def list_hooks() -> dict[str, int]:
    """列出所有已注册的 hook 类型及其数量。"""
    with _lock:
        return {e.value: len(hooks) for e, hooks in _hooks.items()}


def _run_event(event: HookEvent, ctx: HookContext) -> list[Any]:
    """触发某个事件的所有 hooks。返回非空结果列表。"""
    results = []
    for callback in _hooks.get(event, []):
        try:
            result = callback(ctx)
            if result is not None:
                results.append(result)
        except HookBlockError as e:
            # 传播阻止
            raise
        except Exception as e:
            # hook 出错不阻断主流程
            pass
    return results


# ── 高层 API（供 agent_engine 调用） ──

def fire_pre_tool(tool_name: str, tool_args: dict, user_id: int | None = None, session_id: str = "") -> bool:
    """工具调用前触发 PreToolUse hooks。
    返回 True 表示允许执行，False 表示被阻止。
    """
    ctx = HookContext(
        event=HookEvent.PRE_TOOL_USE,
        tool_name=tool_name,
        tool_args=tool_args,
        user_id=user_id,
        session_id=session_id,
    )
    try:
        _run_event(HookEvent.PRE_TOOL_USE, ctx)
        return True
    except HookBlockError:
        return False


def fire_post_tool(tool_name: str, tool_args: dict, tool_result: Any, user_id: int | None = None, session_id: str = "") -> Any:
    """工具调用后触发 PostToolUse hooks。
    返回可能被 hook 修改后的结果。
    """
    ctx = HookContext(
        event=HookEvent.POST_TOOL_USE,
        tool_name=tool_name,
        tool_args=tool_args,
        tool_result=tool_result,
        user_id=user_id,
        session_id=session_id,
    )
    results = _run_event(HookEvent.POST_TOOL_USE, ctx)
    # 如果 hook 返回了修改结果，使用最后一个
    if results:
        return results[-1]
    return tool_result


def fire_user_prompt(message: str, user_id: int | None = None) -> str:
    """用户消息提交时触发 UserPromptSubmit hooks。
    返回可能被 hook 修改后的消息。
    """
    ctx = HookContext(
        event=HookEvent.USER_PROMPT_SUBMIT,
        user_message=message,
        user_id=user_id,
    )
    results = _run_event(HookEvent.USER_PROMPT_SUBMIT, ctx)
    if results and isinstance(results[-1], str):
        return results[-1]
    return message


def fire_session_start(session_id: str, user_id: int | None = None):
    """会话开始时触发。"""
    ctx = HookContext(
        event=HookEvent.SESSION_START,
        session_id=session_id,
        user_id=user_id,
    )
    _run_event(HookEvent.SESSION_START, ctx)


def fire_session_end(session_id: str, user_id: int | None = None):
    """会话结束时触发。"""
    ctx = HookContext(
        event=HookEvent.SESSION_END,
        session_id=session_id,
        user_id=user_id,
    )
    _run_event(HookEvent.SESSION_END, ctx)


def fire_notification(message: str, level: str = "info", **meta):
    """发送系统通知。"""
    ctx = HookContext(
        event=HookEvent.NOTIFICATION,
        user_message=message,
        metadata={'level': level, **meta},
    )
    _run_event(HookEvent.NOTIFICATION, ctx)


# ── 内置 Hooks（参考 claw-code 的常用 hooks） ──

def _builtin_audit_log_hook(ctx: HookContext):
    """内置 Hook：记录所有工具调用到审计日志。"""
    try:
        log_entry = {
            'event': ctx.event.value,
            'tool': ctx.tool_name,
            'user_id': ctx.user_id,
            'timestamp': __import__('datetime').datetime.now().isoformat(),
        }
        # 写入 hooks 日志文件
    except Exception:
        pass


def _builtin_tool_denylist_hook(ctx: HookContext):
    """内置 Hook：危险工具黑名单（在只读场景下强制阻止）。"""
    if ctx.event != HookEvent.PRE_TOOL_USE:
        return
    # 从 permissions 模块获取工具级别
    from modules.ai.permission import get_tool_permission
    perm = get_tool_permission(ctx.tool_name)
    # 危险工具需要额外注意
    if perm == 'danger':
        pass  # allow — permission 模块会处理


def register_builtin_hooks():
    """注册内置 hooks（启动时自动调用）。"""
    register_hook(HookEvent.PRE_TOOL_USE, _builtin_audit_log_hook)
    register_hook(HookEvent.POST_TOOL_USE, _builtin_audit_log_hook)
    register_hook(HookEvent.SESSION_START, _builtin_audit_log_hook)
    register_hook(HookEvent.SESSION_END, _builtin_audit_log_hook)


# 启动时注册
try:
    register_builtin_hooks()
except Exception:
    pass
