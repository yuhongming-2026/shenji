"""审计数据助手 Skill — 开发者可参考此模板编写自己的 Skill。"""
from __future__ import annotations

from typing import Any


def run(args: dict | None = None, context: dict | None = None) -> dict[str, Any]:
    args = args or {}
    focus = args.get('focus', 'summary')
    try:
        from modules.ai.builtin_tools import _audit_context, _table_summary
        audit = _audit_context()
        table = _table_summary()
        return {
            'focus': focus,
            'audit': audit,
            'table': table,
            'hint': '可将此结果交给 Agent 进一步分析',
        }
    except Exception as e:
        return {'error': str(e)}
