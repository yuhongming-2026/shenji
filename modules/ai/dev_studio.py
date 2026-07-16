"""Agent 扩展开发工作室 — 文件读写、脚手架、测试。"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

import yaml

_BASE = Path(__file__).resolve().parent.parent.parent
EXT_ROOT = _BASE / 'extensions'
CONFIG_MODELS = _BASE / 'config' / 'models.yaml'

_TYPE_DIRS = {
    'skill': 'skills',
    'mcp': 'mcp',
    'miniprogram': 'miniprograms',
    'workflow': 'workflows',
    'agent': 'agents',
}

_SKILL_HANDLER_TEMPLATE = '''"""Skill: {name}"""
from __future__ import annotations

from typing import Any


def run(args: dict | None = None, context: dict | None = None) -> dict[str, Any]:
  """args: 工具参数; context: 含 user_id 等运行时上下文"""
  args = args or {{}}
  context = context or {{}}
  # TODO: 在此实现业务逻辑
  return {{"skill": "{skill_id}", "args": args, "status": "ok"}}
'''

_SKILL_JSON_TEMPLATE = {
    'id': '',
    'name': '',
    'description': '',
    'version': '1.0.0',
    'author': '',
    'parameters': {
        'type': 'object',
        'properties': {},
    },
    'handler': '',
}


def _safe_path(rel_path: str) -> Path:
    rel = rel_path.replace('\\', '/').lstrip('/')
    if '..' in rel.split('/'):
        raise ValueError('非法路径')
    full = (_BASE / rel).resolve()
    if not str(full).startswith(str(_BASE.resolve())):
        raise ValueError('路径越界')
    allowed = (_BASE / 'extensions', _BASE / 'config')
    if not any(str(full).startswith(str(a.resolve())) for a in allowed):
        raise ValueError('仅允许编辑 extensions/ 与 config/ 下文件')
    return full


def list_type_files(ext_type: str) -> list[dict]:
    sub = _TYPE_DIRS.get(ext_type)
    if not sub:
        return []
    folder = EXT_ROOT / sub
    if not folder.exists():
        return []
    items: list[dict] = []
    if ext_type == 'skill':
        for d in sorted(folder.iterdir()):
            if not d.is_dir():
                continue
            skill_json = d / 'skill.json'
            if skill_json.exists():
                items.append({
                    'id': d.name,
                    'path': str(skill_json.relative_to(_BASE)).replace('\\', '/'),
                    'handler': str((d / 'handler.py').relative_to(_BASE)).replace('\\', '/')
                    if (d / 'handler.py').exists() else None,
                })
    else:
        patterns = ['*.json', '*.yaml', '*.yml'] if ext_type == 'workflow' else ['*.json']
        for pat in patterns:
            for f in sorted(folder.glob(pat)):
                items.append({
                    'id': f.stem,
                    'path': str(f.relative_to(_BASE)).replace('\\', '/'),
                })
    return items


def read_file(rel_path: str) -> dict:
    path = _safe_path(rel_path)
    if not path.exists():
        raise FileNotFoundError(f'文件不存在: {rel_path}')
    content = path.read_text(encoding='utf-8')
    return {'path': rel_path, 'content': content, 'name': path.name}


def write_file(rel_path: str, content: str) -> dict:
    path = _safe_path(rel_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding='utf-8')
    from modules.ai.registry import reload_extensions
    counts = reload_extensions()
    return {'path': rel_path, 'counts': counts}


def scaffold_skill(skill_id: str, name: str, description: str, author: str = 'developer') -> dict:
    skill_id = re.sub(r'[^a-zA-Z0-9_-]', '_', skill_id.strip())
    if not skill_id:
        raise ValueError('Skill ID 不能为空')
    folder = EXT_ROOT / 'skills' / skill_id
    if folder.exists():
        raise ValueError(f'Skill 已存在: {skill_id}')
    folder.mkdir(parents=True)

    meta = dict(_SKILL_JSON_TEMPLATE)
    meta.update({
        'id': skill_id,
        'name': name or skill_id,
        'description': description or '',
        'author': author,
        'handler': f'extensions/skills/{skill_id}/handler.py:run',
    })
    skill_path = folder / 'skill.json'
    handler_path = folder / 'handler.py'
    skill_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    handler_path.write_text(
        _SKILL_HANDLER_TEMPLATE.format(name=name or skill_id, skill_id=skill_id),
        encoding='utf-8',
    )
    from modules.ai.registry import reload_extensions
    counts = reload_extensions()
    return {
        'skill_id': skill_id,
        'skill_path': str(skill_path.relative_to(_BASE)).replace('\\', '/'),
        'handler_path': str(handler_path.relative_to(_BASE)).replace('\\', '/'),
        'counts': counts,
    }


def scaffold_mcp(mcp_id: str, name: str, url: str = '') -> dict:
    mcp_id = re.sub(r'[^a-zA-Z0-9_-]', '_', mcp_id.strip())
    path = EXT_ROOT / 'mcp' / f'{mcp_id}.json'
    if path.exists():
        raise ValueError(f'MCP 已存在: {mcp_id}')
    data = {
        'id': mcp_id,
        'name': name or mcp_id,
        'description': 'MCP 服务配置',
        'transport': 'http',
        'url': url,
        'headers': {},
        'tools': [],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    from modules.ai.registry import reload_extensions
    return {'path': str(path.relative_to(_BASE)).replace('\\', '/'), 'counts': reload_extensions()}


def scaffold_workflow(wf_id: str, name: str) -> dict:
    wf_id = re.sub(r'[^a-zA-Z0-9_-]', '_', wf_id.strip())
    path = EXT_ROOT / 'workflows' / f'{wf_id}.yaml'
    if path.exists():
        raise ValueError(f'工作流已存在: {wf_id}')
    data = {
        'id': wf_id,
        'name': name or wf_id,
        'description': '新建工作流',
        'version': '1.0',
        'steps': [
            {'type': 'skill', 'skill': 'audit_helper', 'args': {'focus': 'summary'}},
            {'type': 'agent', 'prompt': '根据上一步结果生成办公简报。', 'max_steps': 3},
        ],
    }
    path.write_text(yaml.dump(data, allow_unicode=True, sort_keys=False), encoding='utf-8')
    from modules.ai.registry import reload_extensions
    return {'path': str(path.relative_to(_BASE)).replace('\\', '/'), 'counts': reload_extensions()}


def scaffold_miniprogram(mp_id: str, name: str, description: str = '') -> dict:
    mp_id = re.sub(r'[^a-zA-Z0-9_-]', '_', mp_id.strip())
    path = EXT_ROOT / 'miniprograms' / f'{mp_id}.json'
    if path.exists():
        raise ValueError(f'小程序已存在: {mp_id}')
    data = {
        'id': mp_id,
        'name': name or mp_id,
        'description': description or '办公小程序场景',
        'version': '1.0.0',
        'entry': '/dashboard',
        'icon': 'bi-app',
        'prompts': [
            '根据当前审计数据给出简要分析',
            '列出需要关注的风险点',
        ],
        'required_tools': ['get_audit_context', 'search_knowledge'],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    from modules.ai.registry import reload_extensions
    return {'path': str(path.relative_to(_BASE)).replace('\\', '/'), 'counts': reload_extensions()}


def scaffold_agent(agent_id: str, name: str) -> dict:
    agent_id = re.sub(r'[^a-zA-Z0-9_-]', '_', agent_id.strip())
    path = EXT_ROOT / 'agents' / f'{agent_id}.json'
    if path.exists():
        raise ValueError(f'Agent 已存在: {agent_id}')
    data = {
        'id': agent_id,
        'name': name or agent_id,
        'description': '自定义办公 Agent',
        'model': 'local:qwen2.5-0.5b',
        'system_prompt': '你是办公 AI Agent，帮助用户完成审计与文档任务。',
        'tools': ['get_audit_context', 'search_knowledge'],
        'workflows': [],
    }
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding='utf-8')
    from modules.ai.registry import reload_extensions
    return {'path': str(path.relative_to(_BASE)).replace('\\', '/'), 'counts': reload_extensions()}


def scaffold_feishu_bot(bot_id: str, name: str, description: str = '') -> dict:
    """创建飞书 Bot 脚手架（skill + 配置）。"""
    bot_id = re.sub(r'[^a-zA-Z0-9_-]', '_', bot_id.strip())
    if not bot_id:
        raise ValueError('Bot ID 不能为空')

    # 1. 创建 Skill
    skill_folder = EXT_ROOT / 'skills' / f'feishu_{bot_id}'
    if skill_folder.exists():
        raise ValueError(f'飞书 Bot Skill 已存在: feishu_{bot_id}')
    skill_folder.mkdir(parents=True)

    meta = {
        'id': f'feishu_{bot_id}',
        'name': name or f'飞书Bot-{bot_id}',
        'description': description or '飞书机器人消息处理 Skill',
        'version': '1.0.0',
        'author': 'developer',
        'parameters': {
            'type': 'object',
            'properties': {
                'message': {'type': 'string', 'description': '飞书用户消息'},
                'open_id': {'type': 'string', 'description': '飞书用户 open_id'},
            },
        },
        'handler': f'extensions/skills/feishu_{bot_id}/handler.py:run',
    }
    skill_path = skill_folder / 'skill.json'
    handler_path = skill_folder / 'handler.py'
    skill_path.write_text(json.dumps(meta, ensure_ascii=False, indent=2), encoding='utf-8')
    handler_path.write_text(_FEISHU_HANDLER_TEMPLATE.format(name=name or bot_id, skill_id=f'feishu_{bot_id}'), encoding='utf-8')

    # 2. 创建飞书配置
    feishu_cfg = _BASE / 'config' / f'feishu_{bot_id}.yaml'
    if not feishu_cfg.exists():
        feishu_cfg.write_text(
            f'# 飞书 Bot: {name or bot_id}\n'
            f'app_id: ""\napp_secret: ""\n'
            f'verification_token: ""\nbot_name: "{name or bot_id}"\n'
            f'web_url: "http://localhost:5000"\n',
            encoding='utf-8',
        )

    from modules.ai.registry import reload_extensions
    counts = reload_extensions()
    return {
        'skill_id': f'feishu_{bot_id}',
        'skill_path': str(skill_path.relative_to(_BASE)).replace('\\', '/'),
        'handler_path': str(handler_path.relative_to(_BASE)).replace('\\', '/'),
        'feishu_config': f'config/feishu_{bot_id}.yaml',
        'counts': counts,
    }


def test_skill(skill_id: str, args: dict | None, context: dict | None) -> Any:
    from modules.ai.registry import run_skill
    return run_skill(skill_id, args or {}, context or {})


_FEISHU_HANDLER_TEMPLATE = '''"""飞书 Bot Skill: {name}"""
from __future__ import annotations

from typing import Any


def run(args: dict | None = None, context: dict | None = None) -> dict[str, Any]:
    """处理飞书用户消息。

    args:
        message: 用户消息文本
        open_id: 飞书用户 open_id
    """
    args = args or {{}}
    message = args.get("message", "").strip()
    open_id = args.get("open_id", "")

    if not message:
        return {{"reply": "请发送文字消息", "reply_type": "text"}}

    # 路由到 AI Agent 处理
    try:
        from modules.ai.agent_engine import run_agent
        result = run_agent(
            user_message=message,
            context={{"source": "feishu", "open_id": open_id}},
            max_steps=5,
            system_prompt=(
                "你是财务审计AI助手，通过飞书与用户交流。"
                "用中文回答，简洁专业。可以调用审计工具。"
            ),
        )
        return {{
            "success": True,
            "reply": result.get("reply", "")[:4000],
            "reply_type": "text",
        }}
    except Exception as e:
        return {{"success": False, "reply": f"处理失败: {{e}}", "reply_type": "text"}}
'''
