"""系统页面注册表 — Agent 可跳转的页面与说明。"""
from __future__ import annotations

PAGES: dict[str, dict] = {
    'home': {'url': '/', 'label': '数据导入', 'desc': '上传 CSV/Excel/图片凭证'},
    'import': {'url': '/', 'label': '数据导入', 'desc': '上传财务数据文件'},
    'receivables': {'url': '/finance/receivables', 'label': '应收账款', 'desc': '客户往来与账龄'},
    'payables': {'url': '/finance/payables', 'label': '应付账款', 'desc': '供应商往来'},
    'invoices': {'url': '/finance/invoices', 'label': '发票管理', 'desc': '应收/应付发票'},
    'reconciliation': {'url': '/finance/reconciliation', 'label': '银行对账', 'desc': '银行流水与账面核对'},
    'approvals': {'url': '/workflow/approvals', 'label': '审批中心', 'desc': '飞书式审批流'},
    'tasks': {'url': '/workflow/tasks', 'label': '任务中心', 'desc': '任务与@提醒'},
    'finance': {'url': '/finance', 'label': '财务总览', 'desc': '科目余额、期间状态、财务 KPI'},
    'vouchers': {'url': '/finance/vouchers', 'label': '凭证管理', 'desc': '录入/审核记账凭证'},
    'ledger': {'url': '/finance', 'label': '总账', 'desc': '会计科目与余额'},
    'edit': {'url': '/edit', 'label': '表格编辑', 'desc': '协同编辑财务明细表'},
    'preview': {'url': '/preview', 'label': '数据预览', 'desc': '查看已导入数据'},
    'dashboard': {'url': '/dashboard', 'label': '审计概览', 'desc': '三阶段审计仪表盘'},
    'analysis': {'url': '/analysis', 'label': '规则检测', 'desc': 'Benford/异常/规则审计'},
    'report': {'url': '/report', 'label': '审计报告', 'desc': '导出 HTML/Excel 报告'},
    'history': {'url': '/history', 'label': '历史记录', 'desc': '审计会话归档'},
    'chat': {'url': '/chat', 'label': '消息协作', 'desc': '飞书式即时消息与文件'},
    'agent': {'url': '/agent', 'label': 'AI Agent', 'desc': '智能体工作台'},
    'profile': {'url': '/profile', 'label': '个人空间', 'desc': '账号、好友、主题设置'},
    'search': {'url': '/search', 'label': '全文检索', 'desc': '搜索知识与历史'},
}


def resolve_page(page: str, query: str = '') -> str:
    key = (page or '').strip().lower()
    info = PAGES.get(key)
    if not info:
        if key.startswith('/'):
            return key
        return '/'
    url = info['url']
    if query:
        sep = '&' if '?' in url else '?'
        url = f'{url}{sep}{query.lstrip("?")}'
    return url


def pages_prompt() -> str:
    lines = ['系统页面（可用 navigate_page 工具跳转）:']
    for key, info in PAGES.items():
        lines.append(f"- {key}: {info['label']} — {info['desc']} ({info['url']})")
    return '\n'.join(lines)
