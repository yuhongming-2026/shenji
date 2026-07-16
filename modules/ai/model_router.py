"""统一模型路由 — 支持本地模型、OpenAI 兼容 API、自动发现本地端点。"""
from __future__ import annotations

import json
import os
import ssl
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any

import yaml

_BASE = Path(__file__).resolve().parent.parent.parent
_CONFIG_PATH = _BASE / 'config' / 'models.yaml'


def _load_config() -> dict:
    if not _CONFIG_PATH.exists():
        return {'models': [], 'default': 'bailian:qwen-plus'}
    with open(_CONFIG_PATH, encoding='utf-8') as f:
        return yaml.safe_load(f) or {}


def save_config(cfg: dict) -> bool:
    """保存模型配置到文件。"""
    _CONFIG_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_CONFIG_PATH, 'w', encoding='utf-8') as f:
        yaml.dump(cfg, f, allow_unicode=True, default_flow_style=False)
    return True


def list_models() -> list[dict[str, Any]]:
    """列出所有已配置模型（含自动发现的本地模型）。"""
    cfg = _load_config()
    models = []
    for m in cfg.get('models', []):
        mid = m.get('id', '')
        available = _check_available(m)
        models.append({
            'id': mid,
            'name': m.get('name', mid),
            'provider': m.get('provider', 'unknown'),
            'description': m.get('description', ''),
            'available': available,
            'is_default': mid == cfg.get('default'),
        })

    # 注入自动发现的本地端点（Ollama / LM Studio / vLLM）
    discovered = _scan_local_endpoints()
    existing_ids = {m['id'] for m in models}
    for d in discovered:
        if d['id'] not in existing_ids:
            models.append(d)

    return models


def scan_local_endpoints() -> list[dict]:
    """公开的本地端点扫描接口。"""
    return _scan_local_endpoints()


def _scan_local_endpoints() -> list[dict]:
    """扫描本地运行的 AI 端点（Ollama、LM Studio、vLLM 等）。"""
    discovered = []
    endpoints = [
        ('http://localhost:11434', 'ollama', 'Ollama'),
        ('http://localhost:1234', 'lmstudio', 'LM Studio'),
        ('http://localhost:8000', 'vllm', 'vLLM'),
        ('http://localhost:4891', 'gpt4all', 'GPT4All'),
    ]

    for base_url, endpoint_id, name in endpoints:
        try:
            ctx = ssl.create_default_context()
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE
            req = urllib.request.Request(
                f'{base_url}/v1/models' if endpoint_id != 'lmstudio' else f'{base_url}/v1/models',
                headers={'Content-Type': 'application/json'},
            )
            with urllib.request.urlopen(req, timeout=3, context=ctx) as resp:
                result = json.loads(resp.read().decode('utf-8'))
                models_list = result.get('data', result.get('models', []))
                if models_list:
                    for m in models_list[:5]:  # 最多列出 5 个模型
                        model_id = m.get('id', m.get('name', ''))
                        discovered.append({
                            'id': f'{endpoint_id}:{model_id}',
                            'name': f'{model_id} ({name})',
                            'provider': 'openai_compat',
                            'description': f'自动发现：{name} @ {base_url}',
                            'available': True,
                            'is_default': False,
                            'auto_discovered': True,
                            'base_url': f'{base_url}/v1',
                            'model': model_id,
                        })
        except Exception:
            pass

    return discovered


def _check_available(model_cfg: dict) -> bool:
    provider = model_cfg.get('provider', '')
    if provider == 'local':
        # 本地权重模式已停用，统一走 API
        return False
    # 自动发现的模型视为可用
    if model_cfg.get('auto_discovered'):
        return True
    api_key_env = model_cfg.get('api_key_env', '')
    if api_key_env:
        return bool(os.environ.get(api_key_env, '').strip())
    return bool(model_cfg.get('api_key', '').strip())


def get_default_model_id() -> str:
    cfg = _load_config()
    return cfg.get('default', 'bailian:qwen-plus')


def _get_model_cfg(model_id: str | None) -> dict:
    mid = model_id or get_default_model_id()
    cfg = _load_config()
    for m in cfg.get('models', []):
        if m.get('id') == mid:
            return m
    # 检查自动发现的模型
    discovered = _scan_local_endpoints()
    for d in discovered:
        if d['id'] == mid:
            return {
                'id': mid,
                'provider': 'openai_compat',
                'model': d.get('model', mid),
                'base_url': d.get('base_url', ''),
                'auto_discovered': True,
            }
    raise ValueError(f'未知模型: {mid}（请在 /models 配置 API 或选择已有模型）')


def chat(
    messages: list[dict[str, str]],
    *,
    model_id: str | None = None,
    max_tokens: int = 1024,
    temperature: float = 0.7,
    fast: bool | None = None,
    use_cache: bool = True,
    **_kwargs,
) -> str:
    """统一聊天入口，仅通过 API / OpenAI 兼容端点调用。

    支持的 provider:
      - openai_compat: OpenAI 兼容协议（百炼兼容模式/DeepSeek/OpenAI/Ollama/vLLM）
      - dashscope: 阿里百炼 DashScope 原生协议
    """
    del fast, use_cache  # 兼容旧调用签名；缓存由调用方自行处理
    cfg = _get_model_cfg(model_id)
    provider = cfg.get('provider', 'openai_compat')

    if provider == 'local':
        raise RuntimeError(
            '本地 Qwen 权重已停用。请到「模型管理」配置 BAILIAN_API_KEY / DEEPSEEK_API_KEY 等云端 API。'
        )

    if provider == 'dashscope':
        return _chat_dashscope(cfg, messages, max_tokens=max_tokens, temperature=temperature)

    return _chat_openai_compatible(cfg, messages, max_tokens=max_tokens, temperature=temperature)


def update_api_key(model_id: str, api_key: str) -> dict:
    """更新模型的 API Key 到环境变量。"""
    cfg = _load_config()
    for m in cfg.get('models', []):
        if m.get('id') == model_id:
            env_var = m.get('api_key_env', '')
            if env_var:
                os.environ[env_var] = api_key
                return {'success': True, 'message': f'已设置 {env_var}', 'model': model_id}
            else:
                m['api_key'] = api_key
                save_config(cfg)
                return {'success': True, 'message': 'API Key 已保存到配置', 'model': model_id}
    return {'success': False, 'error': f'未找到模型: {model_id}'}


def add_model(model_cfg: dict) -> dict:
    """动态添加新模型到配置。"""
    cfg = _load_config()
    models = cfg.get('models', [])
    # 检查是否已存在
    for m in models:
        if m.get('id') == model_cfg.get('id'):
            return {'success': False, 'error': '模型 ID 已存在'}
    models.append(model_cfg)
    cfg['models'] = models
    save_config(cfg)
    return {'success': True, 'message': '模型已添加', 'model': model_cfg.get('id')}


def delete_model(model_id: str) -> dict:
    """从配置中删除模型。"""
    cfg = _load_config()
    models = cfg.get('models', [])
    original_count = len(models)
    cfg['models'] = [m for m in models if m.get('id') != model_id]
    if len(cfg['models']) == original_count:
        return {'success': False, 'error': f'未找到模型: {model_id}'}
    # 如果删除的是默认模型，重置为第一个
    if cfg.get('default') == model_id:
        cfg['default'] = cfg['models'][0].get('id', '') if cfg['models'] else ''
    save_config(cfg)
    return {'success': True, 'message': f'模型 {model_id} 已删除', 'remaining': len(cfg['models'])}


def _chat_dashscope(
    cfg: dict,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    temperature: float,
) -> str:
    """阿里百炼 DashScope 原生协议。

    API 格式 (不同于 OpenAI):
      POST {base_url}/services/aigc/text-generation/generation
      Body: {model, input: {messages}, parameters: {max_tokens, temperature, result_format: "message"}}
      Response: {output: {choices: [{message: {content, role}}]}}

    文档: https://help.aliyun.com/zh/model-studio/use-cases/text-generation
    """
    api_key_env = cfg.get('api_key_env', '')
    api_key = os.environ.get(api_key_env, '').strip() if api_key_env else cfg.get('api_key', '')
    if not api_key:
        raise RuntimeError(f'模型 {cfg.get("id")} 未配置 API Key（请设置环境变量 {api_key_env}）')

    base_url = (cfg.get('base_url') or 'https://dashscope.aliyuncs.com/api/v1').rstrip('/')
    model = cfg.get('model', 'qwen-plus')

    body = json.dumps({
        'model': model,
        'input': {
            'messages': messages,
        },
        'parameters': {
            'result_format': 'message',
            'max_tokens': max_tokens,
            'temperature': temperature,
        },
    }).encode('utf-8')

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        f'{base_url}/services/aigc/text-generation/generation',
        data=body,
        headers={
            'Content-Type': 'application/json',
            'Authorization': f'Bearer {api_key}',
        },
    )
    try:
        with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
            result = json.loads(resp.read().decode('utf-8'))
        # DashScope 响应格式: {output: {choices: [{message: {content, role}}]}}
        if 'output' in result:
            choices = result['output'].get('choices', [])
            if choices:
                content = choices[0].get('message', {}).get('content', '')
                return content.encode('utf-8', errors='replace').decode('utf-8')
        # 兼容：有些百炼 API 也返回 OpenAI 格式
        if 'choices' in result:
            content = result['choices'][0]['message']['content']
            return content.encode('utf-8', errors='replace').decode('utf-8')
        # 错误处理
        if 'message' in result:
            raise RuntimeError(f'DashScope 错误: {result.get("code", "")} - {result["message"]}')
        raise RuntimeError(f'DashScope 返回格式未知: {json.dumps(result)[:300]}')
    except urllib.error.HTTPError as e:
        err = e.read().decode('utf-8') if e.fp else str(e)
        raise RuntimeError(f'DashScope API 错误 ({e.code}): {err[:500]}') from e
    except urllib.error.URLError as e:
        raise RuntimeError(f'DashScope 连接失败: {e.reason}') from e


def _chat_openai_compatible(
    cfg: dict,
    messages: list[dict[str, str]],
    *,
    max_tokens: int,
    temperature: float,
) -> str:
    api_key_env = cfg.get('api_key_env', '')
    api_key = os.environ.get(api_key_env, '').strip() if api_key_env else cfg.get('api_key', '')
    if not api_key and not cfg.get('auto_discovered'):
        raise RuntimeError(f'模型 {cfg.get("id")} 未配置 API Key（环境变量 {api_key_env}）')

    base_url = (cfg.get('base_url') or 'https://api.openai.com/v1').rstrip('/')
    model = cfg.get('model', cfg.get('id', ''))

    body = json.dumps({
        'model': model,
        'messages': messages,
        'max_tokens': max_tokens,
        'temperature': temperature,
    }).encode('utf-8')

    headers = {
        'Content-Type': 'application/json',
    }
    if api_key:
        headers['Authorization'] = f'Bearer {api_key}'

    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE

    req = urllib.request.Request(
        f'{base_url}/chat/completions',
        data=body,
        headers=headers,
    )
    try:
        with urllib.request.urlopen(req, timeout=120, context=ctx) as resp:
            result = json.loads(resp.read().decode('utf-8'))
        content = result['choices'][0]['message']['content']
        return content.encode('utf-8', errors='replace').decode('utf-8')
    except urllib.error.HTTPError as e:
        err = e.read().decode('utf-8') if e.fp else str(e)
        raise RuntimeError(f'API 错误 ({e.code}): {err[:500]}') from e
    except urllib.error.URLError as e:
        raise RuntimeError(f'连接失败: {e.reason}') from e
