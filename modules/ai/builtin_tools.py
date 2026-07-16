"""内置审计工具 — Agent 默认可用，覆盖审计系统全部功能。"""
from __future__ import annotations

import json
from typing import Any

# ============================================================
# 工具定义表（供 LLM 理解可用的工具）
# ============================================================

BUILTIN_TOOLS: list[dict] = [
    # ── 数据上传 ──
    {
        'name': 'get_audit_context',
        'description': '获取当前审计数据上下文（行数、风险评分、规则检测结果、金额统计）',
        'parameters': {'type': 'object', 'properties': {}},
        'source': 'builtin',
        'permission': 'read',
    },
    {
        'name': 'import_table_data',
        'description': '导入 JSON 格式的表格数据（用于 OCR 识别后的数据导入）',
        'parameters': {
            'type': 'object',
            'properties': {
                'headers': {'type': 'array', 'items': {'type': 'string'}, 'description': '表头列名列表'},
                'rows': {'type': 'array', 'items': {'type': 'object'}, 'description': '数据行列表'},
            },
            'required': ['headers', 'rows'],
        },
        'source': 'builtin',
        'permission': 'write',
    },
    # ── 表格管理 ──
    {
        'name': 'list_tables',
        'description': '列出所有已加载的数据表，包含表ID、文件名、行列数',
        'parameters': {'type': 'object', 'properties': {}},
        'source': 'builtin',
        'permission': 'read',
    },
    {
        'name': 'switch_table',
        'description': '切换到指定的活动表（切换后会自动重新执行审计分析）',
        'parameters': {
            'type': 'object',
            'properties': {
                'table_id': {'type': 'string', 'description': '要切换到的表ID'},
            },
            'required': ['table_id'],
        },
        'source': 'builtin',
        'permission': 'write',
    },
    {
        'name': 'get_table_data',
        'description': '获取指定表的分页数据，用于查看表格内容',
        'parameters': {
            'type': 'object',
            'properties': {
                'table_id': {'type': 'string', 'description': '表ID，留空则使用当前活动表'},
                'page': {'type': 'integer', 'description': '页码，从1开始，默认1'},
                'per_page': {'type': 'integer', 'description': '每页行数，默认50'},
            },
        },
        'source': 'builtin',
        'permission': 'read',
    },
    {
        'name': 'get_table_summary',
        'description': '获取当前活动表格的摘要信息（文件名、行列数、金额统计、日期范围）',
        'parameters': {'type': 'object', 'properties': {}},
        'source': 'builtin',
        'permission': 'read',
    },
    # ── 表格编辑 ──
    {
        'name': 'update_cell',
        'description': '修改指定单元格的值',
        'parameters': {
            'type': 'object',
            'properties': {
                'table_id': {'type': 'string', 'description': '表ID，留空则使用当前活动表'},
                'row': {'type': 'integer', 'description': '行索引（0-based）'},
                'column': {'type': 'string', 'description': '列名'},
                'value': {'type': 'string', 'description': '新值'},
            },
            'required': ['row', 'column', 'value'],
        },
        'source': 'builtin',
        'permission': 'write',
    },
    {
        'name': 'add_row',
        'description': '向表添加一行新数据',
        'parameters': {
            'type': 'object',
            'properties': {
                'table_id': {'type': 'string', 'description': '表ID，留空则使用当前活动表'},
                'data': {'type': 'object', 'description': '行数据，键为列名，值为内容'},
            },
            'required': ['data'],
        },
        'source': 'builtin',
        'permission': 'write',
    },
    {
        'name': 'delete_row',
        'description': '删除指定行',
        'parameters': {
            'type': 'object',
            'properties': {
                'table_id': {'type': 'string', 'description': '表ID，留空则使用当前活动表'},
                'row_idx': {'type': 'integer', 'description': '行索引（0-based）'},
            },
            'required': ['row_idx'],
        },
        'source': 'builtin',
        'permission': 'danger',
    },
    {
        'name': 'add_column',
        'description': '向表添加一个新列',
        'parameters': {
            'type': 'object',
            'properties': {
                'table_id': {'type': 'string', 'description': '表ID，留空则使用当前活动表'},
                'name': {'type': 'string', 'description': '新列名'},
                'default_value': {'type': 'string', 'description': '默认值，默认为空字符串'},
            },
            'required': ['name'],
        },
        'source': 'builtin',
        'permission': 'write',
    },
    {
        'name': 'delete_column',
        'description': '删除指定列',
        'parameters': {
            'type': 'object',
            'properties': {
                'table_id': {'type': 'string', 'description': '表ID，留空则使用当前活动表'},
                'col_name': {'type': 'string', 'description': '要删除的列名'},
            },
            'required': ['col_name'],
        },
        'source': 'builtin',
        'permission': 'danger',
    },
    {
        'name': 'delete_table',
        'description': '删除一个已加载的数据表',
        'parameters': {
            'type': 'object',
            'properties': {
                'table_id': {'type': 'string', 'description': '要删除的表ID'},
            },
            'required': ['table_id'],
        },
        'source': 'builtin',
        'permission': 'danger',
    },
    # ── 审计分析 ──
    {
        'name': 'run_audit_analysis',
        'description': '运行全部7项审计规则和异常检测（Z-Score + IQR），返回审计结果和风险评分',
        'parameters': {'type': 'object', 'properties': {}},
        'source': 'builtin',
        'permission': 'read',
    },
    {
        'name': 'get_rule_detail',
        'description': '获取某条审计规则的详细检测结果',
        'parameters': {
            'type': 'object',
            'properties': {
                'rule_name': {'type': 'string', 'description': '规则名称，如 duplicate_check, large_amount, abnormal_date, category_anomaly, high_frequency, voucher_gap, balance_anomaly, benford'},
            },
            'required': ['rule_name'],
        },
        'source': 'builtin',
        'permission': 'read',
    },
    # ── 仪表盘 ──
    {
        'name': 'get_dashboard',
        'description': '获取仪表盘完整数据，包含图表数据（金额分布、类别分布、本福特定律、风险分布、时间趋势）',
        'parameters': {'type': 'object', 'properties': {}},
        'source': 'builtin',
        'permission': 'read',
    },
    # ── 三阶段审计 ──
    {
        'name': 'run_risk_assessment',
        'description': '执行三阶段审计第1步：风险评估（财务比率分析、收入趋势、集中度分析）',
        'parameters': {'type': 'object', 'properties': {}},
        'source': 'builtin',
        'permission': 'read',
    },
    {
        'name': 'run_control_testing',
        'description': '执行三阶段审计第2步：控制测试（IT控制、业务流程控制）',
        'parameters': {'type': 'object', 'properties': {}},
        'source': 'builtin',
        'permission': 'read',
    },
    {
        'name': 'run_substantive_procedures',
        'description': '执行三阶段审计第3步：实质性程序（详细测试、分析性复核）',
        'parameters': {
            'type': 'object',
            'properties': {
                'bs_date': {'type': 'string', 'description': '资产负债表日期，格式YYYY-MM-DD，可选'},
            },
        },
        'source': 'builtin',
        'permission': 'read',
    },
    {
        'name': 'run_all_audit_phases',
        'description': '一次性执行全部三阶段审计流程（风险评估 + 控制测试 + 实质性程序）',
        'parameters': {
            'type': 'object',
            'properties': {
                'bs_date': {'type': 'string', 'description': '资产负债表日期，可选'},
            },
        },
        'source': 'builtin',
        'permission': 'read',
    },
    # ── 报告导出 ──
    {
        'name': 'get_score',
        'description': '获取当前审计的综合风险评分（包含总体评分、分项得分、风险等级）',
        'parameters': {'type': 'object', 'properties': {}},
        'source': 'builtin',
        'permission': 'read',
    },
    {
        'name': 'export_report_info',
        'description': '获取可导出的报告信息（报告包含哪些内容、文件类型选项），实际下载需用户在浏览器操作',
        'parameters': {'type': 'object', 'properties': {}},
        'source': 'builtin',
        'permission': 'read',
    },
    # ── 历史记录 ──
    {
        'name': 'list_history',
        'description': '列出已保存的审计历史记录，支持搜索和按类型筛选',
        'parameters': {
            'type': 'object',
            'properties': {
                'q': {'type': 'string', 'description': '搜索关键词，可选'},
                'source_type': {'type': 'string', 'description': '来源类型：file（文件上传）、image（图片识别）、import（导入），可选'},
                'limit': {'type': 'integer', 'description': '返回数量，默认50，最大200'},
            },
        },
        'source': 'builtin',
        'permission': 'read',
    },
    {
        'name': 'load_history',
        'description': '加载一条历史审计记录到当前会话，恢复分析结果',
        'parameters': {
            'type': 'object',
            'properties': {
                'record_id': {'type': 'integer', 'description': '历史记录ID'},
            },
            'required': ['record_id'],
        },
        'source': 'builtin',
        'permission': 'write',
    },
    {
        'name': 'delete_history',
        'description': '删除一条历史记录',
        'parameters': {
            'type': 'object',
            'properties': {
                'record_id': {'type': 'integer', 'description': '历史记录ID'},
            },
            'required': ['record_id'],
        },
        'source': 'builtin',
        'permission': 'danger',
    },
    # ── 协同编辑 ──
    {
        'name': 'create_collab_session',
        'description': '为当前活动表创建一个协同编辑会话，生成分享链接',
        'parameters': {
            'type': 'object',
            'properties': {
                'table_id': {'type': 'string', 'description': '表ID，留空则使用当前活动表'},
            },
        },
        'source': 'builtin',
        'permission': 'write',
    },
    # ── 消息通讯 ──
    {
        'name': 'list_conversations',
        'description': '获取当前用户的会话列表（包含未读数和最后一条消息）',
        'parameters': {'type': 'object', 'properties': {}},
        'source': 'builtin',
        'permission': 'read',
    },
    {
        'name': 'get_unread_counts',
        'description': '获取未读消息和通知的总数',
        'parameters': {'type': 'object', 'properties': {}},
        'source': 'builtin',
        'permission': 'read',
    },
    # ── 用户与检索 ──
    {
        'name': 'search_knowledge',
        'description': '全文检索审计知识库与历史记录',
        'parameters': {
            'type': 'object',
            'properties': {
                'query': {'type': 'string', 'description': '搜索关键词'},
            },
            'required': ['query'],
        },
        'source': 'builtin',
        'permission': 'read',
    },
    {
        'name': 'search_users',
        'description': '搜索系统中的用户（用于发起会话、邀请协同等）',
        'parameters': {
            'type': 'object',
            'properties': {
                'q': {'type': 'string', 'description': '用户名搜索关键词'},
            },
            'required': ['q'],
        },
        'source': 'builtin',
        'permission': 'read',
    },
    {
        'name': 'get_my_profile',
        'description': '获取当前登录用户的个人资料和统计数据',
        'parameters': {'type': 'object', 'properties': {}},
        'source': 'builtin',
        'permission': 'read',
    },
    # ── 导航辅助 ──
    {
        'name': 'navigate_page',
        'description': '跳转到系统页面（财务/审计/协作）。用户说「打开/去/跳转」某功能时使用。',
        'parameters': {
            'type': 'object',
            'properties': {
                'page': {
                    'type': 'string',
                    'description': '页面标识: finance, vouchers, payables, receivables, invoices, reconciliation, approvals, tasks, dashboard, analysis, report, edit, chat, agent, history, home 等',
                },
                'reason': {'type': 'string', 'description': '跳转原因'},
                'query': {'type': 'string', 'description': '可选 URL 查询参数'},
            },
            'required': ['page'],
        },
        'source': 'builtin',
        'permission': 'read',
    },
    {
        'name': 'navigate_to',
        'description': '同 navigate_page，跳转到系统页面。',
        'parameters': {
            'type': 'object',
            'properties': {
                'page': {'type': 'string', 'description': '目标页面标识'},
                'reason': {'type': 'string'},
            },
            'required': ['page'],
        },
        'source': 'builtin',
        'permission': 'read',
    },
    {
        'name': 'get_finance_overview',
        'description': '获取财务总览：科目余额、期间、凭证统计',
        'parameters': {'type': 'object', 'properties': {}},
        'source': 'builtin',
        'permission': 'read',
    },
    {
        'name': 'list_vouchers',
        'description': '列出最近的记账凭证',
        'parameters': {
            'type': 'object',
            'properties': {
                'limit': {'type': 'integer'},
                'status': {'type': 'string'},
            },
        },
        'source': 'builtin',
        'permission': 'read',
    },
    {
        'name': 'list_invoices',
        'description': '列出应收/应付发票',
        'parameters': {
            'type': 'object',
            'properties': {
                'invoice_type': {'type': 'string', 'description': 'ar 应收 或 ap 应付'},
            },
        },
        'source': 'builtin',
        'permission': 'read',
    },
]


# ============================================================
# 工具执行函数
# ============================================================

def run_builtin(name: str, args: dict, context: dict | None = None) -> Any | None:
    """根据工具名分发到具体的执行函数。返回 None 表示不是内置工具。"""
    ctx = context or {}
    user_id = ctx.get('user_id')

    handlers = {
        # 数据
        'get_audit_context': lambda: _audit_context(),
        'import_table_data': lambda: _import_table(args),
        # 表格
        'list_tables': lambda: _list_tables(),
        'switch_table': lambda: _switch_table(args.get('table_id', '')),
        'get_table_data': lambda: _get_table_data(args),
        'get_table_summary': lambda: _table_summary(),
        # 编辑
        'update_cell': lambda: _update_cell(args),
        'add_row': lambda: _add_row(args),
        'delete_row': lambda: _delete_row(args),
        'add_column': lambda: _add_column(args),
        'delete_column': lambda: _delete_column(args),
        'delete_table': lambda: _delete_table(args.get('table_id', '')),
        # 分析
        'run_audit_analysis': lambda: _run_analysis(),
        'get_rule_detail': lambda: _rule_detail(args.get('rule_name', '')),
        # 仪表盘
        'get_dashboard': lambda: _get_dashboard(),
        # 三阶段
        'run_risk_assessment': lambda: _run_phase('risk_assessment'),
        'run_control_testing': lambda: _run_phase('control_testing'),
        'run_substantive_procedures': lambda: _run_substantive(args),
        'run_all_audit_phases': lambda: _run_all_phases(args),
        # 报告
        'get_score': lambda: _get_score(),
        'export_report_info': lambda: _export_info(),
        # 历史
        'list_history': lambda: _list_history(args, user_id),
        'load_history': lambda: _load_history(args, user_id),
        'delete_history': lambda: _delete_history(args, user_id),
        # 协同
        'create_collab_session': lambda: _create_collab(args, user_id),
        # 通讯
        'list_conversations': lambda: _list_conversations(user_id),
        'get_unread_counts': lambda: _unread_counts(user_id),
        # 检索
        'search_knowledge': lambda: _search(args.get('query', ''), user_id),
        'search_users': lambda: _search_users(args.get('q', ''), user_id),
        # 用户
        'get_my_profile': lambda: _my_profile(user_id),
        # 导航 / 财务
        'navigate_to': lambda: _navigate(args if isinstance(args, dict) else {'page': str(args)}),
        'navigate_page': lambda: _navigate(args if isinstance(args, dict) else {'page': str(args)}),
        'get_finance_overview': lambda: _finance_overview(user_id),
        'list_vouchers': lambda: _list_vouchers(user_id, args),
        'list_invoices': lambda: _list_invoices(user_id, args),
    }

    handler = handlers.get(name)
    if handler:
        try:
            return handler()
        except Exception as e:
            return {'error': str(e), 'tool': name}
    return None


# ============================================================
# 工具实现
# ============================================================

def _audit_context() -> dict:
    try:
        from app import _analysis_cache, _build_ai_context
        score = _analysis_cache.get('score', {})
        return {
            'context_text': _build_ai_context(),
            'score': score,
            'audit_rules_count': len(_analysis_cache.get('audit_results', [])),
            'has_data': bool(_analysis_cache),
        }
    except Exception:
        return {'context_text': '', 'note': '暂无审计数据，请先上传文件'}


def _import_table(args: dict) -> dict:
    headers = args.get('headers', [])
    rows = args.get('rows', [])
    if not headers:
        return {'error': '缺少表头数据'}
    from modules.data_processor import import_table_data
    result = import_table_data(headers, rows)
    if result.get('success'):
        _run_auto_analysis(result)
    return result


def _list_tables() -> dict:
    from modules.data_processor import get_tables, get_active_table_id
    return {
        'tables': get_tables(),
        'active_table_id': get_active_table_id(),
        'count': len(get_tables()),
    }


def _switch_table(table_id: str) -> dict:
    if not table_id:
        return {'error': '请指定 table_id'}
    from modules.data_processor import set_active_table, get_tables
    ok = set_active_table(table_id)
    if ok:
        from app import _analysis_cache
        try:
            from modules.data_processor import get_current_data
            from modules.audit_rules import run_all_rules, get_rule_summary
            from modules.anomaly_detector import run_all_detectors
            from modules.report_generator import calculate_overall_score
            df = get_current_data()
            audit_results = run_all_rules(df)
            anomaly_results = run_all_detectors(df)
            score = calculate_overall_score(audit_results, anomaly_results)
            from modules.data_processor import get_active_table
            t = get_active_table()
            _analysis_cache.update({
                'audit_results': audit_results,
                'audit_summary': get_rule_summary(audit_results),
                'anomaly_results': anomaly_results,
                'score': score,
                'preview_data': t['preview_data'] if t else [],
                'preview_columns': t['preview_columns'] if t else [],
            })
        except Exception:
            pass
        return {'success': True, 'active_table_id': table_id, 'tables': get_tables()}
    return {'error': '表不存在'}


def _get_table_data(args: dict) -> dict:
    from modules.data_processor import get_active_table_id, get_table_data
    tid = args.get('table_id') or get_active_table_id()
    if not tid:
        return {'error': '没有活动表'}
    return get_table_data(tid, args.get('page', 1), args.get('per_page', 50))


def _table_summary() -> dict:
    from modules.data_processor import get_current_summary, get_active_table
    summary = get_current_summary()
    table = get_active_table()
    return {
        'filename': table.get('filename') if table else None,
        'summary': summary,
        'note': '暂无活动表格' if not table else None,
    }


def _update_cell(args: dict) -> dict:
    from modules.data_processor import get_active_table_id, update_cell
    tid = args.get('table_id') or get_active_table_id()
    return update_cell(tid, int(args['row']), args['column'], args.get('value', ''))


def _add_row(args: dict) -> dict:
    from modules.data_processor import get_active_table_id, add_row
    tid = args.get('table_id') or get_active_table_id()
    return add_row(tid, args.get('data', {}))


def _delete_row(args: dict) -> dict:
    from modules.data_processor import get_active_table_id, delete_row
    tid = args.get('table_id') or get_active_table_id()
    return delete_row(tid, int(args['row_idx']))


def _add_column(args: dict) -> dict:
    from modules.data_processor import get_active_table_id, add_column
    tid = args.get('table_id') or get_active_table_id()
    return add_column(tid, args['name'], args.get('default_value', ''))


def _delete_column(args: dict) -> dict:
    from modules.data_processor import get_active_table_id, delete_column
    tid = args.get('table_id') or get_active_table_id()
    return delete_column(tid, args['col_name'])


def _delete_table(table_id: str) -> dict:
    from modules.data_processor import delete_table
    return delete_table(table_id)


def _run_analysis() -> dict:
    from modules.data_processor import get_current_data
    from modules.audit_rules import run_all_rules, get_rule_summary
    from modules.anomaly_detector import run_all_detectors
    from modules.report_generator import calculate_overall_score
    df = get_current_data()
    if df is None:
        return {'error': '未加载数据，请先上传文件'}
    audit_results = run_all_rules(df)
    anomaly_results = run_all_detectors(df)
    score = calculate_overall_score(audit_results, anomaly_results)
    _sync_cache(audit_results, anomaly_results, score)
    return {
        'audit_summary': get_rule_summary(audit_results),
        'score': score,
        'rules_checked': len(audit_results),
        'anomalies_found': anomaly_results.get('summary', {}).get('total_anomalies_found', 0),
    }


def _rule_detail(rule_name: str) -> dict:
    from app import _analysis_cache
    for r in _analysis_cache.get('audit_results', []):
        if r.get('rule') == rule_name:
            return {'rule': r}
    return {'error': f'未找到规则: {rule_name}'}


def _get_dashboard() -> dict:
    from modules.data_processor import get_current_data, get_current_summary
    df = get_current_data()
    if df is None:
        return {'error': '未加载数据'}
    from app import _analysis_cache
    summary = get_current_summary()
    score = _analysis_cache.get('score', {})
    audit_summary = _analysis_cache.get('audit_summary', {})
    # 提取关键图表数据摘要
    charts_summary = {}
    amount_col = summary.get('amount_stats', {}).get('column') if summary else None
    if amount_col:
        import pandas as pd
        amounts = pd.to_numeric(df[amount_col], errors='coerce').dropna()
        if len(amounts) > 0:
            charts_summary['amount'] = {
                'total': float(amounts.sum()), 'mean': float(amounts.mean()),
                'max': float(amounts.max()), 'min': float(amounts.min()),
                'count': int(len(amounts)),
            }
    return {
        'summary': summary,
        'score': score,
        'audit_summary': audit_summary,
        'charts_summary': charts_summary,
    }


def _run_phase(phase: str) -> dict:
    from modules.data_processor import get_current_data
    df = get_current_data()
    if df is None:
        return {'error': '未加载数据，请先上传文件'}
    if phase == 'risk_assessment':
        from modules.risk_assessment import run_risk_assessment
        result = run_risk_assessment(df)
        return {'phase': 1, 'name': '风险评估', 'findings_count': len(result.get('findings', [])), 'summary': result.get('summary', {})}
    elif phase == 'control_testing':
        from modules.control_testing import run_control_tests
        result = run_control_tests(df)
        return {'phase': 2, 'name': '控制测试', 'findings_count': len(result.get('findings', [])), 'summary': result.get('summary', {})}
    return {'error': f'未知阶段: {phase}'}


def _run_substantive(args: dict) -> dict:
    from modules.data_processor import get_current_data
    df = get_current_data()
    if df is None:
        return {'error': '未加载数据，请先上传文件'}
    from modules.substantive_procedures import run_substantive_procedures
    result = run_substantive_procedures(df, bs_date=args.get('bs_date'))
    return {'phase': 3, 'name': '实质性程序', 'findings_count': result.get('total_findings', 0), 'summary': result.get('summary', {})}


def _run_all_phases(args: dict) -> dict:
    from modules.data_processor import get_current_data
    df = get_current_data()
    if df is None:
        return {'error': '未加载数据，请先上传文件'}
    from modules.risk_assessment import run_risk_assessment
    from modules.control_testing import run_control_tests
    from modules.substantive_procedures import run_substantive_procedures
    errors = []
    results = {}
    total_findings = 0
    try:
        r1 = run_risk_assessment(df)
        results['phase1'] = {'findings': len(r1.get('findings', [])), 'summary': r1.get('summary', {})}
        total_findings += len(r1.get('findings', []))
    except Exception as e:
        errors.append(f'阶段1失败: {e}')
    try:
        r2 = run_control_tests(df)
        results['phase2'] = {'findings': len(r2.get('findings', [])), 'summary': r2.get('summary', {})}
        total_findings += len(r2.get('findings', []))
    except Exception as e:
        errors.append(f'阶段2失败: {e}')
    try:
        r3 = run_substantive_procedures(df, bs_date=args.get('bs_date'))
        results['phase3'] = {'findings': r3.get('total_findings', 0), 'summary': r3.get('summary', {})}
        total_findings += r3.get('total_findings', 0)
    except Exception as e:
        errors.append(f'阶段3失败: {e}')
    return {'success': True, 'results': results, 'total_findings': total_findings, 'errors': errors if errors else None}


def _get_score() -> dict:
    from app import _analysis_cache
    score = _analysis_cache.get('score', {})
    if not score:
        return {'note': '暂无评分数据，请先运行分析'}
    return {'score': score}


def _export_info() -> dict:
    from app import _analysis_cache
    if not _analysis_cache:
        return {'error': '无分析结果，请先上传数据并分析'}
    return {
        'available_formats': ['html', 'excel'],
        'html_endpoint': '/api/export/html',
        'excel_endpoint': '/api/export/excel',
        'note': '导出文件将在浏览器中自动下载。请在 Agent 工作台页面点击下方链接下载，或告诉我为你生成导出链接。',
    }


def _list_history(args: dict, user_id: int | None) -> dict:
    from modules.database import list_history
    records = list_history(
        limit=min(int(args.get('limit', 50)), 200),
        user_id=user_id,
        q=args.get('q'),
        source_type=args.get('source_type'),
    )
    return {'records': records, 'total': len(records)}


def _load_history(args: dict, user_id: int | None) -> dict:
    from modules.database import get_history_record
    record = get_history_record(int(args['record_id']), user_id=user_id)
    if not record:
        return {'error': '历史记录不存在'}
    from modules.data_processor import restore_table_from_df
    from modules.audit_rules import get_rule_summary
    table_id = restore_table_from_df(record['df'], record['filename'] or record['title'])
    from app import _analysis_cache as cache
    cache.update({
        'audit_results': record['audit_results'],
        'audit_summary': get_rule_summary(record['audit_results']),
        'anomaly_results': record['anomaly_results'],
        'score': record['score'],
        'preview_data': record['df'].head(100).fillna('').to_dict(orient='records'),
        'preview_columns': list(record['df'].columns),
    })
    return {
        'success': True,
        'table_id': table_id,
        'title': record['title'],
        'row_count': record['row_count'],
        'score': record['score'],
    }


def _delete_history(args: dict, user_id: int | None) -> dict:
    from modules.database import delete_history_record
    ok = delete_history_record(int(args['record_id']), user_id=user_id)
    return {'success': ok, 'error': None if ok else '记录不存在或无权限'}


def _create_collab(args: dict, user_id: int | None) -> dict:
    from modules.collab import create_session_from_table
    return create_session_from_table(user_id or 0, args.get('table_id', ''))


def _list_conversations(user_id: int | None) -> dict:
    if not user_id:
        return {'error': '未登录'}
    from modules.database import list_conversations
    convs = list_conversations(user_id)
    return {'conversations': convs, 'count': len(convs)}


def _unread_counts(user_id: int | None) -> dict:
    if not user_id:
        return {'unread_messages': 0, 'unread_notifications': 0}
    from modules.database import get_unread_message_count, get_unread_notification_count
    return {
        'unread_messages': get_unread_message_count(user_id),
        'unread_notifications': get_unread_notification_count(user_id),
    }


def _search(query: str, user_id: int | None) -> dict:
    if not query:
        return {'results': [], 'error': '缺少 query 参数'}
    from modules.search_engine import search
    data = search(query, user_id=user_id)
    return {'query': query, 'results': data.get('results', [])[:8]}


def _search_users(q: str, user_id: int | None) -> dict:
    if not q:
        return {'users': [], 'error': '缺少搜索关键词'}
    from modules.database import search_users as db_search_users
    users = db_search_users(q, exclude_id=user_id)
    return {'users': users, 'count': len(users)}


def _my_profile(user_id: int | None) -> dict:
    if not user_id:
        return {'error': '未登录'}
    from modules.database import get_user_by_id, get_user_stats
    user = get_user_by_id(user_id)
    stats = get_user_stats(user_id)
    return {'user': {'id': user['id'], 'username': user['username'], 'created_at': user.get('created_at')}, 'stats': stats}


def _navigate(page_or_args) -> dict:
    """跳转页面，返回前端可执行的 navigate action。"""
    from modules.ai.page_registry import resolve_page, PAGES
    if isinstance(page_or_args, dict):
        page = (page_or_args.get('page') or '').strip().lower()
        reason = (page_or_args.get('reason') or '').strip()
        query = (page_or_args.get('query') or '').strip()
    else:
        page = str(page_or_args or '').strip().lower()
        reason = ''
        query = ''
    url = resolve_page(page, query)
    label = PAGES.get(page, {}).get('label', page)
    return {
        'action': 'navigate',
        'url': url,
        'page': page,
        'name': label,
        'reason': reason or f'正在为您打开「{label}」',
        'delay_ms': 1000,
        'message': f'点击前往「{label}」: {url}',
    }


def _finance_overview(user_id: int | None) -> dict:
    if not user_id:
        return {'error': '未登录'}
    try:
        from modules.database import get_finance_overview, ensure_finance_seed
        ensure_finance_seed(user_id)
        return get_finance_overview(user_id)
    except Exception as e:
        return {'error': str(e)}


def _list_vouchers(user_id: int | None, args: dict) -> dict:
    if not user_id:
        return {'vouchers': [], 'error': '未登录'}
    try:
        from modules.database import list_fin_vouchers
        return {'vouchers': list_fin_vouchers(user_id, limit=int(args.get('limit') or 10), status=args.get('status'))}
    except Exception as e:
        return {'vouchers': [], 'error': str(e)}


def _list_invoices(user_id: int | None, args: dict) -> dict:
    if not user_id:
        return {'invoices': [], 'error': '未登录'}
    try:
        from modules.enterprise_db import list_invoices
        return {'invoices': list_invoices(user_id, invoice_type=args.get('invoice_type'), limit=15)}
    except Exception as e:
        return {'invoices': [], 'error': str(e)}


# ============================================================
# 辅助函数
# ============================================================

def _sync_cache(audit_results, anomaly_results, score):
    """同步分析结果到全局缓存"""
    from app import _analysis_cache
    from modules.audit_rules import get_rule_summary
    from modules.data_processor import get_active_table
    t = get_active_table()
    _analysis_cache.update({
        'audit_results': audit_results,
        'audit_summary': get_rule_summary(audit_results),
        'anomaly_results': anomaly_results,
        'score': score,
        'preview_data': t['preview_data'] if t else [],
        'preview_columns': t['preview_columns'] if t else [],
    })


def _run_auto_analysis(result: dict):
    """上传/导入后自动运行审计分析"""
    from app import _analysis_cache
    from modules.data_processor import get_current_data, get_current_summary
    from modules.audit_rules import run_all_rules, get_rule_summary
    from modules.anomaly_detector import run_all_detectors
    from modules.report_generator import calculate_overall_score
    from modules.database import save_history_record
    try:
        df = get_current_data()
        audit_results = run_all_rules(df)
        audit_summary = get_rule_summary(audit_results)
        anomaly_results = run_all_detectors(df)
        summary = get_current_summary() or {}
        score = calculate_overall_score(audit_results, anomaly_results)
        t = get_active_table()
        import app as app_module
        _analysis_cache.update({
            'audit_results': audit_results, 'audit_summary': audit_summary,
            'anomaly_results': anomaly_results, 'score': score,
            'preview_data': t['preview_data'] if t else [],
            'preview_columns': t['preview_columns'] if t else [],
        })
        from flask import session
        save_history_record(
            title=result.get('filename', '导入数据'),
            source_type='import',
            filename=result.get('filename', ''),
            df=df,
            summary=summary,
            audit_results=audit_results,
            anomaly_results=anomaly_results,
            score=score,
            user_id=session.get('user_id'),
        )
    except Exception as e:
        pass


# 获取活动表ID的辅助函数
def get_active_table_id():
    from modules.data_processor import get_active_table_id
    return get_active_table_id()


def get_active_table():
    from modules.data_processor import get_active_table
    return get_active_table()
