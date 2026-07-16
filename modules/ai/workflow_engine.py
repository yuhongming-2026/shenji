"""增强工作流引擎 — 顺序/并行/条件分支/对话交互。"""
from __future__ import annotations

import concurrent.futures
import json
import re
from typing import Any, Callable

from modules.ai.registry import get_extension, run_skill


def list_workflows() -> list[dict]:
    from modules.ai.registry import list_extensions
    return list_extensions('workflow')


def run_workflow(
    workflow_id: str,
    *,
    inputs: dict | None = None,
    model_id: str | None = None,
    context: dict | None = None,
    progress_callback: Callable[[str, dict], None] | None = None,
    user_response: str | None = None,  # 用于对话交互恢复
) -> dict[str, Any]:
    """运行工作流。

    支持步骤类型:
      - skill: 调用已注册的 Skill
      - agent: 调用 Agent 引擎
      - mcp: 调用 MCP 工具
      - parallel: 并行执行多个子步骤
      - condition: 条件分支（if/else）

    模板变量: {{prev}}, {{prev.field}}, {{inputs.key}}
    """
    wf = get_extension('workflow', workflow_id)
    if not wf:
        return {'success': False, 'error': f'工作流不存在: {workflow_id}', 'output': None, 'steps': []}

    ctx = dict(context or {})
    inputs = inputs or {}
    steps = wf.get('steps', [])
    results: list[dict] = []
    prev_output: Any = None

    for i, step in enumerate(steps):
        step_type = step.get('type') or _infer_step_type(step)

        if progress_callback:
            progress_callback(f'step_{i+1}', {
                'step': i + 1, 'total': len(steps),
                'type': step_type, 'name': step.get('name', f'步骤 {i+1}'),
            })

        try:
            if step_type == 'skill':
                result = _exec_skill_step(step, inputs, prev_output, ctx)
            elif step_type == 'agent':
                result = _exec_agent_step(step, inputs, prev_output, model_id, ctx, user_response)
                user_response = None  # 只对第一个等待步骤生效
            elif step_type == 'mcp':
                result = _exec_mcp_step(step, inputs, prev_output, ctx)
            elif step_type == 'parallel':
                result = _exec_parallel_steps(step, inputs, prev_output, model_id, ctx)
            elif step_type == 'condition':
                result = _exec_condition_step(step, inputs, prev_output, model_id, ctx)
                if result.get('skip_remaining'):
                    results.append({
                        'index': i + 1, 'type': step_type,
                        'name': step.get('name', ''), 'ok': result.get('success', True),
                        'output': result,
                    })
                    break
            else:
                result = {'success': False, 'error': f'未知步骤类型: {step_type}'}

            results.append({
                'index': i + 1, 'type': step_type,
                'name': step.get('name', ''), 'ok': result.get('success', True),
                'output': result, 'error': result.get('error'),
            })
            prev_output = result

            if not result.get('success') and step.get('required', True):
                return {
                    'workflow_id': workflow_id, 'success': False,
                    'error': f'步骤 {i+1} 失败: {result.get("error")}',
                    'steps': results, 'output': None,
                }
        except Exception as e:
            results.append({'index': i + 1, 'type': step_type, 'name': step.get('name', ''), 'ok': False, 'error': str(e)})
            if step.get('required', True):
                return {'workflow_id': workflow_id, 'success': False, 'error': str(e), 'steps': results, 'output': None}

    return {'workflow_id': workflow_id, 'success': True, 'steps': results, 'output': prev_output}


def _resolve_template(text: str, inputs: dict, prev_output: Any) -> str:
    """替换模板变量。"""
    if '{{prev}}' in text and prev_output is not None:
        text = text.replace('{{prev}}', json.dumps(prev_output, ensure_ascii=False) if isinstance(prev_output, dict) else str(prev_output))
    for key, val in inputs.items():
        text = text.replace(f'{{{{inputs.{key}}}}}', str(val))
    if isinstance(prev_output, dict):
        for match in re.findall(r'\{\{prev\.(\w+)\}\}', text):
            text = text.replace(f'{{{{prev.{match}}}}}', str(prev_output.get(match, '')))
    return text


def _resolve_args(args: dict, inputs: dict, prev_output: Any) -> dict:
    resolved = {}
    for k, v in (args or {}).items():
        resolved[k] = _resolve_template(v, inputs, prev_output) if isinstance(v, str) else v
    return resolved


def _exec_skill_step(step: dict, inputs: dict, prev_output: Any, ctx: dict) -> dict:
    skill_id = step.get('skill') or step.get('skill_id') or step.get('id', '')
    args = _resolve_args(step.get('args', {}), inputs, prev_output)
    if step.get('input') == '{{prev}}' and prev_output is not None:
        args['prev'] = prev_output
    return run_skill(skill_id, args, ctx)


def _exec_agent_step(step: dict, inputs: dict, prev_output: Any, model_id: str | None, ctx: dict, user_response: str | None = None) -> dict:
    prompt = step.get('prompt', step.get('message', ''))
    resolved_prompt = _resolve_template(prompt, inputs, prev_output)
    if step.get('input') == '{{prev}}' and prev_output is not None:
        resolved_prompt += f'\n\n上一步结果:\n{json.dumps(prev_output, ensure_ascii=False)[:2000]}'
    if user_response and step.get('wait_for_user'):
        resolved_prompt = f'用户回复: {user_response}\n\n原始请求: {resolved_prompt}'

    if step.get('wait_for_user') and not user_response:
        return {'success': True, 'wait_for_user': True, 'prompt': resolved_prompt, 'message': '请用户输入以继续', '_user_response_needed': True}

    from modules.ai.agent_engine import run_agent
    result = run_agent(
        user_message=resolved_prompt,
        model_id=model_id or step.get('model'),
        context=ctx,
        max_steps=step.get('max_steps', 3),
        system_prompt=step.get('system_prompt'),
    )
    return {'success': True, 'reply': result.get('reply', ''), 'agent_steps': result.get('steps', [])}


def _exec_mcp_step(step: dict, inputs: dict, prev_output: Any, ctx: dict) -> dict:
    from modules.ai.mcp_client import call_mcp_tool
    args = _resolve_args(step.get('args', {}), inputs, prev_output)
    result = call_mcp_tool(step['mcp_id'], step['tool'], args)
    return {'success': True, 'result': result}


def _exec_parallel_steps(step: dict, inputs: dict, prev_output: Any, model_id: str | None, ctx: dict) -> dict:
    sub_steps = step.get('steps', [])
    if not sub_steps:
        return {'success': False, 'error': 'parallel 步骤缺少子步骤'}

    def _run_sub(sub_step: dict) -> dict:
        st = sub_step.get('type', 'skill')
        try:
            if st == 'skill':
                return _exec_skill_step(sub_step, inputs, prev_output, ctx)
            elif st == 'agent':
                return _exec_agent_step(sub_step, inputs, prev_output, model_id, ctx)
            elif st == 'mcp':
                return _exec_mcp_step(sub_step, inputs, prev_output, ctx)
            return {'success': False, 'error': f'未知子步骤: {st}'}
        except Exception as e:
            return {'success': False, 'error': str(e)}

    with concurrent.futures.ThreadPoolExecutor(max_workers=min(len(sub_steps), 8)) as executor:
        futures = {executor.submit(_run_sub, s): i for i, s in enumerate(sub_steps)}
        results_list = [None] * len(sub_steps)
        for future in concurrent.futures.as_completed(futures):
            idx = futures[future]
            try:
                results_list[idx] = future.result()
            except Exception as e:
                results_list[idx] = {'success': False, 'error': str(e)}

    has_failure = any(r and not r.get('success') for r in results_list)
    return {'success': not has_failure, 'parallel_results': results_list, 'completed': sum(1 for r in results_list if r), 'total': len(sub_steps)}


def _exec_condition_step(step: dict, inputs: dict, prev_output: Any, model_id: str | None, ctx: dict) -> dict:
    condition = step.get('condition', {})
    field = condition.get('field', 'success')
    op = condition.get('op', 'eq')
    value = condition.get('value', True)

    actual = prev_output.get(field) if isinstance(prev_output, dict) else prev_output
    if op == 'eq':
        condition_met = actual == value
    elif op == 'neq':
        condition_met = actual != value
    elif op in ('gt', 'gte', 'lt', 'lte'):
        try:
            a, v = float(actual or 0), float(value)
            condition_met = (op == 'gt' and a > v) or (op == 'gte' and a >= v) or (op == 'lt' and a < v) or (op == 'lte' and a <= v)
        except (ValueError, TypeError):
            condition_met = False
    elif op == 'contains':
        condition_met = str(value).lower() in str(actual or '').lower()
    elif op == 'exists':
        condition_met = actual is not None
    else:
        condition_met = False

    branch_steps = step.get('if_true' if condition_met else 'if_false', [])
    if not branch_steps:
        return {'success': True, 'condition_met': condition_met}

    result = None
    for sub_step in branch_steps:
        st = sub_step.get('type', 'skill')
        if st == 'skill':
            result = _exec_skill_step(sub_step, inputs, prev_output, ctx)
        elif st == 'agent':
            result = _exec_agent_step(sub_step, inputs, prev_output, model_id, ctx)
        elif st == 'mcp':
            result = _exec_mcp_step(sub_step, inputs, prev_output, ctx)

    return {'success': True, 'condition_met': condition_met, 'branch': 'if_true' if condition_met else 'if_false', 'result': result}


def _infer_step_type(step: dict) -> str:
    if 'skill' in step:
        return 'skill'
    if 'mcp_id' in step:
        return 'mcp'
    if 'prompt' in step or step.get('type') == 'agent':
        return 'agent'
    if 'steps' in step and step.get('type') == 'parallel':
        return 'parallel'
    if 'condition' in step:
        return 'condition'
    return step.get('type', 'skill')
