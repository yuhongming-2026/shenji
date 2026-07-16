"""用户角色、主题与功能权限配置（按真实岗位划分可见功能）。"""
from __future__ import annotations

import json

ROLES: dict[str, str] = {
    'audit_manager': '审计经理',
    'finance_director': '财务主管',
    'accountant': '会计',
    'auditor': '审计员',
    'cashier': '出纳',
    'tax_assistant': '税务助理',
    'consultant': '顾问',
    'normal_user': '普通用户',
    'student': '学生',
}

# 需填写公司、同公司自动好友的职业
PROFESSIONAL_ROLES = [
    'audit_manager', 'finance_director', 'accountant', 'auditor',
    'cashier', 'tax_assistant', 'consultant',
]
CUSTOMIZABLE_ROLES = ['normal_user', 'student']

THEMES = {
    'default': '暖沙经典',
    'dark': '深色专业',
    'ocean': '海蓝清爽',
    'forest': '墨绿沉稳',
    'slate': '岩灰商务',
    'rose': '玫红活力',
}

PAGE_STYLES = {
    'classic': '经典侧栏',
    'compact': '紧凑模式',
    'spacious': '宽松模式',
}

ALL_FEATURES = {
    'finance': '财务总览',
    'vouchers': '凭证管理',
    'receivables': '应收账款',
    'payables': '应付账款',
    'invoices': '发票管理',
    'reconciliation': '银行对账',
    'approvals': '审批中心',
    'tasks': '任务中心',
    'upload': '数据导入',
    'edit': '表格编辑',
    'preview': '数据预览',
    'dashboard': '审计概览',
    'analysis': '规则检测',
    'report': '审计报告',
    'history': '历史记录',
    'chat': '消息协作',
    'video': '视频通话',
    'collab': '协同编辑',
    'search': '全文检索',
    'ai': '智能助手',
    'agent': 'AI Agent',
}


def _feats(*keys: str) -> dict[str, bool]:
    enabled = set(keys)
    return {k: (k in enabled) for k in ALL_FEATURES}


# 真实岗位默认权限（职业角色不可在注册时随意勾选）
ROLE_DEFAULTS: dict[str, dict] = {
    # 审计经理：审计全流程 + 审批任务 + 协作；不负责日常出纳/开票录入
    'audit_manager': {
        'theme': 'slate', 'page_style': 'classic',
        'features': _feats(
            'finance', 'receivables', 'payables', 'invoices',
            'approvals', 'tasks',
            'upload', 'edit', 'preview', 'dashboard', 'analysis', 'report', 'history',
            'chat', 'video', 'collab', 'search', 'ai', 'agent',
        ),
    },
    # 财务主管：核算全模块 + 审批；不做深度规则审计/报告签发
    'finance_director': {
        'theme': 'ocean', 'page_style': 'classic',
        'features': _feats(
            'finance', 'vouchers', 'receivables', 'payables', 'invoices', 'reconciliation',
            'approvals', 'tasks',
            'upload', 'edit', 'preview', 'history',
            'chat', 'video', 'collab', 'search', 'ai', 'agent',
        ),
    },
    # 会计：凭证/往来/发票/导入编辑；无审批中心、无审计报告签发
    'accountant': {
        'theme': 'default', 'page_style': 'classic',
        'features': _feats(
            'finance', 'vouchers', 'receivables', 'payables', 'invoices',
            'upload', 'edit', 'preview', 'history',
            'chat', 'video', 'collab', 'search', 'ai',
        ),
    },
    # 审计员：数据导入分析报告；不做凭证记账与银行对账
    'auditor': {
        'theme': 'forest', 'page_style': 'classic',
        'features': _feats(
            'finance', 'receivables', 'payables', 'invoices',
            'upload', 'edit', 'preview', 'dashboard', 'analysis', 'report', 'history',
            'chat', 'video', 'collab', 'search', 'ai', 'agent',
        ),
    },
    # 出纳：收付款相关 + 银行对账；无凭证编制、无审计分析
    'cashier': {
        'theme': 'ocean', 'page_style': 'compact',
        'features': _feats(
            'finance', 'receivables', 'payables', 'invoices', 'reconciliation',
            'upload', 'edit', 'preview', 'history',
            'chat', 'video', 'search', 'ai',
        ),
    },
    # 税务助理：发票与基础数据；无银行对账/审批/凭证
    'tax_assistant': {
        'theme': 'rose', 'page_style': 'classic',
        'features': _feats(
            'finance', 'invoices',
            'upload', 'edit', 'preview', 'analysis', 'history',
            'chat', 'video', 'search', 'ai',
        ),
    },
    # 顾问：只读分析与 AI；不改账
    'consultant': {
        'theme': 'dark', 'page_style': 'spacious',
        'features': _feats(
            'finance', 'preview', 'dashboard', 'analysis', 'report', 'history',
            'chat', 'search', 'ai', 'agent',
        ),
    },
    # 普通用户：基础协作与导入
    'normal_user': {
        'theme': 'default', 'page_style': 'classic',
        'features': _feats(
            'upload', 'edit', 'preview', 'history',
            'chat', 'video', 'collab', 'search', 'ai',
        ),
    },
    # 学生：学习向审计练习，无企业审批/对账/真实开票流程
    'student': {
        'theme': 'ocean', 'page_style': 'spacious',
        'features': _feats(
            'upload', 'edit', 'preview', 'dashboard', 'analysis', 'history',
            'chat', 'video', 'collab', 'search', 'ai', 'agent',
        ),
    },
}

ROLE_HINTS = {
    'audit_manager': '侧重审计计划、规则检测、报告与审批，不含日常开票/对账录入。',
    'finance_director': '侧重财务核算、凭证与审批管理，不含深度审计报告签发。',
    'accountant': '侧重凭证、往来与发票处理，不含审批中心与审计报告。',
    'auditor': '侧重数据分析与审计报告，不含凭证编制与银行对账。',
    'cashier': '侧重收付款与银行对账，不含凭证编制与规则审计。',
    'tax_assistant': '侧重发票与税务相关数据，不含对账与审批。',
    'consultant': '侧重只读分析与 AI 建议，不能改账。',
    'normal_user': '基础导入与协作，可自定义界面。',
    'student': '学习练习模式：导入分析与协作，不含企业审批/对账。',
}


def parse_preferences(raw: str | dict | None) -> dict:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return {}


def get_role_label(role: str | None) -> str:
    return ROLES.get(role or 'normal_user', '普通用户')


def resolve_registration_profile(data: dict) -> dict:
    """根据注册表单解析角色、主题、功能与公司。"""
    role = (data.get('role') or 'normal_user').strip()
    if role not in ROLES:
        role = 'normal_user'

    defaults = ROLE_DEFAULTS.get(role, ROLE_DEFAULTS['normal_user'])
    theme = defaults['theme']
    page_style = defaults['page_style']
    features = dict(defaults['features'])

    company = (data.get('company') or '').strip()
    if role in PROFESSIONAL_ROLES and not company:
        raise ValueError('职业用户注册必须填写公司名称')

    if role in CUSTOMIZABLE_ROLES:
        theme = data.get('theme') or theme
        if theme not in THEMES:
            theme = 'default'
        page_style = data.get('page_style') or page_style
        if page_style not in PAGE_STYLES:
            page_style = 'classic'
        # 功能菜单固定按角色，不接受表单随意全开

    prefs: dict = {
        'features': features,
        'accent_color': data.get('accent_color') or None,
        'company': company or None,
    }

    return {
        'role': role,
        'theme': theme,
        'page_style': page_style,
        'preferences': prefs,
        'company': company,
    }


def get_user_features(user: dict | None) -> dict[str, bool]:
    """返回当前用户可见功能。

    一律按角色 ROLE_DEFAULTS 生效，避免老账号 preferences 全开导致各职业菜单相同。
    普通用户/学生仅可自定义主题与版式，不可随意打开企业核算全模块。
    """
    if not user:
        return {k: False for k in ALL_FEATURES}
    role = user.get('role') or 'normal_user'
    return dict(ROLE_DEFAULTS.get(role, ROLE_DEFAULTS['normal_user'])['features'])


def feature_enabled(user: dict | None, feature: str) -> bool:
    return get_user_features(user).get(feature, False)


def get_user_company(user: dict | None) -> str:
    if not user:
        return ''
    company = (user.get('company') or '').strip()
    if company:
        return company
    prefs = parse_preferences(user.get('preferences'))
    return (prefs.get('company') or '').strip()
