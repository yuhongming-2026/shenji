"""Coze 式 Bot 编排 — 多 Agent 协作工作流。"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from modules.ai.agent_engine import run_agent
from modules.ai.registry import get_extension, list_extensions

_BOTS_ROOT = Path(__file__).resolve().parent.parent.parent / 'extensions' / 'bots'


def list_bots() -> list[dict]:
    if not _BOTS_ROOT.exists():
        return []
    bots = []
    for path in sorted(_BOTS_ROOT.glob('*.json')):
        try:
            with open(path, encoding='utf-8') as f:
                data = json.load(f)
            data['_path'] = str(path.name)
            bots.append(data)
        except Exception:
            pass
    return bots


def get_bot(bot_id: str) -> dict | None:
    for b in list_bots():
        if b.get('id') == bot_id:
            return b
    return None


def run_bot(
    bot_id: str,
    user_message: str,
    *,
    model_id: str | None = None,
    context: dict | None = None,
    history: list[dict[str, str]] | None = None,
) -> dict[str, Any]:
    """按 Bot 定义顺序调度多个 Agent，上一步输出传入下一步。"""
    bot = get_bot(bot_id)
    if not bot:
        raise ValueError(f'Bot 不存在: {bot_id}')

    ctx = dict(context or {})
    trace: list[dict] = []
    actions: list[dict] = []
    prev_reply = ''
    shared_context = ''

    for i, step in enumerate(bot.get('agents', [])):
        agent_id = step.get('agent') or step.get('id')
        agent_cfg = get_extension('agent', agent_id) or {}
        if i == 0:
            prompt = user_message
        else:
            prompt = step.get('prompt') or '请基于上文继续'
        if i > 0 and prev_reply:
            prompt = f'{prompt}\n\n【上一步 Agent ({agent_id}) 输出】\n{prev_reply[:2000]}'
        if shared_context:
            prompt = f'{shared_context}\n\n{prompt}'

        handoff = step.get('handoff', '')
        if handoff:
            prompt = f'{handoff}\n{prompt}'

        result = run_agent(
            prompt,
            model_id=model_id or step.get('model') or agent_cfg.get('model'),
            history=history if i == 0 else None,
            context=ctx,
            max_steps=step.get('max_steps', 3),
            system_prompt=agent_cfg.get('system_prompt'),
        )
        prev_reply = result.get('reply', '')
        for a in result.get('actions') or []:
            if a not in actions:
                actions.append(a)
        trace.append({
            'step': i + 1,
            'agent': agent_id,
            'name': agent_cfg.get('name', agent_id),
            'reply_preview': prev_reply[:200],
            'tools': [s.get('tool') for s in result.get('steps', [])],
            'ok': True,
        })
        shared_context += f'\n[Agent {agent_id}]: {prev_reply[:500]}'

    return {
        'reply': prev_reply,
        'bot_id': bot_id,
        'bot_name': bot.get('name', bot_id),
        'trace': trace,
        'actions': actions,
        'finished': True,
    }
