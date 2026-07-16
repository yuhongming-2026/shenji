"""在线推理策略 — Bandit 式强化学习调参 + 快速路径绕过 LLM。

说明：这不是在 data/models 里训练新权重，而是根据反馈动态调整
max_tokens / temperature，并对高频意图直接走工具短路，显著降低延迟。
"""
from __future__ import annotations

import json
import re
import threading
import time
from pathlib import Path
from typing import Any

_POLICY_PATH = Path(__file__).resolve().parent.parent.parent / 'data' / 'models' / 'inference_policy.json'
_lock = threading.Lock()

_NAV_PATTERNS = [
    (re.compile(r'(?:打开|跳转|去|进入|看看|带我).{0,6}(凭证|记账|voucher)', re.I), 'vouchers'),
    (re.compile(r'(?:打开|跳转|去|进入).{0,6}(应付|payable)', re.I), 'payables'),
    (re.compile(r'(?:打开|跳转|去|进入).{0,6}(应收|receivable)', re.I), 'receivables'),
    (re.compile(r'(?:打开|跳转|去|进入).{0,6}(发票|invoice)', re.I), 'invoices'),
    (re.compile(r'(?:打开|跳转|去|进入).{0,6}(对账|银行)', re.I), 'reconciliation'),
    (re.compile(r'(?:打开|跳转|去|进入).{0,6}(审批)', re.I), 'approvals'),
    (re.compile(r'(?:打开|跳转|去|进入).{0,6}(任务)', re.I), 'tasks'),
    (re.compile(r'(?:打开|跳转|去|进入).{0,6}(财务|总账|科目|账套)', re.I), 'finance'),
    (re.compile(r'(?:打开|跳转|去|进入).{0,6}(审计|概览|dashboard)', re.I), 'dashboard'),
    (re.compile(r'(?:打开|跳转|去|进入).{0,6}(规则|检测|分析)', re.I), 'analysis'),
    (re.compile(r'(?:打开|跳转|去|进入).{0,6}(报告)', re.I), 'report'),
    (re.compile(r'(?:打开|跳转|去|进入).{0,6}(编辑|表格)', re.I), 'edit'),
    (re.compile(r'(?:打开|跳转|去|进入).{0,6}(消息|聊天|协作)', re.I), 'chat'),
    (re.compile(r'(?:打开|跳转|去|进入).{0,6}(agent|智能体|助手)', re.I), 'agent'),
    (re.compile(r'(?:打开|跳转|去|进入).{0,6}(历史)', re.I), 'history'),
    (re.compile(r'(?:打开|跳转|去|进入).{0,6}(导入|上传|首页)', re.I), 'home'),
]

_FINANCE_PATTERNS = [
    re.compile(r'财务总览|科目余额|账套|资产合计|负债|凭证.{0,4}几', re.I),
    re.compile(r'最近.{0,4}凭证|查账|看账', re.I),
    re.compile(r'应付账款|应收账款|应付|应收|发票|银行对账|对账', re.I),
]

# 纯关键词 → (页面, 显示名, 往来类型可选)
_FINANCE_KEYWORDS: list[tuple[str, str, str, str | None]] = [
    ('应付账款', 'payables', '应付账款', 'vendor'),
    ('应付', 'payables', '应付账款', 'vendor'),
    ('应收账款', 'receivables', '应收账款', 'customer'),
    ('应收', 'receivables', '应收账款', 'customer'),
    ('银行对账', 'reconciliation', '银行对账', None),
    ('对账', 'reconciliation', '银行对账', None),
    ('发票', 'invoices', '发票管理', None),
    ('审批', 'approvals', '审批中心', None),
    ('任务', 'tasks', '任务中心', None),
]


def _default_policy() -> dict:
    return {
        'version': 1,
        'bypass_enabled': True,
        'cache_enabled': True,
        'intents': {
            'navigate': {'max_tokens': 96, 'temperature': 0.1, 'fast': True, 'reward_ema': 0.85, 'samples': 0},
            'finance_query': {'max_tokens': 192, 'temperature': 0.15, 'fast': True, 'reward_ema': 0.8, 'samples': 0},
            'simple_qa': {'max_tokens': 256, 'temperature': 0.2, 'fast': True, 'reward_ema': 0.75, 'samples': 0},
            'tool_agent': {'max_tokens': 384, 'temperature': 0.25, 'fast': True, 'reward_ema': 0.7, 'samples': 0},
            'complex': {'max_tokens': 512, 'temperature': 0.35, 'fast': False, 'reward_ema': 0.65, 'samples': 0},
        },
    }


def _load_policy_unlocked() -> dict:
    if _POLICY_PATH.exists():
        try:
            with open(_POLICY_PATH, encoding='utf-8') as f:
                data = json.load(f)
            if isinstance(data, dict) and 'intents' in data:
                return data
        except Exception:
            pass
    policy = _default_policy()
    _save_policy_unlocked(policy)
    return policy


def load_policy() -> dict:
    with _lock:
        return _load_policy_unlocked()


def _save_policy_unlocked(policy: dict) -> None:
    _POLICY_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(_POLICY_PATH, 'w', encoding='utf-8') as f:
        json.dump(policy, f, ensure_ascii=False, indent=2)


def save_policy(policy: dict) -> None:
    with _lock:
        _save_policy_unlocked(policy)


def classify_intent(message: str) -> str:
    msg = (message or '').strip()
    if not msg:
        return 'simple_qa'
    if len(msg) <= 12 and re.match(r'^(你好|hi|hello|谢谢|好的)[!！。.?？]*$', msg, re.I):
        return 'simple_qa'
    for pat, _page in _NAV_PATTERNS:
        if pat.search(msg):
            return 'navigate'
    for pat in _FINANCE_PATTERNS:
        if pat.search(msg):
            return 'finance_query'
    if any(kw in msg for kw, *_ in _FINANCE_KEYWORDS):
        return 'finance_query'
    if re.search(r'审计|规则|Benford|异常|风险', msg, re.I):
        return 'tool_agent'
    if len(msg) > 120 or re.search(r'分析.{0,4}全部|详细|逐步|为什么', msg):
        return 'complex'
    if re.search(r'打开|跳转|查询|帮我|运行|执行', msg):
        return 'tool_agent'
    return 'simple_qa'


def get_generation_params(message: str) -> dict[str, Any]:
    policy = load_policy()
    intent = classify_intent(message)
    cfg = dict(policy.get('intents', {}).get(intent) or policy['intents']['simple_qa'])
    cfg['intent'] = intent
    cfg['cache_enabled'] = policy.get('cache_enabled', True)
    return cfg


def record_outcome(intent: str, *, latency_ms: float, rating: int | None = None, positive: bool | None = None) -> None:
    """Bandit 反馈：根据延迟与用户评分更新该意图的生成参数。"""
    with _lock:
        policy = _load_policy_unlocked()
        intents = policy.setdefault('intents', {})
        cfg = intents.setdefault(intent, _default_policy()['intents']['simple_qa'])

        if positive is None:
            if rating is not None:
                positive = rating >= 4
            else:
                positive = latency_ms < 4000

        reward = 1.0 if positive else 0.0
        ema = float(cfg.get('reward_ema', 0.7))
        cfg['reward_ema'] = round(0.85 * ema + 0.15 * reward, 4)
        cfg['samples'] = int(cfg.get('samples', 0)) + 1

        max_tok = int(cfg.get('max_tokens', 256))
        if not positive or latency_ms > 6000:
            max_tok = max(64, int(max_tok * 0.9))
            cfg['fast'] = True
        elif positive and latency_ms < 2000 and ema > 0.8:
            max_tok = min(512, int(max_tok * 1.05))
        cfg['max_tokens'] = max_tok

        if latency_ms > 8000:
            cfg['temperature'] = max(0.05, float(cfg.get('temperature', 0.3)) - 0.05)

        _save_policy_unlocked(policy)


def try_fast_bypass(message: str, user_id: int | None) -> dict[str, Any] | None:
    """高频意图直接走工具，不调用 LLM（最快路径）。"""
    policy = load_policy()
    if not policy.get('bypass_enabled', True):
        return None

    msg = (message or '').strip()

    # 财务关键词直达（不加载 LLM）
    for keyword, page, label, partner_type in _FINANCE_KEYWORDS:
        if keyword in msg and user_id:
            result = _finance_keyword_reply(user_id, msg, page, label, partner_type)
            if result:
                return result

    intent = classify_intent(msg)

    if intent == 'navigate':
        for pat, page in _NAV_PATTERNS:
            if pat.search(msg):
                from modules.ai.builtin_tools import run_builtin
                result = run_builtin('navigate_page', {'page': page, 'reason': f'正在打开{page}'}, {'user_id': user_id})
                if result:
                    labels = {'vouchers': '凭证管理', 'finance': '财务总览', 'dashboard': '审计概览',
                              'payables': '应付账款', 'receivables': '应收账款', 'invoices': '发票管理',
                              'reconciliation': '银行对账', 'approvals': '审批中心', 'tasks': '任务中心'}
                    label = labels.get(page, page)
                    return {
                        'reply': f'好的，正在为您打开「{label}」。',
                        'actions': [result],
                        'intent': intent,
                        'bypassed': True,
                        'model': 'policy:bypass',
                    }
        return None

    if intent == 'finance_query' and user_id:
        from modules.finance import agent_summary
        from modules.ai.builtin_tools import run_builtin
        try:
            summary = agent_summary(user_id)
            nav = None
            if re.search(r'凭证', msg):
                nav = run_builtin('navigate_page', {'page': 'vouchers'}, {'user_id': user_id})
            lines = [
                '**财务快览**',
                f"- 资产合计：{summary.get('totals', {}).get('assets', 0):.2f}",
                f"- 负债合计：{summary.get('totals', {}).get('liabilities', 0):.2f}",
                f"- 收入：{summary.get('totals', {}).get('revenue', 0):.2f}",
            ]
            vc = summary.get('voucher_counts') or {}
            if vc:
                lines.append(f"- 凭证：已记账 {vc.get('posted', 0)} / 草稿 {vc.get('draft', 0)}")
            actions = [nav] if nav else []
            return {
                'reply': '\n'.join(lines),
                'actions': actions,
                'intent': intent,
                'bypassed': True,
                'model': 'policy:bypass',
            }
        except Exception:
            return None

    if intent == 'simple_qa' and re.match(r'^(你好|hi|hello)[!！。.?？]*$', msg, re.I):
        return {
            'reply': '你好！我是财务智能助手，可以查账、做审计，也能帮你跳转页面。试试说「打开凭证管理」。',
            'actions': [],
            'intent': intent,
            'bypassed': True,
            'model': 'policy:bypass',
        }

    return None


def _finance_keyword_reply(
    user_id: int,
    msg: str,
    page: str,
    label: str,
    partner_type: str | None,
) -> dict[str, Any] | None:
    from modules.ai.builtin_tools import run_builtin
    try:
        lines = [f'**{label}**']
        if partner_type:
            from modules.enterprise_db import list_partners
            partners = list_partners(user_id, partner_type)
            if partners:
                lines.append('往来单位：')
                for p in partners[:5]:
                    bal = float(p.get('balance') or 0)
                    lines.append(f"- {p['code']} {p['name']}：{bal:.2f}")
                total = sum(float(p.get('balance') or 0) for p in partners)
                lines.append(f"合计：{total:.2f}")
            else:
                lines.append('暂无往来单位数据。')
        elif page == 'invoices':
            from modules.enterprise_db import list_invoices
            invs = list_invoices(user_id, limit=5)
            for inv in invs:
                lines.append(f"- {inv['invoice_no']} {inv.get('partner_name','')} {float(inv['amount']):.2f} ({inv['status']})")
            if not invs:
                lines.append('暂无发票记录。')
        elif page == 'reconciliation':
            from modules.enterprise_db import list_bank_accounts
            banks = list_bank_accounts(user_id)
            for b in banks:
                lines.append(f"- {b['bank_name']} 账面余额 {float(b['book_balance']):.2f}")
        nav = run_builtin('navigate_page', {'page': page, 'reason': f'正在打开{label}'}, {'user_id': user_id})
        return {
            'reply': '\n'.join(lines) + f'\n\n正在为您打开「{label}」页面。',
            'actions': [nav] if nav else [],
            'intent': 'finance_query',
            'bypassed': True,
            'model': 'policy:bypass',
        }
    except Exception:
        return None


def rule_based_fallback(message: str, user_id: int | None = None) -> str:
    """模型不可用时的规则回复，保证始终返回 JSON 而非崩溃。"""
    bypass = try_fast_bypass(message, user_id)
    if bypass:
        return bypass['reply']
    return (
        '我是财务智能助手，可直接说：\n'
        '· **应付账款** / **应收账款**\n'
        '· **发票** / **银行对账**\n'
        '· 打开凭证管理 / 财务总览\n'
        '· 审批 / 任务\n\n'
        '复杂分析请前往「财务 Agent」工作台。'
    )


class LatencyTracker:
    def __init__(self, intent: str):
        self.intent = intent
        self._t0 = time.perf_counter()

    def finish(self, rating: int | None = None, positive: bool | None = None) -> float:
        ms = (time.perf_counter() - self._t0) * 1000
        record_outcome(self.intent, latency_ms=ms, rating=rating, positive=positive)
        return ms
