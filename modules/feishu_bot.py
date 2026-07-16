"""飞书机器人集成 — 接收飞书消息，路由到 AI Agent 处理，返回结果。"""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import time
from pathlib import Path
from typing import Any

import yaml

_BASE = Path(__file__).resolve().parent.parent.parent
CONFIG_PATH = _BASE / 'config' / 'feishu.yaml'
_config_cache: dict | None = None


def _load_config() -> dict:
    global _config_cache
    if _config_cache is not None:
        return _config_cache
    if CONFIG_PATH.exists():
        with open(CONFIG_PATH, encoding='utf-8') as f:
            _config_cache = yaml.safe_load(f) or {}
    else:
        _config_cache = {}
    return _config_cache


def save_config(data: dict) -> bool:
    global _config_cache
    CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(data, f, allow_unicode=True, default_flow_style=False)
    _config_cache = data
    return True


def get_config() -> dict:
    """获取当前飞书配置（脱敏处理）。"""
    cfg = dict(_load_config())
    if cfg.get('app_secret'):
        cfg['app_secret'] = cfg['app_secret'][:4] + '****' + cfg['app_secret'][-4:] if len(cfg['app_secret']) > 8 else '****'
    if cfg.get('encrypt_key'):
        cfg['encrypt_key'] = '****'
    return cfg


def get_configured_status() -> dict:
    """检查飞书是否已配置。"""
    cfg = _load_config()
    configured = bool(cfg.get('app_id') and cfg.get('app_secret'))
    return {
        'configured': configured,
        'app_id': cfg.get('app_id', ''),
        'has_secret': bool(cfg.get('app_secret')),
        'bot_name': cfg.get('bot_name', '审计助手'),
    }


def verify_signature(timestamp: str, nonce: str, body: str, signature: str) -> bool:
    """验证飞书回调签名。"""
    cfg = _load_config()
    secret = cfg.get('app_secret', '')
    if not secret:
        return False
    raw = f'{timestamp}{nonce}{secret}{body}'
    computed = hashlib.sha256(raw.encode()).hexdigest()
    return hmac.compare_digest(computed, signature)


def process_message(event: dict) -> dict:
    """处理飞书收到的消息，返回回复内容。

    Args:
        event: 飞书事件对象，包含 msg_type, content, open_id 等

    Returns:
        {'success': bool, 'reply': str, 'reply_type': 'text'|'card'}
    """
    msg_type = event.get('msg_type', 'text')
    content = event.get('content', '{}')

    # 解析消息内容
    text = ''
    try:
        content_obj = json.loads(content)
        text = content_obj.get('text', '')
    except (json.JSONDecodeError, TypeError):
        text = str(content)

    if not text.strip():
        return {'success': False, 'reply': '请发送文字消息'}

    # 特殊命令处理
    lower_text = text.strip().lower()
    if lower_text in ('帮助', 'help', '/help'):
        return {
            'success': True,
            'reply': _help_message(),
            'reply_type': 'text',
        }
    if lower_text in ('状态', 'status', '/status'):
        cfg = _load_config()
        return {
            'success': True,
            'reply': f'🤖 {cfg.get("bot_name", "审计助手")} 在线\n📊 可通过以下指令交互：\n'
                     f'• 帮助 — 查看使用说明\n'
                     f'• 上传XX — 询问数据上传方式\n'
                     f'• 分析 — 执行审计分析\n'
                     f'• 报告 — 获取审计报告摘要\n'
                     f'• 查询XX — 搜索审计知识库',
            'reply_type': 'text',
        }

    # 路由到 AI Agent 处理
    try:
        from modules.ai.agent_engine import run_agent
        from modules.ai.registry import reload_extensions
        reload_extensions()

        context = {
            'source': 'feishu',
            'open_id': event.get('open_id', ''),
            'user_id': event.get('open_id', ''),
        }

        result = run_agent(
            user_message=text,
            context=context,
            max_steps=5,
            system_prompt=(
                '你是财务审计AI助手，通过飞书与用户交流。'
                '用户可能是审计客户或同事，请用中文回答，简洁专业。'
                '可以调用审计工具获取数据和分析结果。'
                '如果用户的请求超出审计范围，友好地引导他们。'
            ),
        )
        reply = result.get('reply', '抱歉，处理请求时遇到了问题，请稍后再试。')
        return {'success': True, 'reply': reply[:4000], 'reply_type': 'text'}
    except Exception as e:
        return {'success': False, 'reply': f'处理失败: {str(e)}'}


def send_card_message(open_id: str, card: dict) -> dict:
    """主动发送飞书卡片消息。

    Args:
        open_id: 接收者的飞书 open_id
        card: 飞书卡片 JSON 对象

    Returns:
        {'success': bool, 'message': str}
    """
    cfg = _load_config()
    if not cfg.get('app_id') or not cfg.get('app_secret'):
        return {'success': False, 'error': '飞书未配置'}

    # 获取 tenant_access_token
    token = _get_tenant_token(cfg)
    if not token:
        return {'success': False, 'error': '获取飞书 access token 失败'}

    # 发送消息
    import urllib.request
    body = json.dumps({
        'receive_id': open_id,
        'msg_type': 'interactive',
        'content': json.dumps(card),
    }).encode('utf-8')

    req = urllib.request.Request(
        'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id',
        data=body,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('code') == 0:
                return {'success': True, 'message_id': result.get('data', {}).get('message_id', '')}
            return {'success': False, 'error': result.get('msg', '未知错误')}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def send_text_message(open_id: str, text: str) -> dict:
    """主动发送飞书文本消息。"""
    cfg = _load_config()
    if not cfg.get('app_id') or not cfg.get('app_secret'):
        return {'success': False, 'error': '飞书未配置'}

    token = _get_tenant_token(cfg)
    if not token:
        return {'success': False, 'error': '获取飞书 access token 失败'}

    import urllib.request
    body = json.dumps({
        'receive_id': open_id,
        'msg_type': 'text',
        'content': json.dumps({'text': text[:4000]}),
    }).encode('utf-8')

    req = urllib.request.Request(
        'https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type=open_id',
        data=body,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {token}',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('code') == 0:
                return {'success': True, 'message_id': result.get('data', {}).get('message_id', '')}
            return {'success': False, 'error': result.get('msg', '未知错误')}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def build_audit_card(title: str, score: dict, findings: list) -> dict:
    """构建飞书审计报告卡片。

    Args:
        title: 报告标题
        score: 评分信息 {'overall_label': '...', 'risk_percentage': 75}
        findings: 发现的异常列表

    Returns:
        飞书卡片 JSON
    """
    risk_color = 'red' if score.get('risk_percentage', 0) > 70 else ('yellow' if score.get('risk_percentage', 0) > 40 else 'green')
    findings_text = '\n'.join(f'- {f}' for f in findings[:5])
    if len(findings) > 5:
        findings_text += f'\n...及其他 {len(findings) - 5} 项'

    return {
        'config': {'wide_screen_mode': True},
        'header': {
            'title': {'tag': 'plain_text', 'content': f'📊 {title}'},
            'template': risk_color,
        },
        'elements': [
            {
                'tag': 'div',
                'text': {'tag': 'lark_md', 'content': f'**风险等级：{score.get("overall_label", "未知")}**\n评分：{score.get("risk_percentage", 0)}%'},
            },
            {
                'tag': 'div',
                'text': {'tag': 'lark_md', 'content': f'**异常发现：**\n{findings_text}'},
            },
            {
                'tag': 'action',
                'actions': [
                    {
                        'tag': 'button',
                        'text': {'tag': 'plain_text', 'content': '查看详情'},
                        'url': cfg.get('web_url', 'http://localhost:5000/report'),
                        'type': 'primary',
                    },
                ],
            },
        ],
    }


# ── 内部辅助 ──

_token_cache: dict[str, Any] = {}


def _get_tenant_token(cfg: dict) -> str | None:
    """获取飞书 tenant_access_token（带缓存）。"""
    global _token_cache
    cache_key = cfg.get('app_id', '')
    cached = _token_cache.get(cache_key)
    if cached and cached.get('expire_time', 0) > time.time():
        return cached.get('token')

    import urllib.request
    body = json.dumps({
        'app_id': cfg['app_id'],
        'app_secret': cfg['app_secret'],
    }).encode('utf-8')

    req = urllib.request.Request(
        'https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal',
        data=body,
        headers={'Content-Type': 'application/json'},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            result = json.loads(resp.read().decode('utf-8'))
            if result.get('code') == 0:
                token = result.get('tenant_access_token', '')
                _token_cache[cache_key] = {
                    'token': token,
                    'expire_time': time.time() + result.get('expire', 7200) - 300,
                }
                return token
    except Exception:
        pass
    return None


def _help_message() -> str:
    return (
        '🤖 财务审计助手 使用说明\n\n'
        '📤 上传数据 — 发送 CSV/Excel 文件到系统进行审计\n'
        '🔍 分析 — 执行审计规则检测和异常发现\n'
        '📊 报告 — 获取审计报告摘要\n'
        '📋 查询 [关键词] — 搜索审计知识库和历史记录\n'
        '👥 协同 — 创建协同编辑会话\n'
        '📈 仪表盘 — 查看数据概览\n\n'
        '💡 提示：你可以直接向我描述你的需求，比如：\n'
        '"分析上周的财务数据"、"检查是否有异常大额交易"、"生成审计报告"等。'
    )
