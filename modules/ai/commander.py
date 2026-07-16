"""多Agent指挥官系统 — 参考 claw-code OmO (oh-my-openagent) 多Agent协作模式。

模式:
  - single: 单模型模式，用户选择一个模型直接对话
  - auto: 自动路由，根据任务类型自动选择最佳模型
  - multi: 多Agent协作，指挥官拆解任务 → 分派给专业Agent → 汇总

架构 (参考 claw-code Architect → Executor → Reviewer 模式):
  用户消息 → Commander 分析任务
    → Agent A (分析模型, 如 qwen-max)    ─┐
    → Agent B (执行模型, 如 qwen-plus)    ─┤ 并行执行
    → Agent C (审核模型, 如 qwen-turbo)   ─┘
  → Commander 汇总 → 最终回复
"""
from __future__ import annotations

import json
import re
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any

# ── 任务分类（Auto 模式路由）──

TASK_PATTERNS = {
    'quick': {
        'keywords': ['你好', '帮助', '怎么', '是什么', '列出', '显示', '多少', '哪个', '状态', '统计', '计数', 'count', 'list', 'help', 'what'],
        'model': 'bailian:qwen-turbo',
        'description': '简单问答/查询',
    },
    'analysis': {
        'keywords': ['分析', '审计', '风险', '异常', '检测', '检查', '评估', '报告', '合规', 'audit', 'risk', 'analysis', 'review'],
        'model': 'bailian:qwen-plus',
        'description': '审计分析/规则检测',
    },
    'complex': {
        'keywords': ['综合', '深度', '复杂', '推理', '判断', '建议', '策略', '方案', '全部', '所有', '完整', 'comprehensive', 'full', 'all', 'deep'],
        'model': 'bailian:qwen-max',
        'description': '复杂推理/综合决策',
    },
    'vision': {
        'keywords': ['图片', '图像', '识别', '扫描', 'OCR', '发票', '凭证', '表格图片', 'image', 'ocr', 'scan', 'photo', 'picture'],
        'model': 'bailian:qwen-vl-plus',
        'description': '图像识别/OCR',
    },
}

DEFAULT_AUTO_MODEL = 'bailian:qwen-plus'


def classify_task(user_message: str) -> dict:
    """根据用户消息自动分类任务类型，返回推荐的模型。

    Args:
        user_message: 用户消息文本

    Returns:
        {'task_type': 'quick'|'analysis'|'complex'|'vision', 'model': 'model_id', 'reason': '...'}
    """
    msg_lower = user_message.lower()

    # 按优先级匹配：complex > vision > analysis > quick
    for task_type in ['complex', 'vision', 'analysis', 'quick']:
        pattern = TASK_PATTERNS[task_type]
        keyword_count = sum(1 for kw in pattern['keywords'] if kw in msg_lower)
        if keyword_count >= 1 or (task_type == 'quick' and len(user_message) < 15):
            return {
                'task_type': task_type,
                'model': pattern['model'],
                'reason': f'检测到{pattern["description"]}任务（命中 {keyword_count} 个关键词）',
                'description': pattern['description'],
            }

    # 默认用 Plus
    return {
        'task_type': 'analysis',
        'model': DEFAULT_AUTO_MODEL,
        'reason': '未匹配特殊模式，使用默认分析模型',
        'description': '通用分析',
    }


# ── 多Agent指挥官 ──

COMMANDER_SYSTEM_PROMPT = """你是多Agent协作系统的指挥官（Commander）。

你的职责：
1. 分析用户的任务，判断是否可以拆解为多个子任务并行执行
2. 如果需要拆解，输出任务分配方案
3. 收集各专业Agent的结果，汇总成最终回复

任务分配输出格式（JSON）：
{
  "action": "dispatch",
  "subtasks": [
    {"id": 1, "role": "分析", "prompt": "子任务描述"},
    {"id": 2, "role": "执行", "prompt": "子任务描述"}
  ],
  "reasoning": "为什么这样分配"
}

如果任务不需要拆解（比如简单问答），输出：
{
  "action": "direct",
  "prompt": "直接执行的prompt"
}

重要：你只能输出 JSON，不要输出其他内容。"""


def run_commander(
    user_message: str,
    *,
    available_models: list[str],
    context: dict | None = None,
    model_id: str | None = None,
    history: list[dict] | None = None,
    permission_mode: str = 'ask',
    session_id: str = '',
) -> dict[str, Any]:
    """多Agent指挥官模式。

    流程：
    1. Commander 分析用户消息，决定拆解方案
    2. 并行分派给专业 Worker Agent 执行
    3. Commander 汇总结果

    Args:
        user_message: 用户消息
        available_models: 可用的模型 ID 列表（至少 2-3 个）
        model_id: 指挥官使用的模型
        context: 执行上下文
        history: 对话历史
        permission_mode: 权限模式
        session_id: 会话 ID

    Returns:
        {'reply': str, 'plan': dict, 'worker_results': list, 'mode': 'multi'}
    """
    from modules.ai.model_router import chat, get_default_model_id

    commander_model = model_id or get_default_model_id()
    ctx = context or {}

    # Step 1: Commander 分析并拆解任务
    analyze_messages = [
        {'role': 'system', 'content': COMMANDER_SYSTEM_PROMPT},
        {'role': 'user', 'content': f'用户任务: {user_message}\n\n可用的专业Agent模型: {", ".join(available_models)}\n\n请分析任务并给出执行方案（只输出JSON）。'},
    ]

    try:
        raw = chat(analyze_messages, model_id=commander_model, max_tokens=1024, temperature=0.2)
        plan = _parse_commander_response(raw)
    except Exception as e:
        return {
            'reply': f'指挥官模型调用失败: {e}，已降级为单模型模式。请重试或切换到单模型模式。',
            'plan': None,
            'worker_results': [],
            'mode': 'multi',
            'error': str(e),
        }

    # 简单任务 — 直接执行
    if plan.get('action') == 'direct':
        from modules.ai.agent_engine import run_agent
        result = run_agent(
            user_message=plan.get('prompt', user_message),
            model_id=commander_model,
            context=ctx,
            permission_mode=permission_mode,
            session_id=session_id,
        )
        return {
            'reply': f'[指挥官判断: 无需拆解，直接执行]\n\n{result.get("reply", "")}',
            'plan': plan,
            'worker_results': [],
            'mode': 'multi',
        }

    # 复杂任务 — 并行分派 Worker Agent
    subtasks = plan.get('subtasks', [])
    if not subtasks:
        subtasks = [{'id': 1, 'role': '执行', 'prompt': user_message}]

    # 分配模型给各 Worker（轮转分配，每个Worker用不同模型增强多样性）
    worker_results = []
    with ThreadPoolExecutor(max_workers=min(len(subtasks), 4)) as executor:
        futures = {}
        for i, subtask in enumerate(subtasks):
            worker_model = available_models[i % len(available_models)]
            futures[executor.submit(
                _run_worker,
                subtask, worker_model, ctx, history, permission_mode, session_id,
            )] = (subtask, worker_model)

        for future in as_completed(futures):
            subtask, w_model = futures[future]
            try:
                result = future.result(timeout=120)
                worker_results.append({
                    'subtask': subtask,
                    'model': w_model,
                    'result': result,
                })
            except Exception as e:
                worker_results.append({
                    'subtask': subtask,
                    'model': w_model,
                    'error': str(e),
                })

    # Step 3: Commander 汇总
    synthesis_messages = [
        {'role': 'system', 'content': '你是多Agent指挥官。请根据各专业Agent的执行结果，汇总成一个完整、专业的回复。用中文，简洁全面。'},
        {'role': 'user', 'content': f'原始任务: {user_message}\n\n各Agent执行结果:\n{json.dumps(worker_results, ensure_ascii=False, indent=2)[:4000]}\n\n请汇总回复。'},
    ]

    try:
        final_reply = chat(synthesis_messages, model_id=commander_model, max_tokens=2000, temperature=0.5)
    except Exception as e:
        # 降级：直接拼接各 Worker 结果
        parts = [f'## {wr["subtask"].get("role", "Agent")}: {wr["subtask"].get("prompt", "")[:100]}\n'
                 + (wr.get('result', {}).get('reply', str(wr)) if isinstance(wr.get('result'), dict) else str(wr))
                 + (f'\n⚠️ {wr["error"]}' if wr.get('error') else '')
                 for wr in worker_results]
        final_reply = '\n\n---\n\n'.join(parts)

    return {
        'reply': final_reply,
        'plan': plan,
        'worker_results': [{'role': wr['subtask'].get('role', ''), 'model': wr['model'],
                            'ok': 'error' not in wr}
                           for wr in worker_results],
        'mode': 'multi',
    }


def _run_worker(
    subtask: dict,
    model_id: str,
    context: dict,
    history: list[dict] | None,
    permission_mode: str,
    session_id: str,
) -> dict:
    """执行单个 Worker Agent 任务。"""
    from modules.ai.agent_engine import run_agent
    role = subtask.get('role', 'Worker')
    prompt = subtask.get('prompt', '')

    worker_system = (
        f'你是专业Agent，负责: {role}。'
        '根据分配的任务，利用可用工具获取审计数据并给出专业回答。用中文。'
    )
    return run_agent(
        user_message=prompt,
        model_id=model_id,
        history=history,
        context=context,
        max_steps=3,
        system_prompt=worker_system,
        permission_mode=permission_mode,
        session_id=f'{session_id}_worker_{subtask.get("id", 0)}',
    )


def _parse_commander_response(raw: str) -> dict:
    """解析 Commander 的 JSON 响应。"""
    raw = raw.strip()
    # 提取 JSON
    m = re.search(r'\{[^{}]*"action"\s*:\s*"[^"]+"[^{}]*\}', raw, re.DOTALL)
    if m:
        try:
            return json.loads(m.group())
        except json.JSONDecodeError:
            pass
    # 尝试直接解析
    if raw.startswith('{'):
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            pass
    # 降级：直接执行
    return {'action': 'direct', 'prompt': raw[:500]}
