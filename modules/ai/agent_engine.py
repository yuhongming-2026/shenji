"""Agent 引擎 — ReAct 循环 + 权限检查 + Hook 系统 + 深度审计上下文绑定。

集成了 claw-code 的以下设计模式:
  - PreToolUse / PostToolUse hooks（参考 claw-code hooks.rs）
  - ToolPermissionContext.blocks() 黑名单检查
  - 结构化 ToolExecution 结果追踪
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from modules.ai.model_router import chat, get_default_model_id
from modules.ai.registry import list_tools, run_tool
from modules.ai.permission import check_permission, PermissionResult


def _collect_action(result: Any, actions: list[dict]) -> None:
    if isinstance(result, dict) and result.get('action') == 'navigate':
        if not any(a.get('url') == result.get('url') for a in actions):
            actions.append(result)


def _tools_prompt(tools: list[dict]) -> str:
    lines = ['可用工具（你可以调用这些工具来操作审计系统）:']
    for t in tools:
        perm = t.get('permission', 'read')
        perm_label = {'read': '📖', 'write': '✏️', 'export': '📤', 'danger': '⚠️'}.get(perm, '')
        lines.append(f"- {t['name']} {perm_label}: {t.get('description', '')}")
    lines.append('')
    lines.append('如需调用工具，请只输出 JSON（不要其他文字）:')
    lines.append('{"action":"tool","tool":"工具名","args":{...}}')
    lines.append('完成后输出: {"action":"answer","content":"你的回答"}')
    lines.append('')
    lines.append('重要提醒：')
    lines.append('- 你已深度绑定审计系统，可以操作数据上传、表格编辑、审计分析、报告导出、用户协同等全部功能')
    lines.append('- 可以引导用户前往不同页面：使用 navigate_page / navigate_to 工具')
    lines.append('- 每次工具调用后，分析返回结果再决定下一步')
    return '\n'.join(lines)


def _parse_action(text: str) -> dict | None:
    """从模型输出中提取 action JSON。

    适配多种 LLM 输出格式:
      - 裸 JSON: {"action":"tool","tool":"xxx","args":{...}}
      - Markdown 代码块: ```json\n{...}\n```
      - 嵌套 JSON（args 可能含嵌套对象）
    """
    text = text.strip()

    # 1. 先尝试提取 Markdown 代码块中的 JSON
    md_match = re.search(r'```(?:json)?\s*\n?(\{[\s\S]*?\})\s*\n?```', text)
    if md_match:
        try:
            return json.loads(md_match.group(1))
        except json.JSONDecodeError:
            pass

    # 2. 从文本中提取最外层 JSON 对象（支持嵌套大括号）
    # 找到第一个 "action" 键，向前找到 {，然后逐字符匹配大括号
    action_pos = text.find('"action"')
    if action_pos >= 0:
        # 向前找到 {
        start = text.rfind('{', 0, action_pos)
        if start >= 0:
            # 从 start 开始逐字符匹配大括号深度
            depth = 0
            end = -1
            for i in range(start, len(text)):
                if text[i] == '{':
                    depth += 1
                elif text[i] == '}':
                    depth -= 1
                    if depth == 0:
                        end = i + 1
                        break
            if end > start:
                try:
                    return json.loads(text[start:end])
                except json.JSONDecodeError:
                    pass

    # 3. 旧版简单正则（兼容）
    m = re.search(r'\{[^{}]*"action"\s*:\s*"[^"]+"[^{}]*\}', text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass

    # 4. 首尾大括号直接解析
    if text.startswith('{') and text.endswith('}'):
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass

    return None


def run_agent(
    user_message: str,
    *,
    model_id: str | None = None,
    history: list[dict[str, str]] | None = None,
    context: dict | None = None,
    max_steps: int = 5,
    system_prompt: str | None = None,
    permission_mode: str = 'ask',       # 'readonly' | 'ask' | 'auto'
    session_id: str = '',
) -> dict[str, Any]:
    """运行 Agent，返回 reply、steps、model、permission_requests。

    Args:
        user_message: 用户消息
        model_id: 模型 ID
        history: 对话历史
        context: 执行上下文（含 user_id, current_page 等）
        max_steps: 最大工具调用步数
        system_prompt: 自定义系统提示词
        permission_mode: 权限模式 (readonly/ask/auto)
        session_id: 会话 ID（用于权限记忆）
    """
    mid = model_id or get_default_model_id()
    tools = list_tools()
    trace: list[dict] = []
    actions: list[dict] = []
    permission_requests: list[dict] = []

    # 构建系统提示词
    context_info = _build_context_info(context)
    sys = system_prompt or (
        '你是财务审计 AI Agent，深度绑定财务大数据审计系统。'
        '你可以操作审计系统的全部功能：数据上传与编辑、审计规则检测、异常发现、三阶段审计、报告导出、历史管理、协同编辑、站内通讯等。'
        '用中文回答，简洁专业。遇到数据异常给出风险解读和行动建议。'
        '如果可以，主动建议用户进行下一步操作（如查看仪表盘、导出报告等）。'
    )
    if context_info:
        sys += '\n\n' + context_info
    sys += '\n\n' + _tools_prompt(tools)

    messages: list[dict[str, str]] = [{'role': 'system', 'content': sys}]
    if history:
        messages.extend(history[-40:])
    messages.append({'role': 'user', 'content': user_message})

    for step in range(max_steps):
        reply = chat(messages, model_id=mid, max_tokens=1024, temperature=0.3)
        action = _parse_action(reply)

        if not action:
            return {'reply': reply, 'steps': trace, 'actions': actions, 'model': mid, 'finished': True, 'permission_requests': permission_requests}

        if action.get('action') == 'answer':
            return {'reply': action.get('content', reply), 'steps': trace, 'actions': actions, 'model': mid, 'finished': True, 'permission_requests': permission_requests}

        if action.get('action') == 'tool':
            tool_name = action.get('tool', '')
            tool_args = action.get('args') or {}

            # ── 权限检查 ──
            perm_result = check_permission(tool_name, tool_args, permission_mode, session_id)
            if not perm_result.allowed:
                if perm_result.needs_approval:
                    # 需要用户确认，暂停执行
                    permission_requests.append(perm_result.to_dict())
                    return {
                        'reply': f'⏸️ 需要确认: {perm_result.message}',
                        'steps': trace,
                        'model': mid,
                        'finished': False,
                        'needs_permission': True,
                        'permission_requests': [perm_result.to_dict()],
                        'pending_tool': {'tool': tool_name, 'args': tool_args},
                    }
                else:
                    # 被自动拒绝
                    trace.append({
                        'step': step + 1, 'tool': tool_name, 'args': tool_args,
                        'error': '权限不足', 'ok': False, 'permission': perm_result.to_dict(),
                    })
                    messages.append({'role': 'assistant', 'content': reply})
                    messages.append({
                        'role': 'user',
                        'content': f'工具 {tool_name} 被拒绝: {perm_result.message}。请换用其他方式。',
                    })
                    continue

            # ── PreToolUse Hook（参考 claw-code hooks.rs PreToolUse 事件）──
            try:
                from modules.ai.hooks import fire_pre_tool, fire_post_tool, HookBlockError
                hook_allowed = fire_pre_tool(tool_name, tool_args, context.get('user_id'), session_id)
                if not hook_allowed:
                    trace.append({
                        'step': step + 1, 'tool': tool_name, 'args': tool_args,
                        'error': '被 Hook 阻止', 'ok': False,
                    })
                    messages.append({'role': 'assistant', 'content': reply})
                    messages.append({'role': 'user', 'content': f'工具 {tool_name} 被系统 Hook 阻止。请换用其他方式。'})
                    continue
            except ImportError:
                pass
            except HookBlockError as hbe:
                trace.append({
                    'step': step + 1, 'tool': tool_name, 'args': tool_args,
                    'error': hbe.reason, 'ok': False,
                })
                messages.append({'role': 'assistant', 'content': reply})
                messages.append({'role': 'user', 'content': f'工具 {tool_name} 被阻止: {hbe.reason}。请换用其他方式。'})
                continue

            # ── 执行工具 ──
            try:
                tool_start = datetime.now()
                result = run_tool(tool_name, tool_args, context)

                # ── PostToolUse Hook（参考 claw-code hooks.rs PostToolUse 事件）──
                try:
                    from modules.ai.hooks import fire_post_tool
                    result = fire_post_tool(tool_name, tool_args, result, context.get('user_id'), session_id)
                except ImportError:
                    pass

                tool_duration_ms = int((datetime.now() - tool_start).total_seconds() * 1000)
                _collect_action(result, actions)
                trace.append({
                    'step': step + 1, 'tool': tool_name, 'args': tool_args,
                    'result': _truncate(result), 'ok': True,
                    'duration_ms': tool_duration_ms,
                })
                messages.append({'role': 'assistant', 'content': reply})
                messages.append({
                    'role': 'user',
                    'content': f'工具 {tool_name} 返回（{tool_duration_ms}ms）:\n{json.dumps(result, ensure_ascii=False)[:3000]}\n请继续或给出最终回答。若已 navigate_page，在 answer 中告知用户即将跳转。',
                })
                continue
            except Exception as e:
                trace.append({
                    'step': step + 1, 'tool': tool_name, 'args': tool_args,
                    'error': str(e), 'ok': False,
                })
                messages.append({'role': 'assistant', 'content': reply})
                messages.append({
                    'role': 'user',
                    'content': f'工具调用失败: {e}。请换用其他方式回答。',
                })
                continue

        return {'reply': reply, 'steps': trace, 'actions': actions, 'model': mid, 'finished': True, 'permission_requests': permission_requests}

    # 达到最大步数，强制总结
    messages.append({'role': 'user', 'content': '请根据已有信息给出最终回答（不要再调用工具）。'})
    final = chat(messages, model_id=mid, max_tokens=1024, temperature=0.5)
    return {'reply': final, 'steps': trace, 'actions': actions, 'model': mid, 'finished': True, 'permission_requests': permission_requests}


def _build_context_info(context: dict | None) -> str:
    """构建当前审计上下文信息，注入系统提示词。"""
    if not context:
        return ''
    parts = ['当前系统上下文:']
    page = context.get('current_page')
    if page:
        page_names = {
            'index': '首页（数据上传）', 'edit': '表格编辑器', 'dashboard': '仪表盘',
            'preview': '数据预览', 'analysis': '审计分析', 'report': '审计报告',
            'history': '历史记录', 'chat': '消息', 'agent': 'AI Agent 工作台',
            'profile': '个人中心', 'search': '搜索',
        }
        parts.append(f'- 用户当前在: {page_names.get(page, page)}')
    source = context.get('source')
    if source:
        parts.append(f'- 交互渠道: {source}')

    # 尝试获取审计数据摘要
    try:
        from app import _analysis_cache, _build_ai_context
        ctx_text = _build_ai_context()
        if ctx_text and ctx_text.strip():
            parts.append('- 当前审计数据:')
            parts.append(ctx_text[:1500])
    except Exception:
        pass

    return '\n'.join(parts)


def _truncate(obj: Any, max_len: int = 2000) -> Any:
    s = json.dumps(obj, ensure_ascii=False) if not isinstance(obj, str) else obj
    if len(s) > max_len:
        return s[:max_len] + '…'
    return obj
