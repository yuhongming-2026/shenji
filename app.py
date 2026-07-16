"""
智能财务系统 - Flask 主应用
核算 · 审计 · 协作 · AI Agent
"""
from __future__ import annotations

import os
import io
import json
import base64
from datetime import datetime, timedelta

import pandas as pd
import numpy as np

from flask import (Flask, render_template, request, jsonify,
                   session, send_file, send_from_directory, redirect, url_for, g)
from flask.json.provider import DefaultJSONProvider
from flask_compress import Compress

from modules.data_processor import (
    process_upload, process_image_upload, import_table_data,
    restore_table_from_df, persist_table, restore_working_tables_for_user,
    bind_table_history,
    get_current_data, get_current_summary,
    get_tables, get_table, get_active_table,
    set_active_table, get_active_table_id,
    get_table_data, update_cell, add_row, delete_row,
    add_column, delete_column, delete_table,
)

from modules.audit_rules import run_all_rules, get_rule_summary
from modules.anomaly_detector import run_all_detectors
from modules.report_generator import (calculate_overall_score,
                                       generate_html_report,
                                       export_to_excel,
                                       calculate_overall_score_v2,
                                       generate_html_report_v2,
                                       export_to_excel_v2)
from modules.database import (init_db, save_history_record, list_history,
                               get_history_record, delete_history_record)
from modules.risk_assessment import run_risk_assessment
from modules.control_testing import run_control_tests
from modules.substantive_procedures import run_substantive_procedures
from modules.auth import (
    REMEMBER_COOKIE, REMEMBER_DAYS,
    register_user, authenticate_user, login_user, logout_user,
    restore_user_from_remember, get_current_user,
)

app = Flask(__name__)

_secret_file = os.path.join(os.path.dirname(__file__), 'data', '.secret_key')
os.makedirs(os.path.dirname(_secret_file), exist_ok=True)
if os.path.exists(_secret_file):
    with open(_secret_file) as f:
        app.secret_key = f.read().strip()
else:
    app.secret_key = os.urandom(32).hex()
    with open(_secret_file, 'w') as f:
        f.write(app.secret_key)

app.config['MAX_CONTENT_LENGTH'] = 100 * 1024 * 1024  # 100MB
app.config['PERMANENT_SESSION_LIFETIME'] = timedelta(days=REMEMBER_DAYS)
app.config['SESSION_COOKIE_HTTPONLY'] = True
app.config['SESSION_COOKIE_SAMESITE'] = 'Lax'
app.config['COMPRESS_LEVEL'] = 6
app.config['COMPRESS_MIN_SIZE'] = 256


class NumpyJSONProvider(DefaultJSONProvider):
    def default(self, obj):
        if isinstance(obj, np.integer):
            return int(obj)
        if isinstance(obj, np.floating):
            return float(obj)
        if isinstance(obj, np.ndarray):
            return obj.tolist()
        if isinstance(obj, np.bool_):
            return bool(obj)
        return super().default(obj)


app.json = NumpyJSONProvider(app)
Compress(app)

os.makedirs(os.path.join(os.path.dirname(__file__), 'uploads'), exist_ok=True)
os.makedirs(os.path.join(os.path.dirname(__file__), 'data', 'models'), exist_ok=True)
init_db()
try:
    from modules.enterprise_db import ensure_enterprise_schema
    ensure_enterprise_schema()
except Exception:
    pass

# AI 仅通过云端 / OpenAI 兼容 API 接入
AI_MODEL = 'api'

try:
    from modules.ai.registry import reload_extensions
    reload_extensions()
except Exception as exc:
    print(f'[Agent] 扩展扫描跳过: {exc}', flush=True)


@app.after_request
def _add_cache_headers(response):
    if request.path.startswith('/static/'):
        response.cache_control.max_age = 86400 if '/vendor/' in request.path else 3600
        response.cache_control.public = True
    elif response.content_type and 'text/html' in response.content_type:
        response.cache_control.no_cache = True
        response.cache_control.no_store = True
        response.headers['Pragma'] = 'no-cache'
    return response


# 当前会话的分析结果缓存（审计规则、异常检测、评分等），加载历史记录时一并恢复
_analysis_cache = {}

# 前端资源版本：每次发版递增，避免老账号浏览器缓存旧 UI
UI_BUILD = '20260716d'


@app.context_processor
def inject_ui_build():
    return {'ui_build': UI_BUILD}

_PUBLIC_PATHS = {
    '/login', '/api/auth/login', '/api/auth/register', '/api/auth/roles',
    '/favicon.ico', '/manifest.webmanifest', '/sw.js',
}


@app.context_processor
def inject_user_ui():
    user = g.get('current_user')
    if not user:
        return {}
    from modules.roles import get_user_features, get_role_label, parse_preferences, get_user_company
    prefs = parse_preferences(user.get('preferences'))
    return {
        'user_theme': user.get('theme') or 'default',
        'user_page_style': user.get('page_style') or 'classic',
        'user_role_label': get_role_label(user.get('role')),
        'user_features': get_user_features(user),
        'user_accent': prefs.get('accent_color'),
        'user_company': get_user_company(user),
    }


def _uid() -> int | None:
    return session.get('user_id')


def _safe_reply(result: dict) -> str:
    """安全提取 Agent 回复文本。"""
    reply = result.get('reply', '') if isinstance(result, dict) else str(result)
    if not isinstance(reply, str):
        reply = str(reply)
    return reply.encode('utf-8', errors='replace').decode('utf-8')


@app.before_request
def _load_current_user():
    """每个请求前：恢复登录态，未登录则跳转登录页（API 返回 401）"""
    g.current_user = get_current_user()
    if not g.current_user:
        token = request.cookies.get(REMEMBER_COOKIE)
        if restore_user_from_remember(token):
            g.current_user = get_current_user()

    path = request.path
    if path.startswith('/static') or path in _PUBLIC_PATHS:
        return
    if not g.current_user:
        if path.startswith('/api/'):
            return jsonify({'success': False, 'error': '请先登录', 'login_required': True}), 401
        return redirect(url_for('login_page', next=path))


# ============================================================
# 认证
# ============================================================

@app.route('/favicon.ico')
def favicon():
    return send_file(
        os.path.join(app.root_path, 'static', 'favicon.svg'),
        mimetype='image/svg+xml',
        max_age=86400,
    )


@app.route('/manifest.webmanifest')
def web_manifest():
    resp = send_from_directory(
        os.path.join(app.root_path, 'static'),
        'manifest.webmanifest',
        mimetype='application/manifest+json',
    )
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.route('/sw.js')
def service_worker():
    """PWA Service Worker 必须挂在站点根路径，才能覆盖全站 scope。"""
    resp = send_from_directory(
        os.path.join(app.root_path, 'static'),
        'sw.js',
        mimetype='application/javascript',
    )
    resp.headers['Service-Worker-Allowed'] = '/'
    resp.headers['Cache-Control'] = 'no-cache'
    return resp


@app.route('/login')
def login_page():
    if g.current_user:
        return redirect(request.args.get('next') or url_for('index'))
    from modules.roles import ROLES, THEMES, PAGE_STYLES, ALL_FEATURES, CUSTOMIZABLE_ROLES, PROFESSIONAL_ROLES, ROLE_HINTS, ROLE_DEFAULTS
    return render_template(
        'login.html',
        next_url=request.args.get('next', '/'),
        roles=ROLES,
        themes=THEMES,
        page_styles=PAGE_STYLES,
        features=ALL_FEATURES,
        customizable_roles=CUSTOMIZABLE_ROLES,
        professional_roles=PROFESSIONAL_ROLES,
        role_hints=ROLE_HINTS,
        role_defaults={k: v['features'] for k, v in ROLE_DEFAULTS.items()},
    )


@app.route('/api/auth/login', methods=['POST'])
def api_auth_login():
    data = request.get_json(silent=True) or {}
    ok, msg, user = authenticate_user(data.get('username', ''), data.get('password', ''))
    if not ok or not user:
        return jsonify({'success': False, 'error': msg})
    remember = data.get('remember', True)
    token = login_user(user, remember=remember)
    resp = jsonify({'success': True, 'redirect': data.get('next') or request.args.get('next') or '/'})
    if token:
        resp.set_cookie(
            REMEMBER_COOKIE, token, max_age=REMEMBER_DAYS * 86400,
            httponly=True, samesite='Lax',
        )
    return resp


@app.route('/api/auth/roles')
def api_auth_roles():
    """注册页：角色、主题、功能选项"""
    from modules.roles import ROLES, THEMES, PAGE_STYLES, ALL_FEATURES, CUSTOMIZABLE_ROLES
    return jsonify({
        'success': True,
        'roles': ROLES,
        'themes': THEMES,
        'page_styles': PAGE_STYLES,
        'features': ALL_FEATURES,
        'customizable_roles': CUSTOMIZABLE_ROLES,
    })


@app.route('/api/auth/register', methods=['POST'])
def api_auth_register():
    data = request.get_json(silent=True) or {}
    profile = {
        'role': data.get('role'),
        'theme': data.get('theme'),
        'page_style': data.get('page_style'),
        'features': data.get('features'),
        'accent_color': data.get('accent_color'),
        'company': data.get('company'),
    }
    ok, msg, user_id = register_user(
        data.get('username', ''),
        data.get('password', ''),
        profile=profile,
    )
    if not ok or not user_id:
        return jsonify({'success': False, 'error': msg})
    from modules.database import get_user_by_id
    user = get_user_by_id(user_id)
    remember = data.get('remember', True)
    token = login_user(user, remember=remember)
    resp = jsonify({'success': True, 'redirect': '/'})
    if token:
        resp.set_cookie(
            REMEMBER_COOKIE, token, max_age=REMEMBER_DAYS * 86400,
            httponly=True, samesite='Lax',
        )
    return resp


@app.route('/logout')
def logout_page():
    global _analysis_cache, _ai_conversations
    token = request.cookies.get(REMEMBER_COOKIE)
    logout_user(token)
    # 清空所有内存数据
    _analysis_cache.clear()
    _ai_conversations.clear()
    from modules.data_processor import clear_all_tables
    clear_all_tables()
    resp = redirect(url_for('login_page'))
    resp.set_cookie(REMEMBER_COOKIE, '', max_age=0)
    return resp


# ============================================================
# 页面路由
# ============================================================

@app.route('/')
def index():
    return render_template('index.html')


@app.route('/edit')
def edit_page():
    """电子表格编辑器（支持 ?collab=token 协同模式）"""
    collab_token = request.args.get('collab')
    if collab_token:
        return render_template('edit.html', collab_token=collab_token, ui_build=UI_BUILD)
    uid = _uid()
    if uid:
        # 强制从 SQLite 覆盖内存，保证协同写回后普通编辑看到最新数据
        restore_working_tables_for_user(uid, force=True)
    if get_active_table() is None:
        return redirect(url_for('index'))
    return render_template('edit.html', collab_token=None, ui_build=UI_BUILD)


@app.route('/finance')
def finance_page():
    return render_template('finance.html')


@app.route('/finance/vouchers')
def vouchers_page():
    return render_template('vouchers.html')


@app.route('/finance/receivables')
def receivables_page():
    return render_template('finance_receivables.html')


@app.route('/finance/payables')
def payables_page():
    return render_template('finance_payables.html')


@app.route('/finance/invoices')
def invoices_page():
    return render_template('finance_invoices.html')


@app.route('/finance/reconciliation')
def reconciliation_page():
    return render_template('finance_reconciliation.html')


@app.route('/workflow/approvals')
def approvals_page():
    return render_template('workflow_approvals.html')


@app.route('/workflow/tasks')
def tasks_page():
    return render_template('workflow_tasks.html')


@app.route('/dashboard')
def dashboard_page():
    if get_active_table() is None:
        return redirect(url_for('index'))
    return render_template('dashboard.html')


@app.route('/preview')
def preview_page():
    if get_active_table() is None:
        return redirect(url_for('index'))
    return render_template('preview.html')


@app.route('/analysis')
def analysis_page():
    if get_active_table() is None:
        return redirect(url_for('index'))
    return render_template('analysis.html')


@app.route('/report')
def report_page():
    global _analysis_cache
    if not _analysis_cache:
        return redirect(url_for('analysis_page'))
    return render_template('report.html')


@app.route('/history')
def history_page():
    """历史记录页面：展示已保存的审计会话，支持搜索与重新加载"""
    return render_template('history.html')


@app.route('/profile')
def profile_page():
    return render_template('profile.html')


@app.route('/chat')
def chat_page():
    return render_template('chat.html')


@app.route('/agent')
def agent_page():
    return render_template('agent.html')


@app.route('/models')
def models_page():
    """AI 模型可视化管理页面。"""
    return render_template('models.html')


@app.route('/agent/develop')
def agent_develop_page():
    """Agent 扩展开发文档页"""
    readme_path = os.path.join(app.root_path, 'extensions', 'README.md')
    content = ''
    if os.path.isfile(readme_path):
        with open(readme_path, encoding='utf-8') as f:
            content = f.read()
    return render_template('agent_develop.html', readme_content=content)


@app.route('/search')
def search_page():
    """站内搜索：开源 SQLite FTS5 全文检索（无第三方搜索 API）。"""
    from modules.search_engine import search

    query = (request.args.get('q') or '').strip()
    if not query:
        return redirect(url_for('index'))

    from modules.search_engine import refresh_dynamic_index
    try:
        refresh_dynamic_index(user_id=_uid())
    except Exception:
        pass

    data = search(query, user_id=_uid())
    return render_template(
        'search.html',
        query=query,
        results=data.get('results') or [],
        search_ok=data.get('success', False),
        search_error=data.get('error'),
        search_engine=data.get('engine', 'SQLite FTS5'),
        search_note=data.get('engine_note', ''),
    )


@app.route('/api/search')
def api_search():
    """搜索 API（JSON）。"""
    from modules.search_engine import search

    query = (request.args.get('q') or '').strip()
    if not query:
        return jsonify({'success': False, 'error': '缺少参数 q', 'results': []})
    data = search(query, user_id=_uid())
    return jsonify(data)


# ============================================================
# API - 多文件上传
# ============================================================

@app.route('/api/upload', methods=['POST'])
def api_upload():
    """上传 CSV/Excel → 自动审计 → 写入历史记录"""
    global _analysis_cache

    files = request.files.getlist('files')
    if not files or all(f.filename == '' for f in files):
        # 兼容单文件上传
        if 'file' in request.files:
            files = [request.files['file']]
        else:
            return jsonify({'success': False, 'error': '未选择文件'})

    results = []
    errors = []
    for file in files:
        if file.filename == '':
            continue
        result = process_upload(file)
        if result['success']:
            results.append(result)
        else:
            errors.append({'filename': file.filename, 'error': result['error']})

    if not results and errors:
        return jsonify({'success': False, 'error': errors[0]['error'], 'errors': errors})

    # 用第一个成功的表做自动审计分析
    first = results[0]
    try:
        df = get_current_data()
        audit_results = run_all_rules(df)
        audit_summary = get_rule_summary(audit_results)
        anomaly_results = run_all_detectors(df)
        summary = get_current_summary() or {}
        score = calculate_overall_score(audit_results, anomaly_results)

        _analysis_cache = {
            'audit_results': audit_results,
            'audit_summary': audit_summary,
            'anomaly_results': anomaly_results,
            'score': score,
            'preview_data': first.get('preview_data', []),
            'preview_columns': first.get('preview_columns', []),
            'dashboard_charts': _build_dashboard_charts(df, summary, audit_results, audit_summary),
        }

        first['audit_summary'] = audit_summary
        first['score'] = score

        try:
            record_id = save_history_record(
                title=first.get('filename', '上传数据'),
                source_type='file',
                filename=first.get('filename', ''),
                df=df,
                summary=summary,
                audit_results=audit_results,
                anomaly_results=anomaly_results,
                score=score,
                user_id=_uid(),
            )
            first['history_id'] = record_id
        except Exception as e:
            first['history_save_error'] = str(e)

        try:
            from modules.search_engine import refresh_dynamic_index
            refresh_dynamic_index(user_id=_uid())
        except Exception:
            pass
    except Exception as e:
        first['auto_analyze_error'] = str(e)

    return jsonify({
        'success': True,
        'tables': get_tables(),
        'active_table_id': get_active_table_id(),
        'upload_results': results,
        'errors': errors if errors else None,
        'audit_summary': first.get('audit_summary'),
        'score': first.get('score'),
        'history_id': first.get('history_id'),
        'history_save_error': first.get('history_save_error'),
    })


def _run_analysis_after_upload(first_result: dict, source_type: str = 'file') -> dict:
    """上传成功后自动执行审计分析并保存历史记录"""
    global _analysis_cache
    try:
        df = get_current_data()
        audit_results = run_all_rules(df)
        audit_summary = get_rule_summary(audit_results)
        anomaly_results = run_all_detectors(df)
        summary = get_current_summary() or {}
        score = calculate_overall_score(audit_results, anomaly_results)
        _analysis_cache = {
            'audit_results': audit_results,
            'audit_summary': audit_summary,
            'anomaly_results': anomaly_results,
            'score': score,
            'preview_data': first_result.get('preview_data', []),
            'preview_columns': first_result.get('preview_columns', []),
        }
        first_result['audit_summary'] = audit_summary
        first_result['score'] = score

        filename = first_result.get('filename', '未命名数据')
        record_id = save_history_record(
            title=filename,
            source_type=source_type,
            filename=filename,
            df=df,
            summary=summary,
            audit_results=audit_results,
            anomaly_results=anomaly_results,
            score=score,
            user_id=_uid(),
        )
        first_result['history_id'] = record_id
        tid = first_result.get('table_id') or get_active_table_id()
        if tid:
            bind_table_history(tid, record_id)
            persist_table(tid, _uid())
    except Exception as e:
        first_result['auto_analyze_error'] = str(e)
    return first_result


@app.route('/api/upload-image', methods=['POST'])
def api_upload_image():
    """上传图片进行 OCR 识别"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '未选择图片'})

    result = process_image_upload(request.files['file'])
    if result.get('success'):
        result = _run_analysis_after_upload(result, source_type='image')
        return jsonify({
            'success': True,
            'tables': get_tables(),
            'active_table_id': get_active_table_id(),
            'upload_results': [result],
            'audit_summary': result.get('audit_summary'),
            'score': result.get('score'),
            **result,
        })
    return jsonify(result)


@app.route('/api/import-table', methods=['POST'])
def api_import_table():
    """导入 OCR/AI 识别的表格 JSON"""
    data = request.get_json() or {}
    headers = data.get('headers') or []
    rows = data.get('rows') or []
    if not headers:
        return jsonify({'success': False, 'error': '缺少表头数据'})

    result = import_table_data(headers, rows)
    if not result.get('success'):
        return jsonify(result)

    result = _run_analysis_after_upload(result, source_type='import')
    return jsonify({
        'success': True,
        'tables': get_tables(),
        'active_table_id': get_active_table_id(),
        'upload_results': [result],
        'audit_summary': result.get('audit_summary'),
        'score': result.get('score'),
        **result,
    })


# ============================================================
# API - 多表管理
# ============================================================

@app.route('/api/tables')
def api_tables():
    """列出所有表"""
    uid = _uid()
    if uid:
        restore_working_tables_for_user(uid, force=True)
    tables = get_tables()
    return jsonify({
        'success': True,
        'tables': tables,
        'active_table_id': get_active_table_id(),
    })


@app.route('/api/table/<table_id>/activate', methods=['POST'])
def api_activate_table(table_id):
    """切换活动表"""
    ok = set_active_table(table_id)
    if ok:
        # 对活动表重新执行审计
        global _analysis_cache
        try:
            df = get_current_data()
            audit_results = run_all_rules(df)
            audit_summary = get_rule_summary(audit_results)
            anomaly_results = run_all_detectors(df)
            score = calculate_overall_score(audit_results, anomaly_results)
            summary = get_current_summary() or {}
            charts = _build_dashboard_charts(df, summary, audit_results, audit_summary)
            t = get_active_table()
            _analysis_cache = {
                'audit_results': audit_results,
                'audit_summary': audit_summary,
                'anomaly_results': anomaly_results,
                'score': score,
                'preview_data': t['preview_data'] if t else [],
                'preview_columns': t['preview_columns'] if t else [],
                'dashboard_charts': charts,
            }
        except Exception as e:
            pass

        return jsonify({'success': True, 'active_table_id': table_id})
    return jsonify({'success': False, 'error': '表不存在'})


@app.route('/api/table/<table_id>', methods=['DELETE'])
def api_delete_table(table_id):
    result = delete_table(table_id)
    return jsonify(result)


# ============================================================
# API - 电子表格编辑
# ============================================================

@app.route('/api/table/<table_id>/data')
def api_table_data(table_id):
    """获取表数据（分页）"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    result = get_table_data(table_id, page, per_page)
    return jsonify(result)


@app.route('/api/table/<table_id>/cell', methods=['PUT', 'POST'])
def api_update_cell(table_id):
    """更新单元格（POST 兼容 sendBeacon）"""
    data = request.get_json(silent=True) or {}
    row_idx = data.get('row')
    column = data.get('column')
    value = data.get('value')
    if row_idx is None or column is None:
        return jsonify({'success': False, 'error': '缺少 row 或 column 参数'})
    result = update_cell(table_id, int(row_idx), column, value)
    if result.get('success'):
        persist_table(table_id, _uid())
    return jsonify(result)


@app.route('/api/table/<table_id>/row', methods=['POST'])
def api_add_row(table_id):
    """添加行"""
    data = request.get_json() or {}
    result = add_row(table_id, data)
    if result.get('success'):
        persist_table(table_id, _uid())
    return jsonify(result)


@app.route('/api/table/<table_id>/row/<int:row_idx>', methods=['DELETE'])
def api_delete_row(table_id, row_idx):
    """删除行"""
    result = delete_row(table_id, row_idx)
    if result.get('success'):
        persist_table(table_id, _uid())
    return jsonify(result)


@app.route('/api/table/<table_id>/column', methods=['POST'])
def api_add_column(table_id):
    """添加列"""
    data = request.get_json() or {}
    col_name = data.get('name', '').strip()
    default_value = data.get('default', '')
    if not col_name:
        return jsonify({'success': False, 'error': '列名不能为空'})
    result = add_column(table_id, col_name, default_value)
    if result.get('success'):
        persist_table(table_id, _uid())
    return jsonify(result)


@app.route('/api/table/<table_id>/column/<col_name>', methods=['DELETE'])
def api_delete_column(table_id, col_name):
    """删除列"""
    result = delete_column(table_id, col_name)
    if result.get('success'):
        persist_table(table_id, _uid())
    return jsonify(result)


# ============================================================
# API - 财务核算
# ============================================================

@app.route('/api/finance/overview')
def api_finance_overview():
    from modules.finance import overview, accounts, vouchers
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    data = overview(uid)
    return jsonify({
        'success': True,
        **data,
        'accounts': accounts(uid),
        'recent_vouchers': vouchers(uid, limit=8),
    })


@app.route('/api/finance/accounts')
def api_finance_accounts():
    from modules.finance import accounts
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    return jsonify({'success': True, 'accounts': accounts(uid)})


@app.route('/api/finance/vouchers', methods=['GET', 'POST'])
def api_finance_vouchers():
    from modules.finance import vouchers, create_voucher
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    if request.method == 'GET':
        status = request.args.get('status')
        limit = request.args.get('limit', 50, type=int)
        return jsonify({'success': True, 'vouchers': vouchers(uid, limit=limit, status=status)})
    data = request.get_json(silent=True) or {}
    return jsonify(create_voucher(uid, data))


@app.route('/api/finance/vouchers/<int:voucher_id>/post', methods=['POST'])
def api_finance_post_voucher(voucher_id):
    from modules.finance import approve_voucher
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    return jsonify(approve_voucher(uid, voucher_id))


@app.route('/api/finance/vouchers/<int:voucher_id>/submit-approval', methods=['POST'])
def api_finance_submit_approval(voucher_id):
    from modules.finance import submit_voucher_approval
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    data = request.get_json(silent=True) or {}
    return jsonify(submit_voucher_approval(uid, voucher_id, data.get('approver_id')))


@app.route('/api/finance/vouchers/<int:voucher_id>/versions')
def api_voucher_versions(voucher_id):
    from modules.enterprise_db import list_doc_versions
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    return jsonify({'success': True, 'versions': list_doc_versions(uid, 'voucher', voucher_id)})


@app.route('/api/finance/vouchers/<int:voucher_id>/versions/<int:version_no>')
def api_voucher_version(voucher_id, version_no):
    from modules.enterprise_db import get_doc_version
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    v = get_doc_version(uid, 'voucher', voucher_id, version_no)
    if not v:
        return jsonify({'success': False, 'error': '版本不存在'})
    return jsonify({'success': True, 'version': v})


@app.route('/api/finance/partners')
def api_finance_partners():
    from modules.enterprise_db import list_partners
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    ptype = request.args.get('type')
    return jsonify({'success': True, 'partners': list_partners(uid, ptype)})


@app.route('/api/finance/partners', methods=['POST'])
def api_finance_partners_create():
    from modules.enterprise_db import create_partner
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    data = request.get_json(silent=True) or {}
    return jsonify({'success': True, 'partner_id': create_partner(uid, data)})


@app.route('/api/finance/invoices', methods=['GET', 'POST'])
def api_finance_invoices():
    from modules.enterprise_db import list_invoices, create_invoice
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    if request.method == 'GET':
        inv_type = request.args.get('type')
        return jsonify({'success': True, 'invoices': list_invoices(uid, inv_type)})
    data = request.get_json(silent=True) or {}
    iid = create_invoice(uid, data)
    from modules.enterprise_db import save_doc_version, list_invoices
    invs = list_invoices(uid)
    inv = next((x for x in invs if x['id'] == iid), None)
    if inv:
        save_doc_version(uid, 'invoice', iid, inv, message='开具发票', author_id=uid)
    return jsonify({'success': True, 'invoice_id': iid})


@app.route('/api/finance/invoices/<int:invoice_id>/pay', methods=['POST'])
def api_finance_invoice_pay(invoice_id):
    from modules.enterprise_db import record_invoice_payment
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    data = request.get_json(silent=True) or {}
    record_invoice_payment(uid, invoice_id, float(data.get('amount', 0)))
    return jsonify({'success': True})


@app.route('/api/finance/bank/accounts')
def api_finance_bank_accounts():
    from modules.enterprise_db import list_bank_accounts
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    return jsonify({'success': True, 'accounts': list_bank_accounts(uid)})


@app.route('/api/finance/bank/<int:bank_id>/txns')
def api_finance_bank_txns(bank_id):
    from modules.enterprise_db import list_bank_txns
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    return jsonify({'success': True, 'txns': list_bank_txns(bank_id, uid)})


@app.route('/api/finance/bank/<int:bank_id>/import', methods=['POST'])
def api_finance_bank_import(bank_id):
    from modules.enterprise_db import import_bank_txns
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    data = request.get_json(silent=True) or {}
    count = import_bank_txns(uid, bank_id, data.get('txns') or [])
    return jsonify({'success': True, 'imported': count})


@app.route('/api/finance/bank/<int:bank_id>/reconcile', methods=['POST'])
def api_finance_bank_reconcile(bank_id):
    from modules.enterprise_db import run_reconciliation
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    return jsonify({'success': True, **run_reconciliation(uid, bank_id)})


@app.route('/api/workflow/approvals')
def api_workflow_approvals():
    from modules.enterprise_db import list_approvals
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    scope = request.args.get('scope', 'mine')
    return jsonify({'success': True, 'approvals': list_approvals(uid, scope)})


@app.route('/api/workflow/approvals/<int:approval_id>/<action>', methods=['POST'])
def api_workflow_approval_act(approval_id, action):
    from modules.enterprise_db import act_approval
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    if action not in ('approved', 'rejected'):
        return jsonify({'success': False, 'error': '无效操作'})
    data = request.get_json(silent=True) or {}
    return jsonify(act_approval(uid, approval_id, action, data.get('comment', '')))


@app.route('/api/workflow/tasks', methods=['GET', 'POST'])
def api_workflow_tasks():
    from modules.enterprise_db import list_tasks, create_task
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        tid = create_task(uid, data)
        return jsonify({'success': True, 'task_id': tid})
    scope = request.args.get('scope', 'assigned')
    return jsonify({'success': True, 'tasks': list_tasks(uid, scope)})


@app.route('/api/workflow/tasks/<int:task_id>/status', methods=['POST'])
def api_workflow_task_status(task_id):
    from modules.enterprise_db import update_task_status
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    data = request.get_json(silent=True) or {}
    update_task_status(uid, task_id, data.get('status', 'done'))
    return jsonify({'success': True})


@app.route('/api/workflow/tasks/<int:task_id>/comments', methods=['GET', 'POST'])
def api_workflow_task_comments(task_id):
    from modules.enterprise_db import add_task_comment, list_task_comments
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    if request.method == 'POST':
        data = request.get_json(silent=True) or {}
        cid = add_task_comment(uid, task_id, data.get('content', ''))
        return jsonify({'success': True, 'comment_id': cid})
    return jsonify({'success': True, 'comments': list_task_comments(task_id)})


@app.route('/api/finance/versions/<doc_type>/<int:doc_id>')
def api_doc_versions(doc_type, doc_id):
    from modules.enterprise_db import list_doc_versions, get_doc_version
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    vno = request.args.get('version', type=int)
    if vno:
        v = get_doc_version(uid, doc_type, doc_id, vno)
        return jsonify({'success': bool(v), 'version': v})
    return jsonify({'success': True, 'versions': list_doc_versions(uid, doc_type, doc_id)})


# ============================================================
# API - 协同编辑
# ============================================================

@app.route('/api/collab/<token>/apply', methods=['POST'])
def api_collab_apply(token):
    """将协同最新内容写回普通表格编辑（退出协同 / 切回表格编辑时调用）。"""
    from modules.collab import sync_collab_to_source, can_access_collab
    from modules.database import get_collab_session
    session = get_collab_session(token)
    if not session:
        return jsonify({'success': False, 'error': '协同会话不存在'})
    if not can_access_collab(session, _uid()):
        return jsonify({'success': False, 'error': '无权操作'})
    # 写回到拥有者的源表，保证任何人编辑后主人表格一致
    return jsonify(sync_collab_to_source(token, session.get('owner_id')))


@app.route('/api/collab/create', methods=['POST'])
def api_collab_create():
    from modules.collab import create_session_from_table
    data = request.get_json(silent=True) or {}
    table_id = data.get('table_id') or get_active_table_id()
    if not table_id:
        return jsonify({'success': False, 'error': '请先选择要共享的表格'})
    return jsonify(create_session_from_table(_uid(), table_id))


@app.route('/api/collab/<token>/join', methods=['POST'])
def api_collab_join(token):
    from modules.collab import join_session
    return jsonify(join_session(token, _uid()))


@app.route('/api/collab/<token>/sync')
def api_collab_sync(token):
    from modules.collab import get_sync_state
    since = request.args.get('version', 0, type=int)
    return jsonify(get_sync_state(token, _uid(), since))


@app.route('/api/collab/<token>/editing', methods=['POST'])
def api_collab_editing(token):
    """上报当前正在编辑的单元格（用于协同光标/高亮）。"""
    from modules.collab import report_editing_cell
    data = request.get_json(silent=True) or {}
    row = data.get('row')
    column = data.get('column')
    if row is not None:
        row = int(row)
    if column is not None:
        column = str(column)
    if row is None or column is None:
        row, column = None, None
    return jsonify(report_editing_cell(token, _uid(), row, column))


@app.route('/api/collab/<token>/data')
def api_collab_data(token):
    from modules.collab import get_collab_page
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 50, type=int)
    return jsonify(get_collab_page(token, _uid(), page, per_page))


@app.route('/api/collab/<token>/cell', methods=['PUT', 'POST'])
def api_collab_cell(token):
    from modules.collab import update_collab_cell
    data = request.get_json(silent=True) or {}
    row_idx = data.get('row')
    column = data.get('column')
    value = data.get('value')
    if row_idx is None or column is None:
        return jsonify({'success': False, 'error': '缺少 row 或 column 参数'})
    return jsonify(update_collab_cell(token, _uid(), int(row_idx), column, value))


@app.route('/api/collab/<token>/row', methods=['POST'])
def api_collab_add_row(token):
    from modules.collab import add_collab_row
    data = request.get_json(silent=True) or {}
    return jsonify(add_collab_row(token, _uid(), data))


@app.route('/api/collab/<token>/row/<int:row_idx>', methods=['DELETE'])
def api_collab_delete_row(token, row_idx):
    from modules.collab import delete_collab_row
    return jsonify(delete_collab_row(token, _uid(), row_idx))


@app.route('/api/collab/<token>/column', methods=['POST'])
def api_collab_add_column(token):
    from modules.collab import add_collab_column
    data = request.get_json(silent=True) or {}
    col_name = (data.get('name') or '').strip()
    if not col_name:
        return jsonify({'success': False, 'error': '列名不能为空'})
    return jsonify(add_collab_column(token, _uid(), col_name, data.get('default', '')))


@app.route('/api/collab/<token>/column/<col_name>', methods=['DELETE'])
def api_collab_delete_column(token, col_name):
    from modules.collab import delete_collab_column
    return jsonify(delete_collab_column(token, _uid(), col_name))


@app.route('/api/collab/<token>/invite', methods=['POST'])
def api_collab_invite(token):
    """邀请好友协同编辑，并发送消息链接"""
    from modules.collab import build_invite_message, can_access_collab
    from modules.database import (
        create_notification, get_collab_session, get_user_by_id,
        is_friend, join_collab_session, send_message,
    )
    data = request.get_json(silent=True) or {}
    friend_id = data.get('friend_id')
    if not friend_id:
        return jsonify({'success': False, 'error': '请选择好友'})
    friend_id = int(friend_id)
    session = get_collab_session(token)
    if not session:
        return jsonify({'success': False, 'error': '协同会话不存在'})
    if not can_access_collab(session, _uid()):
        return jsonify({'success': False, 'error': '无权邀请'})
    if not is_friend(_uid(), friend_id):
        return jsonify({'success': False, 'error': '只能邀请好友'})
    join_collab_session(session['id'], friend_id)
    me = get_user_by_id(_uid())
    friend = get_user_by_id(friend_id)
    if not me or not friend:
        return jsonify({'success': False, 'error': '用户不存在'})
    content = build_invite_message(token, session['title'], me['username'])
    msg_id = send_message(_uid(), friend_id, content)
    create_notification(
        friend_id,
        'collab',
        f'{me["username"]} 邀请协同编辑',
        session['title'],
        f'/edit?collab={token}',
    )
    return jsonify({
        'success': True,
        'message_id': msg_id,
        'share_url': f'/edit?collab={token}',
        'friend': friend['username'],
    })


# ============================================================
# API - 摘要 & 分析
# ============================================================

def _build_dashboard_charts(df, summary, audit_results, audit_summary):
    """预计算仪表盘图表数据，避免每次请求重复跑 pandas。"""
    amount_col = summary.get('amount_stats', {}).get('column') if summary else None
    amount_distribution = None
    if amount_col and df is not None:
        amounts = pd.to_numeric(df[amount_col], errors='coerce').dropna()
        if len(amounts) > 5:
            lo, hi = amounts.quantile(0.01), amounts.quantile(0.99)
            amounts = amounts[(amounts > lo) & (amounts < hi)]
        if len(amounts) > 5:
            try:
                bins = pd.cut(amounts, bins=10)
                counts = bins.value_counts().sort_index()
                amount_distribution = {
                    'labels': [str(i).replace('(', '').replace(']', '').replace(', ', '-')
                               for i in counts.index.astype(str)],
                    'values': [int(x) for x in counts.values],
                }
            except Exception:
                pass

    category_data = None
    cat_cols = summary.get('category_counts', {}) if summary else {}
    if cat_cols:
        first_cat = list(cat_cols.keys())[0]
        cat_counts = cat_cols[first_cat]
        category_data = {
            'labels': list(cat_counts.keys())[:10],
            'values': list(cat_counts.values())[:10],
        }

    benford_data = None
    for r in audit_results:
        if r.get('rule') == 'benford' and 'observed' in r:
            benford_data = {
                'labels': ['1', '2', '3', '4', '5', '6', '7', '8', '9'],
                'observed': [r['observed'].get(str(d), 0) for d in range(1, 10)],
                'expected': [r['expected'].get(str(d), 0) for d in range(1, 10)],
            }
            break

    risk_distribution = None
    if audit_summary:
        risk_distribution = {
            'labels': ['高风险', '中风险', '低风险'],
            'values': [
                audit_summary.get('high_risk', 0),
                audit_summary.get('medium_risk', 0),
                audit_summary.get('low_risk', 0),
            ],
        }

    time_trend = None
    date_col = summary.get('date_range', {}).get('column') if summary else None
    if date_col and amount_col and df is not None:
        try:
            dates = pd.to_datetime(df[date_col], errors='coerce')
            amounts = pd.to_numeric(df[amount_col], errors='coerce')
            daily = pd.DataFrame({'_date': dates, '_amt': amounts}).dropna()
            daily = daily.groupby(daily['_date'].dt.date)['_amt'].sum().sort_index()
            if len(daily) > 1:
                time_trend = {
                    'labels': [str(d) for d in daily.index[-60:]],
                    'values': [round(float(v), 2) for v in daily.values[-60:]],
                }
        except Exception:
            pass

    return {
        'amount_distribution': amount_distribution,
        'category_data': category_data,
        'benford_data': benford_data,
        'risk_distribution': risk_distribution,
        'time_trend': time_trend,
    }


@app.route('/api/summary')
def api_summary():
    summary = get_current_summary()
    if summary is None:
        return jsonify({'success': False, 'error': '未加载数据'})
    return jsonify({'success': True, 'summary': summary, 'active_table_id': get_active_table_id()})


@app.route('/api/analyze', methods=['POST'])
def api_analyze():
    global _analysis_cache
    df = get_current_data()
    if df is None:
        return jsonify({'success': False, 'error': '未加载数据，请先上传文件'})

    audit_results = run_all_rules(df)
    audit_summary = get_rule_summary(audit_results)
    anomaly_results = run_all_detectors(df)
    summary = get_current_summary() or {}
    score = calculate_overall_score(audit_results, anomaly_results)

    t = get_active_table()
    charts = _build_dashboard_charts(df, summary, audit_results, audit_summary)
    _analysis_cache = {
        'audit_results': audit_results,
        'audit_summary': audit_summary,
        'anomaly_results': anomaly_results,
        'score': score,
        'preview_data': t['preview_data'] if t else [],
        'preview_columns': t['preview_columns'] if t else [],
        'dashboard_charts': charts,
    }

    return jsonify({
        'success': True,
        'audit_results': audit_results,
        'audit_summary': audit_summary,
        'anomaly_results': anomaly_results,
        'score': score,
    })


@app.route('/api/preview-data')
def api_preview_data():
    global _analysis_cache
    df = get_current_data()
    if df is None:
        return jsonify({'success': False, 'error': '未加载数据，请先上传文件'})

    summary = get_current_summary()
    preview_data = _analysis_cache.get('preview_data', [])
    preview_columns = _analysis_cache.get('preview_columns', list(df.columns))

    return jsonify({
        'success': True,
        'summary': summary,
        'preview_data': preview_data,
        'preview_columns': preview_columns,
        'tables': get_tables(),
        'active_table_id': get_active_table_id(),
    })


@app.route('/api/dashboard')
def api_dashboard():
    df = get_current_data()
    if df is None:
        return jsonify({'success': False, 'error': '未加载数据'})

    global _analysis_cache
    summary = get_current_summary()
    audit_summary = _analysis_cache.get('audit_summary', {})
    score = _analysis_cache.get('score', {})
    charts = _analysis_cache.get('dashboard_charts')
    if charts is None:
        audit_results = _analysis_cache.get('audit_results', [])
        charts = _build_dashboard_charts(df, summary, audit_results, audit_summary)
        _analysis_cache['dashboard_charts'] = charts

    return jsonify({
        'success': True,
        'summary': summary,
        'audit_summary': audit_summary,
        'score': score,
        'tables': get_tables(),
        'active_table_id': get_active_table_id(),
        'charts': charts,
    })


@app.route('/api/analysis/<rule_name>')
def api_rule_detail(rule_name):
    global _analysis_cache
    for r in _analysis_cache.get('audit_results', []):
        if r.get('rule') == rule_name:
            return jsonify({'success': True, 'detail': r})
    return jsonify({'success': False, 'error': f'未找到规则: {rule_name}'})


# ============================================================
# API - 三阶段审计
# ============================================================

@app.route('/api/audit/risk-assessment', methods=['POST'])
def api_risk_assessment():
    """执行风险评估阶段"""
    global _analysis_cache
    df = get_current_data()
    if df is None:
        return jsonify({'success': False, 'error': '未加载数据'})

    result = run_risk_assessment(df)
    _analysis_cache['phase1_results'] = result

    # 同时保存到历史记录
    history_id = _analysis_cache.get('history_id')
    summary = result.get('summary', {})
    return jsonify({
        'success': True,
        'phase1_results': result,
        'summary': summary,
        'findings_count': summary.get('total_findings', 0),
    })


@app.route('/api/audit/control-tests', methods=['POST'])
def api_control_tests():
    """执行控制测试阶段"""
    global _analysis_cache
    df = get_current_data()
    if df is None:
        return jsonify({'success': False, 'error': '未加载数据'})

    result = run_control_tests(df)
    _analysis_cache['phase2_results'] = result

    summary = result.get('summary', {})
    return jsonify({
        'success': True,
        'phase2_results': result,
        'summary': summary,
        'findings_count': summary.get('total_findings', 0),
    })


@app.route('/api/audit/substantive-procedures', methods=['POST'])
def api_substantive_procedures():
    """执行实质性程序"""
    global _analysis_cache
    df = get_current_data()
    if df is None:
        return jsonify({'success': False, 'error': '未加载数据'})

    data = request.get_json(silent=True) or {}
    procedures = data.get('procedures')
    bs_date = data.get('bs_date')

    result = run_substantive_procedures(df, procedures=procedures, bs_date=bs_date)
    _analysis_cache['phase3_results'] = result

    summary = result.get('summary', {})
    return jsonify({
        'success': True,
        'phase3_results': result,
        'summary': summary,
        'findings_count': summary.get('total_findings', 0),
    })


@app.route('/api/audit/run-all', methods=['POST'])
def api_run_all_phases():
    """一键执行全部三阶段审计"""
    global _analysis_cache
    df = get_current_data()
    if df is None:
        return jsonify({'success': False, 'error': '未加载数据'})

    data = request.get_json(silent=True) or {}
    bs_date = data.get('bs_date')

    results = {}
    errors = []

    try:
        results['phase1'] = run_risk_assessment(df)
        _analysis_cache['phase1_results'] = results['phase1']
    except Exception as e:
        errors.append(f'风险评估: {e}')
        results['phase1'] = {'error': str(e)}

    try:
        results['phase2'] = run_control_tests(df)
        _analysis_cache['phase2_results'] = results['phase2']
    except Exception as e:
        errors.append(f'控制测试: {e}')
        results['phase2'] = {'error': str(e)}

    try:
        results['phase3'] = run_substantive_procedures(df, bs_date=bs_date)
        _analysis_cache['phase3_results'] = results['phase3']
    except Exception as e:
        errors.append(f'实质性程序: {e}')
        results['phase3'] = {'error': str(e)}

    # 综合评分 v2
    try:
        score_v2 = calculate_overall_score_v2(
            _analysis_cache.get('audit_results', []),
            _analysis_cache.get('anomaly_results', {}),
            _analysis_cache.get('phase1_results'),
            _analysis_cache.get('phase2_results'),
            _analysis_cache.get('phase3_results'),
        )
        _analysis_cache['score_v2'] = score_v2
    except Exception:
        score_v2 = _analysis_cache.get('score', {})

    total_findings = sum(
        r.get('summary', {}).get('total_findings', 0)
        for r in [results.get('phase1', {}), results.get('phase2', {}), results.get('phase3', {})]
    )

    return jsonify({
        'success': True,
        'results': results,
        'score_v2': score_v2,
        'total_findings': total_findings,
        'errors': errors if errors else None,
    })


@app.route('/api/dashboard/phase1')
def api_dashboard_phase1():
    """风险评估仪表盘数据"""
    global _analysis_cache
    p1 = _analysis_cache.get('phase1_results')
    if not p1:
        return jsonify({'success': False, 'error': '请先执行风险评估'})

    summary = get_current_summary() or {}
    procedures = p1.get('procedures', {})

    # 构建图表数据
    chart_data = {}

    # 财务比率雷达图数据
    ratios_proc = procedures.get('financial_ratios', {})
    if ratios_proc:
        ratio_list = ratios_proc.get('ratios', [])
        if ratio_list:
            chart_data['ratios'] = {
                'labels': [r['name'] for r in ratio_list],
                'values': [r['value'] for r in ratio_list],
            }
        anomaly_list = ratios_proc.get('anomalies', [])
        if anomaly_list:
            chart_data['ratio_anomalies'] = {
                'labels': [a['name'] for a in anomaly_list],
                'values': [a['value'] for a in anomaly_list],
            }

    # 收入月度分布
    fraud_proc = procedures.get('revenue_fraud', {})
    monthly = fraud_proc.get('monthly_revenue', [])
    if monthly:
        chart_data['monthly_revenue'] = {
            'labels': [m['month'] for m in monthly[-12:]],
            'values': [m['total'] for m in monthly[-12:]],
        }

    # 客户集中度
    concentration = fraud_proc.get('concentration', {})
    top_n = concentration.get('top_n', [])
    if top_n:
        chart_data['concentration'] = {
            'labels': [t['label'][:10] for t in top_n],
            'values': [t['pct'] for t in top_n],
        }

    return jsonify({
        'success': True,
        'summary': summary,
        'phase1_results': p1,
        'chart_data': chart_data,
    })


@app.route('/api/dashboard/phase2')
def api_dashboard_phase2():
    """控制测试仪表盘数据"""
    global _analysis_cache
    p2 = _analysis_cache.get('phase2_results')
    if not p2:
        return jsonify({'success': False, 'error': '请先执行控制测试'})

    procedures = p2.get('procedures', {})

    chart_data = {}

    # 控制测试通过/失败
    it_proc = procedures.get('it_controls', {})
    tests = it_proc.get('tests', [])
    if tests:
        chart_data['it_tests'] = {
            'labels': [t['test'] for t in tests],
            'passed': [1 if t['passed'] else 0 for t in tests],
            'failed': [0 if t['passed'] else 1 for t in tests],
        }

    biz_proc = procedures.get('biz_automation', {})
    steps = biz_proc.get('workflow_steps', [])
    if steps:
        chart_data['biz_steps'] = {
            'labels': [s['step'] for s in steps],
            'passed': [1 if s['passed'] else 0 for s in steps],
            'failed': [0 if s['passed'] else 1 for s in steps],
        }

    return jsonify({
        'success': True,
        'phase2_results': p2,
        'chart_data': chart_data,
    })


@app.route('/api/dashboard/phase3')
def api_dashboard_phase3():
    """实质性程序仪表盘数据"""
    global _analysis_cache
    p3 = _analysis_cache.get('phase3_results')
    if not p3:
        return jsonify({'success': False, 'error': '请先执行实质性程序'})

    procedures = p3.get('procedures', {})

    # 各程序风险统计
    proc_stats = []
    for key, proc in procedures.items():
        proc_stats.append({
            'key': key,
            'name': proc.get('name', key),
            'risk': proc.get('risk', 'low'),
            'suspicious': proc.get('suspicious', False),
            'findings_count': len(proc.get('findings', [])),
            'description': proc.get('description', ''),
        })

    return jsonify({
        'success': True,
        'phase3_results': p3,
        'proc_stats': proc_stats,
    })


@app.route('/api/audit/session-state')
def api_session_state():
    """当前会话审计状态"""
    global _analysis_cache
    return jsonify({
        'success': True,
        'phases_run': {
            'phase1': 'phase1_results' in _analysis_cache,
            'phase2': 'phase2_results' in _analysis_cache,
            'phase3': 'phase3_results' in _analysis_cache,
        },
        'has_data': get_current_data() is not None,
        'score_v2': _analysis_cache.get('score_v2'),
        'total_findings': (
            _analysis_cache.get('phase1_results', {}).get('summary', {}).get('total_findings', 0) +
            _analysis_cache.get('phase2_results', {}).get('summary', {}).get('total_findings', 0) +
            _analysis_cache.get('phase3_results', {}).get('summary', {}).get('total_findings', 0)
        ),
    })


# ============================================================
# API - 个人空间
# ============================================================

@app.route('/api/profile')
def api_profile():
    """当前用户个人资料"""
    user = g.current_user
    if not user:
        return jsonify({'success': False, 'error': '未登录'}), 401
    uid = user['id']
    from modules.database import get_friends, get_unread_count, list_history
    friends = get_friends(uid)
    history = list_history(limit=100, user_id=uid)
    return jsonify({
        'success': True,
        'user': {
            'id': uid,
            'username': user['username'],
            'created_at': user.get('created_at', ''),
            'role': user.get('role', ''),
            'company': user.get('company') or '',
        },
        'stats': {
            'history_count': len(history),
            'friends_count': len(friends),
            'messages_count': get_unread_count(uid),
        },
    })


@app.route('/api/profile/company', methods=['POST'])
def api_profile_update_company():
    """补填/更新公司，并自动与同公司用户互为好友"""
    data = request.get_json(silent=True) or {}
    company = (data.get('company') or '').strip()
    if not company:
        return jsonify({'success': False, 'error': '公司名称不能为空'})
    from modules.database import update_user_profile, auto_friend_same_company
    from modules.roles import PROFESSIONAL_ROLES
    user = g.current_user
    update_user_profile(user['id'], company=company)
    linked = auto_friend_same_company(user['id'], company)
    return jsonify({
        'success': True,
        'company': company,
        'auto_friends': linked,
        'need_company': user.get('role') in PROFESSIONAL_ROLES,
    })


@app.route('/api/profile/stats')
def api_profile_stats():
    """用户数据统计"""
    from modules.database import list_history, get_friends
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '未登录'}), 401
    records = list_history(limit=100, user_id=uid)
    total_rows = sum(r.get('row_count', 0) for r in records)
    total_findings = 0
    avg_score = 0
    for r in records:
        score = r.get('score', {})
        if isinstance(score, dict):
            total_findings += score.get('risk_items', 0) if isinstance(score.get('risk_items'), int) else len(score.get('risk_items', []))
            if score.get('risk_percentage'):
                avg_score += score['risk_percentage']
    if records:
        avg_score = round(avg_score / len(records), 1)
    return jsonify({
        'success': True,
        'total_records': len(records),
        'total_rows': total_rows,
        'total_findings': total_findings,
        'avg_score': avg_score,
        'records': records[:10],
    })


# ============================================================
# API - 用户搜索
# ============================================================

@app.route('/api/users/search')
def api_search_users():
    """搜索用户"""
    q = (request.args.get('q') or '').strip()
    if not q:
        return jsonify({'success': False, 'error': '请输入搜索关键词'})
    from modules.database import search_users
    users = search_users(q, exclude_id=_uid())
    return jsonify({'success': True, 'users': users})


# ============================================================
# API - 好友系统
# ============================================================

@app.route('/api/friends')
def api_friends():
    """好友列表"""
    from modules.database import get_friends
    friends = get_friends(_uid())
    return jsonify({'success': True, 'friends': friends})


@app.route('/api/friends/requests')
def api_friend_requests():
    """待处理的好友申请"""
    from modules.database import get_friend_requests
    requests = get_friend_requests(_uid())
    return jsonify({'success': True, 'requests': requests})


@app.route('/api/friends/add', methods=['POST'])
def api_add_friend():
    """发送好友申请"""
    data = request.get_json(silent=True) or {}
    friend_id = data.get('friend_id')
    if not friend_id:
        return jsonify({'success': False, 'error': '缺少 friend_id'})
    from modules.database import send_friend_request, create_notification, get_user_by_id
    result = send_friend_request(_uid(), int(friend_id))
    if result.get('success'):
        me = get_user_by_id(_uid())
        if me:
            create_notification(
                int(friend_id),
                'friend',
                f'{me["username"]} 请求添加你为好友',
                '请在个人空间查看好友申请',
                '/profile',
            )
    return jsonify(result)


@app.route('/api/friends/remove', methods=['POST'])
def api_remove_friend():
    """删除好友"""
    data = request.get_json(silent=True) or {}
    friend_id = data.get('friend_id')
    if not friend_id:
        return jsonify({'success': False, 'error': '缺少 friend_id'})
    from modules.database import remove_friend
    result = remove_friend(_uid(), int(friend_id))
    return jsonify(result)


@app.route('/api/friends/requests/<int:request_id>/<action>', methods=['POST'])
def api_handle_friend_request(request_id, action):
    """处理好友申请（accept/reject）"""
    from modules.database import accept_friend_request, reject_friend_request
    if action == 'accept':
        result = accept_friend_request(_uid(), request_id)
    elif action == 'reject':
        result = reject_friend_request(_uid(), request_id)
    else:
        return jsonify({'success': False, 'error': f'不支持的操作: {action}'})
    return jsonify(result)


# ============================================================
# API - 即时消息
# ============================================================

@app.route('/api/messages/send', methods=['POST'])
def api_send_message():
    """发送消息（任意注册用户可互发，无需先加好友）"""
    data = request.get_json(silent=True) or {}
    receiver_id = data.get('receiver_id')
    content = (data.get('content') or '').strip()
    if not receiver_id or not content:
        return jsonify({'success': False, 'error': '缺少接收者或消息内容'})
    from modules.database import send_message, create_notification, get_user_by_id
    receiver_id = int(receiver_id)
    if receiver_id == _uid():
        return jsonify({'success': False, 'error': '不能给自己发消息'})
    receiver = get_user_by_id(receiver_id)
    if not receiver:
        return jsonify({'success': False, 'error': '接收者不存在'})
    sender = get_user_by_id(_uid())
    msg_id = send_message(_uid(), receiver_id, content)
    if sender:
        create_notification(
            receiver_id,
            'message',
            f'{sender["username"]} 发来新消息',
            content[:120],
            f'/chat?id={_uid()}&user={sender["username"]}',
        )
    return jsonify({'success': True, 'message_id': msg_id})


@app.route('/api/messages/send-voice', methods=['POST'])
def api_send_voice_message():
    """发送语音消息（浏览器 MediaRecorder 上传 webm/ogg/mp3）"""
    receiver_id = request.form.get('receiver_id') or (request.get_json(silent=True) or {}).get('receiver_id')
    if not receiver_id:
        return jsonify({'success': False, 'error': '缺少接收者'})
    receiver_id = int(receiver_id)
    if receiver_id == _uid():
        return jsonify({'success': False, 'error': '不能给自己发消息'})
    audio = request.files.get('audio') or request.files.get('file')
    if not audio or not audio.filename:
        return jsonify({'success': False, 'error': '未收到音频文件'})
    from modules.database import send_message, create_notification, get_user_by_id
    receiver = get_user_by_id(receiver_id)
    if not receiver:
        return jsonify({'success': False, 'error': '接收者不存在'})
    import uuid
    from werkzeug.utils import secure_filename
    ext = (secure_filename(audio.filename).rsplit('.', 1)[-1] or 'webm').lower()
    if ext not in {'webm', 'ogg', 'mp3', 'wav', 'm4a', 'aac'}:
        ext = 'webm'
    voice_dir = os.path.join(os.path.dirname(__file__), 'uploads', 'voice')
    os.makedirs(voice_dir, exist_ok=True)
    fname = f'{_uid()}_{uuid.uuid4().hex[:12]}.{ext}'
    fpath = os.path.join(voice_dir, fname)
    audio.save(fpath)
    media_url = f'/uploads/voice/{fname}'
    msg_id = send_message(_uid(), receiver_id, '[语音消息]', msg_type='voice', media_url=media_url)
    sender = get_user_by_id(_uid())
    if sender:
        create_notification(
            receiver_id,
            'message',
            f'{sender["username"]} 发来语音',
            '[语音消息]',
            f'/chat?id={_uid()}&user={sender["username"]}',
        )
    return jsonify({'success': True, 'message_id': msg_id, 'media_url': media_url})


@app.route('/api/colleagues')
def api_colleagues():
    """同公司同事（自动好友），可直接聊天"""
    from modules.database import list_company_colleagues
    return jsonify({'success': True, 'colleagues': list_company_colleagues(_uid())})


@app.route('/uploads/voice/<path:filename>')
def serve_voice_file(filename):
    voice_dir = os.path.join(os.path.dirname(__file__), 'uploads', 'voice')
    return send_from_directory(voice_dir, filename)

@app.route('/api/messages/with/<int:user_id>')
def api_get_messages(user_id):
    """获取与某用户的聊天记录"""
    if user_id == _uid():
        return jsonify({'success': False, 'error': '无法与自己建立会话'})
    from modules.database import get_messages, mark_messages_read, get_user_by_id
    if not get_user_by_id(user_id):
        return jsonify({'success': False, 'error': '用户不存在'})
    mark_messages_read(_uid(), user_id)
    msgs = get_messages(_uid(), user_id, limit=100)
    return jsonify({'success': True, 'messages': msgs})


@app.route('/api/messages/conversations')
def api_conversations():
    """会话列表"""
    from modules.database import get_conversations
    convs = get_conversations(_uid())
    return jsonify({'success': True, 'conversations': convs})


@app.route('/api/messages/unread-count')
def api_unread_count():
    """未读消息数"""
    from modules.database import get_unread_count
    count = get_unread_count(_uid())
    return jsonify({'success': True, 'count': count})


@app.route('/api/messages/poll')
def api_messages_poll():
    """轮询新消息（全局实时同步）"""
    from modules.database import poll_incoming_messages, get_unread_count
    last_id = request.args.get('last_id', 0, type=int)
    msgs = poll_incoming_messages(_uid(), last_id)
    return jsonify({
        'success': True,
        'messages': msgs,
        'unread': get_unread_count(_uid()),
        'last_id': msgs[-1]['id'] if msgs else last_id,
    })


# ============================================================
# API - 消息提醒
# ============================================================

@app.route('/api/notifications')
def api_notifications():
    from modules.database import list_notifications
    unread_only = request.args.get('unread') == '1'
    items = list_notifications(_uid(), limit=40, unread_only=unread_only)
    return jsonify({'success': True, 'notifications': items})


@app.route('/api/notifications/unread-count')
def api_notification_unread_count():
    from modules.database import get_notification_unread_count
    return jsonify({'success': True, 'count': get_notification_unread_count(_uid())})


@app.route('/api/notifications/read', methods=['POST'])
def api_notifications_read():
    from modules.database import mark_notifications_read
    data = request.get_json(silent=True) or {}
    ids = data.get('ids')
    mark_notifications_read(_uid(), ids if ids else None)
    return jsonify({'success': True})


# ============================================================
# API - 用户反馈
# ============================================================

@app.route('/api/feedback', methods=['POST'])
def api_feedback():
    from modules.database import save_feedback
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'success': False, 'error': '请填写反馈内容'})
    rating = int(data.get('rating') or 0)
    rating = max(0, min(5, rating))
    fid = save_feedback(_uid(), data.get('page') or request.referrer or '', rating, message)
    return jsonify({'success': True, 'id': fid})


# ============================================================
# API - 视频通话信令（消息页 WebRTC）
# ============================================================

@app.route('/api/call/start', methods=['POST'])
def api_call_start():
    from modules.call_signaling import start_call
    from modules.database import create_notification, get_user_by_id, is_friend
    data = request.get_json(silent=True) or {}
    peer_id = data.get('peer_id')
    if not peer_id:
        return jsonify({'success': False, 'error': '缺少对方用户 ID'})
    peer_id = int(peer_id)
    if peer_id == _uid():
        return jsonify({'success': False, 'error': '不能呼叫自己'})
    if not is_friend(_uid(), peer_id):
        return jsonify({'success': False, 'error': '请先添加对方为好友后再视频通话'})
    room = start_call(_uid(), peer_id)
    me = get_user_by_id(_uid())
    if me:
        create_notification(
            peer_id,
            'call',
            f'{me["username"]} 发起视频通话',
            '请在消息页接听',
            f'/chat?id={_uid()}&user={me["username"]}',
        )
    return jsonify({'success': True, **room})


@app.route('/api/call/offer', methods=['POST'])
def api_call_offer():
    from modules.call_signaling import set_offer
    data = request.get_json(silent=True) or {}
    ok = set_offer(_uid(), int(data['peer_id']), data.get('sdp'))
    return jsonify({'success': ok})


@app.route('/api/call/answer', methods=['POST'])
def api_call_answer():
    from modules.call_signaling import set_answer
    data = request.get_json(silent=True) or {}
    ok = set_answer(int(data['caller_id']), _uid(), data.get('sdp'))
    return jsonify({'success': ok})


@app.route('/api/call/ice', methods=['POST'])
def api_call_ice():
    from modules.call_signaling import add_ice
    data = request.get_json(silent=True) or {}
    ok = add_ice(_uid(), int(data['peer_id']), data.get('candidate'))
    return jsonify({'success': ok})


@app.route('/api/call/poll')
def api_call_poll():
    from modules.call_signaling import poll
    peer_id = request.args.get('peer_id', type=int)
    if not peer_id:
        return jsonify({'success': False, 'error': '缺少 peer_id'})
    return jsonify({'success': True, **poll(_uid(), peer_id)})


@app.route('/api/call/incoming')
def api_call_incoming():
    """检测是否有发给自己的视频通话邀请"""
    from modules.call_signaling import poll_incoming
    from modules.database import get_user_by_id
    info = poll_incoming(_uid())
    if not info.get('active'):
        return jsonify({'success': True, 'active': False})
    caller = get_user_by_id(info.get('caller_id'))
    return jsonify({
        'success': True,
        'active': True,
        'caller_id': info['caller_id'],
        'caller_name': caller['username'] if caller else '对方',
        'offer': info.get('offer'),
        'status': info.get('status'),
    })


@app.route('/api/call/end', methods=['POST'])
def api_call_end():
    from modules.call_signaling import end_call
    data = request.get_json(silent=True) or {}
    peer_id = data.get('peer_id')
    if peer_id:
        end_call(_uid(), int(peer_id))
    return jsonify({'success': True})


# ============================================================
# API - AI 助手增强
# ============================================================

# 服务端 AI 对话历史缓存
_ai_conversations: dict[int, list[dict]] = {}
_agent_conversations: dict[int, list[dict]] = {}


@app.route('/api/ai/clear', methods=['POST'])
def api_ai_clear():
    """清空当前用户的 AI 对话上下文"""
    uid = _uid()
    if uid in _ai_conversations:
        del _ai_conversations[uid]
    return jsonify({'success': True})


def _build_ai_context() -> str:
    global _analysis_cache
    parts = []

    summary = get_current_summary()
    if summary:
        parts.append(f"数据总览: {summary.get('total_rows', 0)}行, {summary.get('total_columns', 0)}列")
        amt = summary.get('amount_stats', {})
        if amt:
            parts.append(f"金额统计: 合计{amt.get('total', 0):,.0f}, 均值{amt.get('mean', 0):,.0f}, 最大{amt.get('max', 0):,.0f}")
        dr = summary.get('date_range', {})
        if dr:
            parts.append(f"日期范围: {dr.get('start', '')} ~ {dr.get('end', '')}")

    score = _analysis_cache.get('score', {})
    if score:
        parts.append(f"综合风险: {score.get('overall_label', '')} (评分{score.get('risk_percentage', 0)}%)")

    for r in _analysis_cache.get('audit_results', []):
        desc = r.get('description', '')
        if desc:
            parts.append(f"[{r.get('risk', '')}风险] {r.get('name', '')}: {desc}")

    anom = _analysis_cache.get('anomaly_results', {}).get('summary', {})
    if anom:
        parts.append(f"统计异常: 共{anom.get('total_anomalies_found', 0)}个离群值")

    return '\n'.join(parts)


# ============================================================
# API - 文件共享（好友间传输文件）
# ============================================================

@app.route('/api/files/send', methods=['POST'])
def api_send_file():
    """向好友发送文件"""
    from modules.database import save_shared_file, get_friends
    receiver_id = request.form.get('receiver_id', '').strip()
    if not receiver_id:
        return jsonify({'success': False, 'error': '缺少接收者ID'})
    receiver_id = int(receiver_id)

    # 校验是否为好友
    friends = get_friends(_uid())
    friend_ids = {f['friend_id'] if f.get('user_id') == _uid() else f.get('user_id')
                  for f in friends if isinstance(f, dict)}
    # 兼容 friend 字典中可能的两种表示
    for f in friends:
        if f.get('user_id') == _uid():
            friend_ids.add(f.get('friend_id'))
        else:
            friend_ids.add(f.get('user_id'))
    if receiver_id not in friend_ids:
        return jsonify({'success': False, 'error': '只能向好友发送文件'})

    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '未选择文件'})

    file = request.files['file']
    if not file or file.filename == '':
        return jsonify({'success': False, 'error': '未选择文件'})

    original_name = file.filename
    file_data = file.read()
    if len(file_data) == 0:
        return jsonify({'success': False, 'error': '文件为空'})
    if len(file_data) > 200 * 1024 * 1024:
        return jsonify({'success': False, 'error': '文件不能超过200MB'})

    try:
        file_id = save_shared_file(_uid(), receiver_id, original_name, file_data)
        return jsonify({
            'success': True,
            'file_id': file_id,
            'file_name': original_name,
            'file_size': len(file_data),
        })
    except Exception as e:
        return jsonify({'success': False, 'error': f'文件保存失败: {str(e)}'})


@app.route('/api/files/received')
def api_received_files():
    """我收到的文件列表"""
    from modules.database import get_received_files
    files = get_received_files(_uid(), limit=50)
    return jsonify({'success': True, 'files': files})


@app.route('/api/files/sent')
def api_sent_files():
    """我发送的文件列表"""
    from modules.database import get_sent_files
    files = get_sent_files(_uid(), limit=50)
    return jsonify({'success': True, 'files': files})


@app.route('/api/files/<int:file_id>/download')
def api_download_file(file_id):
    """下载共享文件"""
    from modules.database import get_shared_file, SHARED_FILES_DIR
    record = get_shared_file(file_id, user_id=_uid())
    if not record:
        return jsonify({'success': False, 'error': '文件不存在或无权访问'}), 404

    file_path = os.path.join(SHARED_FILES_DIR, record['stored_name'])
    if not os.path.exists(file_path):
        return jsonify({'success': False, 'error': '文件已被删除'}), 404

    return send_file(file_path, download_name=record['original_name'], as_attachment=True)


@app.route('/api/files/unread-count')
def api_files_unread_count():
    """未读/未下载文件数"""
    from modules.database import get_unread_files_count
    count = get_unread_files_count(_uid())
    return jsonify({'success': True, 'count': count})


# ============================================================
# API - 导出（扩展版）
# ============================================================

@app.route('/api/export/html')
def api_export_html():
    global _analysis_cache
    if not _analysis_cache:
        return jsonify({'success': False, 'error': '无分析结果'})

    summary = get_current_summary() or {}
    t = get_active_table()
    summary['filename'] = t['filename'] if t else 'N/A'

    include_phases = request.args.get('include_phases', '')
    if include_phases and (
        _analysis_cache.get('phase1_results') or
        _analysis_cache.get('phase2_results') or
        _analysis_cache.get('phase3_results')
    ):
        score = _analysis_cache.get('score_v2') or calculate_overall_score_v2(
            _analysis_cache['audit_results'],
            _analysis_cache['anomaly_results'],
            _analysis_cache.get('phase1_results'),
            _analysis_cache.get('phase2_results'),
            _analysis_cache.get('phase3_results'),
        )
        html = generate_html_report_v2(
            _analysis_cache['audit_results'],
            _analysis_cache['anomaly_results'],
            summary,
            score,
            _analysis_cache.get('phase1_results'),
            _analysis_cache.get('phase2_results'),
            _analysis_cache.get('phase3_results'),
        )
    else:
        score = _analysis_cache.get('score') or calculate_overall_score(
            _analysis_cache['audit_results'],
            _analysis_cache['anomaly_results'],
        )
        html = generate_html_report(
            _analysis_cache['audit_results'],
            _analysis_cache['anomaly_results'],
            summary,
            score,
        )

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    uid = _uid()
    if uid:
        try:
            from modules.enterprise_db import save_doc_version
            save_doc_version(
                uid, 'report', hash(timestamp) % 100000,
                {'summary': summary, 'score': score, 'format': 'html',
                 'audit_count': len(_analysis_cache.get('audit_results', []))},
                message=f'导出 HTML 报告 {timestamp}',
                author_id=uid,
            )
        except Exception:
            pass
    return send_file(
        io.BytesIO(html.encode('utf-8')),
        mimetype='text/html',
        as_attachment=True,
        download_name=f'audit_report_{timestamp}.html',
    )


@app.route('/api/export/excel')
def api_export_excel():
    global _analysis_cache
    if not _analysis_cache:
        return jsonify({'success': False, 'error': '无分析结果'})

    include_phases = request.args.get('include_phases', '')
    if include_phases and (
        _analysis_cache.get('phase1_results') or
        _analysis_cache.get('phase2_results') or
        _analysis_cache.get('phase3_results')
    ):
        score = _analysis_cache.get('score_v2') or calculate_overall_score_v2(
            _analysis_cache['audit_results'],
            _analysis_cache['anomaly_results'],
            _analysis_cache.get('phase1_results'),
            _analysis_cache.get('phase2_results'),
            _analysis_cache.get('phase3_results'),
        )
        excel_bytes = export_to_excel_v2(
            _analysis_cache['audit_results'],
            _analysis_cache['anomaly_results'],
            score,
            _analysis_cache.get('phase1_results'),
            _analysis_cache.get('phase2_results'),
            _analysis_cache.get('phase3_results'),
        )
    else:
        score = _analysis_cache.get('score') or calculate_overall_score(
            _analysis_cache['audit_results'],
            _analysis_cache['anomaly_results'],
        )
        excel_bytes = export_to_excel(
            _analysis_cache['audit_results'],
            _analysis_cache['anomaly_results'],
            score,
        )

    timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
    return send_file(
        excel_bytes,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'audit_report_{timestamp}.xlsx',
    )


# ============================================================
# API - 语音识别
# ============================================================

@app.route('/api/voice/recognize', methods=['POST'])
def api_voice_recognize():
    """服务端语音识别（Web Speech API 不可用时的回退方案）"""
    if 'audio' not in request.files:
        return jsonify({'success': False, 'error': '未收到音频数据'})

    audio_file = request.files['audio']
    audio_data = audio_file.read()
    if not audio_data:
        return jsonify({'success': False, 'error': '音频数据为空'})

    try:
        import io
        import speech_recognition as sr
        from pydub import AudioSegment
        from speech_recognition import UnknownValueError, RequestError

        audio = AudioSegment.from_file(io.BytesIO(audio_data))
        wav_io = io.BytesIO()
        audio.export(wav_io, format='wav')
        wav_io.seek(0)

        recognizer = sr.Recognizer()
        with sr.AudioFile(wav_io) as source:
            recognizer.adjust_for_ambient_noise(source, duration=0.3)
            content = recognizer.record(source)

        text = recognizer.recognize_google(content, language='zh-CN')
        return jsonify({'success': True, 'text': text.strip()})
    except UnknownValueError:
        return jsonify({'success': False, 'error': '无法识别语音内容，请重试'})
    except RequestError as e:
        return jsonify({'success': False, 'error': f'语音识别服务不可用: {e}'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'语音识别失败: {str(e)}'})


# ============================================================
# API - AI 助手
# ============================================================

@app.route('/api/ai/status')
def api_ai_status():
    from modules.ai.model_router import list_models, get_default_model_id
    models = list_models()
    available = [m for m in models if m.get('available')]
    return jsonify({
        'success': True,
        'mode': 'api',
        'loaded': bool(available),
        'ready': bool(available),
        'default_model': get_default_model_id(),
        'models': models,
        'message': '请配置 BAILIAN_API_KEY 等环境变量，或在「模型管理」中填写 API Key' if not available else 'API 模型可用',
    })


@app.route('/api/ai/chat', methods=['POST'])
def api_ai_chat():
    global _ai_conversations
    data = request.get_json(silent=True) or {}
    user_message = (data.get('message') or '').strip()
    use_agent = bool(data.get('use_agent', False))
    model_id = (data.get('model') or '').strip()

    if not user_message:
        return jsonify({'success': False, 'error': '请输入问题'})

    uid = _uid() or 0
    if uid not in _ai_conversations:
        _ai_conversations[uid] = []
    conversation = _ai_conversations[uid]

    from modules.ai.inference_policy import (
        LatencyTracker, get_generation_params, try_fast_bypass, rule_based_fallback,
    )
    from modules.ai.model_router import chat as router_chat, get_default_model_id, list_models

    gen = get_generation_params(user_message)
    tracker = LatencyTracker(gen['intent'])

    try:
        bypass = try_fast_bypass(user_message, uid if uid else None)
        if bypass:
            latency_ms = tracker.finish(positive=True)
            reply = bypass['reply']
            conversation.append({'role': 'user', 'content': user_message})
            conversation.append({'role': 'assistant', 'content': reply})
            if len(conversation) > 40:
                _ai_conversations[uid] = conversation[-40:]
            return jsonify({
                'success': True,
                'reply': reply,
                'model': bypass.get('model', 'policy:bypass'),
                'steps': [],
                'actions': bypass.get('actions', []),
                'bypassed': True,
                'intent': bypass.get('intent'),
                'latency_ms': round(latency_ms, 1),
            })

        if not model_id:
            model_id = get_default_model_id()

        available = any(m.get('available') for m in list_models())
        if not available:
            reply = rule_based_fallback(user_message, uid if uid else None)
            reply += '\n\n（尚未配置可用的云端 API Key，请到「模型管理」填写 BAILIAN_API_KEY / DEEPSEEK_API_KEY。）'
            latency_ms = tracker.finish(positive=True)
            conversation.append({'role': 'user', 'content': user_message})
            conversation.append({'role': 'assistant', 'content': reply})
            if len(conversation) > 40:
                _ai_conversations[uid] = conversation[-40:]
            return jsonify({
                'success': True,
                'reply': reply,
                'model': 'policy:fallback',
                'intent': gen['intent'],
                'latency_ms': round(latency_ms, 1),
            })

        if use_agent:
            from modules.ai.agent_engine import run_agent
            try:
                result = run_agent(
                    user_message,
                    model_id=model_id,
                    history=conversation,
                    context={'user_id': uid},
                    max_steps=3,
                    system_prompt=(
                        '你是智能财务系统 AI 助手，可帮助用户查账、审计、协作与跳转页面。'
                        '需要打开功能页时调用 navigate_page。回答简洁专业。'
                    ),
                )
            except Exception:
                result = {
                    'reply': rule_based_fallback(user_message, uid if uid else None),
                    'steps': [], 'model': 'policy:fallback', 'actions': [],
                }
            latency_ms = tracker.finish()
            reply = result['reply']
            conversation.append({'role': 'user', 'content': user_message})
            conversation.append({'role': 'assistant', 'content': reply})
            if len(conversation) > 40:
                _ai_conversations[uid] = conversation[-40:]
            return jsonify({
                'success': True,
                'reply': reply,
                'model': result.get('model', model_id),
                'steps': result.get('steps', []),
                'actions': result.get('actions', []),
                'intent': gen['intent'],
                'latency_ms': round(latency_ms, 1),
            })

        context = _build_ai_context()
        system_prompt = (
            '你是财务智能助手。基于审计上下文简洁回答。'
            '\n\n当前上下文:\n' + context[:1500]
        )
        messages = [{'role': 'system', 'content': system_prompt}]
        messages.extend(conversation[-8:])
        messages.append({'role': 'user', 'content': user_message})
        try:
            reply = router_chat(
                messages,
                model_id=model_id,
                max_tokens=int(gen.get('max_tokens', 384)),
                temperature=float(gen.get('temperature', 0.3)),
            )
        except Exception as api_err:
            reply = rule_based_fallback(user_message, uid if uid else None)
            reply += f'\n\n（API 调用失败: {api_err}）'
        latency_ms = tracker.finish()
        conversation.append({'role': 'user', 'content': user_message})
        conversation.append({'role': 'assistant', 'content': reply})
        if len(conversation) > 40:
            _ai_conversations[uid] = conversation[-40:]
        return jsonify({
            'success': True,
            'reply': reply,
            'model': model_id,
            'intent': gen['intent'],
            'latency_ms': round(latency_ms, 1),
        })

    except Exception as e:
        tracker.finish(positive=False)
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/ai/rate', methods=['POST'])
def api_ai_rate():
    """AI 回复反馈 — 用于在线策略强化学习调参。"""
    from modules.ai.inference_policy import record_outcome
    data = request.get_json(silent=True) or {}
    intent = (data.get('intent') or 'simple_qa').strip()
    rating = data.get('rating')
    latency_ms = float(data.get('latency_ms') or 0)
    if rating is not None:
        record_outcome(intent, latency_ms=latency_ms, rating=int(rating))
    else:
        record_outcome(intent, latency_ms=latency_ms, positive=bool(data.get('positive', True)))
    return jsonify({'success': True})


@app.route('/api/ai/vision', methods=['POST'])
def api_ai_vision():
    """图片表格识别：OCR（本地权重已停用；复杂图请用 Agent + qwen-vl-plus）。"""
    from modules.data_processor import _ocr_image
    import tempfile

    if 'image' not in request.files:
        return jsonify({'success': False, 'error': '未上传图片'})

    image_file = request.files['image']
    try:
        suffix = '.' + image_file.filename.rsplit('.', 1)[1].lower() if '.' in image_file.filename else '.png'
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            image_file.save(tmp.name)
            tmp_path = tmp.name

        ocr_rows = _ocr_image(tmp_path)
        os.unlink(tmp_path)

        if not ocr_rows:
            return jsonify({
                'success': False,
                'error': 'OCR 未能识别出表格。复杂图片请在 Agent 中选用 bailian:qwen-vl-plus。',
            })

        headers = [str(c) for c in ocr_rows[0]]
        rows = [[str(c) for c in row] for row in ocr_rows[1:]] if len(ocr_rows) > 1 else []
        return jsonify({'success': True, 'table': {'columns': headers, 'data': rows}, 'model': 'ocr'})
    except Exception as e:
        return jsonify({'success': False, 'error': f'图片识别失败: {str(e)}'})


# ============================================================
# API - AI Agent 平台
# ============================================================

@app.route('/api/agent/models')
def api_agent_models():
    from modules.ai.model_router import list_models, get_default_model_id
    return jsonify({
        'success': True,
        'default': get_default_model_id(),
        'models': list_models(),
    })


@app.route('/api/agent/extensions')
def api_agent_extensions():
    from modules.ai.registry import list_extensions, list_tools
    ext_type = request.args.get('type')
    return jsonify({
        'success': True,
        'extensions': list_extensions(ext_type),
        'tools': list_tools(),
    })


@app.route('/api/agent/extensions/reload', methods=['POST'])
def api_agent_reload():
    from modules.ai.registry import reload_extensions
    counts = reload_extensions()
    return jsonify({'success': True, 'counts': counts})


@app.route('/api/agent/bots')
def api_agent_bots():
    from modules.ai.bot_engine import list_bots
    return jsonify({'success': True, 'bots': list_bots()})


@app.route('/api/agent/bots/<bot_id>/run', methods=['POST'])
def api_agent_bot_run(bot_id):
    from modules.ai.bot_engine import run_bot
    data = request.get_json(silent=True) or {}
    message = (data.get('message') or '').strip()
    if not message:
        return jsonify({'success': False, 'error': '请输入消息'})
    uid = _uid() or 0
    try:
        result = run_bot(bot_id, message, model_id=data.get('model'), context={'user_id': uid})
        return jsonify({'success': True, **result, 'actions': result.get('actions', [])})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/agent/chat', methods=['POST'])
def api_agent_chat():
    from modules.ai.agent_engine import run_agent
    from modules.ai.bot_engine import run_bot
    from modules.ai.registry import get_extension
    from modules.database import (
        create_agent_conversation, get_agent_conversation,
        save_agent_messages, auto_title_from_message,
    )

    data = request.get_json() or {}
    message = (data.get('message') or '').strip()
    model_id = (data.get('model') or '').strip() or None
    agent_id = (data.get('agent_id') or 'office_assistant').strip()
    bot_id = (data.get('bot_id') or '').strip()
    use_tools = data.get('use_tools', True)
    permission_mode = data.get('permission_mode', 'ask')
    run_mode = data.get('run_mode', 'single')
    conv_id = data.get('conversation_id')
    session_id = f'agent_{_uid() or 0}'

    if not message:
        return jsonify({'success': False, 'error': '请输入消息'})

    uid = _uid() or 0

    if conv_id:
        conv = get_agent_conversation(int(conv_id), uid)
        if not conv:
            return jsonify({'success': False, 'error': '会话不存在'})
        history = conv.get('messages', [])
    else:
        title = auto_title_from_message(message)
        conv = create_agent_conversation(uid, title=title, model_id=model_id)
        conv_id = conv['id']
        history = []

    agent_cfg = get_extension('agent', agent_id) or {}
    system_prompt = agent_cfg.get('system_prompt')
    if model_id is None:
        model_id = agent_cfg.get('model')

    context = {'user_id': uid, 'current_page': data.get('current_page', 'agent')}
    auto_info = {}

    try:
        if bot_id:
            result = run_bot(bot_id, message, model_id=model_id, context=context, history=history)
        elif run_mode == 'auto':
            from modules.ai.commander import classify_task
            auto_info = classify_task(message)
            model_id = auto_info['model']
            result = run_agent(
                message, model_id=model_id, history=history, context=context,
                system_prompt=system_prompt, permission_mode=permission_mode,
                session_id=session_id,
            )
        elif run_mode == 'multi':
            from modules.ai.commander import run_commander
            from modules.ai.model_router import list_models as list_all_models
            all_models = list_all_models()
            available = [m['id'] for m in all_models if m.get('available') and not m.get('auto_discovered')]
            result = run_commander(
                message,
                available_models=available[:6] if available else [model_id or 'bailian:qwen-plus'],
                model_id=model_id or (available[0] if available else None),
                context=context, history=history,
                permission_mode=permission_mode, session_id=session_id,
            )
        elif use_tools:
            result = run_agent(
                message, model_id=model_id, history=history, context=context,
                system_prompt=system_prompt, permission_mode=permission_mode,
                session_id=session_id,
            )
        else:
            from modules.ai.model_router import chat as router_chat
            messages = []
            if system_prompt:
                messages.append({'role': 'system', 'content': system_prompt})
            messages.extend(history[-16:])
            messages.append({'role': 'user', 'content': message})
            reply = router_chat(messages, model_id=model_id)
            result = {'reply': reply, 'steps': [], 'model': model_id, 'finished': True}

        reply_text = _safe_reply(result)
        history.append({'role': 'user', 'content': message})
        history.append({'role': 'assistant', 'content': reply_text})
        save_agent_messages(conv_id, uid, history)

        resp = {'success': True, **result, 'run_mode': run_mode, 'conversation_id': conv_id, 'actions': result.get('actions', [])}
        if run_mode == 'auto' and auto_info:
            resp['auto_model'] = auto_info.get('model')
            resp['auto_reason'] = auto_info.get('reason', '自动选择')
        if run_mode == 'multi':
            resp['multi'] = True
        return jsonify(resp)

    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/agent/upload', methods=['POST'])
def api_agent_upload():
    """Agent 聊天中上传文件（CSV/Excel/图片）。"""
    if 'file' not in request.files:
        return jsonify({'success': False, 'error': '未选择文件'})
    file = request.files['file']
    if file.filename == '':
        return jsonify({'success': False, 'error': '文件名为空'})

    ext = file.filename.rsplit('.', 1)[-1].lower() if '.' in file.filename else ''
    uid = _uid() or 0

    if ext in ('png', 'jpg', 'jpeg', 'gif', 'bmp', 'webp'):
        try:
            result = process_image_upload(file)
            if result.get('success'):
                result = _run_analysis_after_upload(result, source_type='image')
                reply = (
                    f'✅ 已识别图片中的表格数据！\n\n'
                    f'📊 共 {result.get("row_count", 0)} 行\n'
                    f'📋 风险评分: {result.get("score", {}).get("risk_percentage", 0)}%\n\n'
                    f'可以说「帮我分析这些数据」查看详细结果。'
                )
                return jsonify({'success': True, 'reply': reply, 'upload_result': result, 'file_type': 'image'})
            return jsonify({'success': False, 'error': result.get('error', 'OCR识别失败')})
        except Exception as e:
            return jsonify({'success': False, 'error': f'图片处理失败: {str(e)}'})

    if ext in ('csv', 'xls', 'xlsx'):
        try:
            result = process_upload(file)
            if result.get('success'):
                result = _run_analysis_after_upload(result, source_type='file')
                audit_summary = result.get('audit_summary', {})
                score = result.get('score', {})
                reply = (
                    f'✅ 文件 "{file.filename}" 已上传并完成审计分析！\n\n'
                    f'📊 数据规模: {result.get("row_count", 0)} 行\n'
                    f'⚠️ 风险: {score.get("overall_label", "未知")} ({score.get("risk_percentage", 0)}%)\n'
                    f'🔍 发现: 高风险 {audit_summary.get("high_risk", 0)} 项, 中风险 {audit_summary.get("medium_risk", 0)} 项'
                )
                return jsonify({'success': True, 'reply': reply, 'upload_result': result, 'file_type': 'file'})
            return jsonify({'success': False, 'error': result.get('error', '上传失败')})
        except Exception as e:
            return jsonify({'success': False, 'error': f'文件处理失败: {str(e)}'})

    return jsonify({'success': False, 'error': f'不支持的文件格式: .{ext}'})


@app.route('/api/agent/conversations', methods=['GET'])
def api_agent_list_conversations():
    from modules.database import list_agent_conversations
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    return jsonify({'success': True, 'conversations': list_agent_conversations(uid)})


@app.route('/api/agent/conversations', methods=['POST'])
def api_agent_create_conversation():
    from modules.database import create_agent_conversation
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    data = request.get_json(silent=True) or {}
    conv = create_agent_conversation(uid, title=data.get('title', '新对话'), model_id=data.get('model_id'))
    return jsonify({'success': True, 'conversation': conv})


@app.route('/api/agent/conversations/<int:conv_id>', methods=['GET'])
def api_agent_get_conversation(conv_id):
    from modules.database import get_agent_conversation
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    conv = get_agent_conversation(conv_id, uid)
    if not conv:
        return jsonify({'success': False, 'error': '会话不存在'})
    return jsonify({'success': True, 'conversation': conv})


@app.route('/api/agent/conversations/<int:conv_id>', methods=['DELETE'])
def api_agent_delete_conversation(conv_id):
    from modules.database import delete_agent_conversation
    uid = _uid()
    if not uid:
        return jsonify({'success': False, 'error': '请先登录'})
    ok = delete_agent_conversation(conv_id, uid)
    return jsonify({'success': ok, 'error': None if ok else '会话不存在'})


@app.route('/api/agent/permission/allow', methods=['POST'])
def api_agent_permission_allow():
    from modules.ai.permission import add_always_allow
    data = request.get_json() or {}
    tool_name = data.get('tool_name', '')
    remember = data.get('remember', False)
    sid = f'agent_{_uid() or 0}'
    if remember and tool_name:
        add_always_allow(sid, tool_name)
    return jsonify({'success': True, 'tool_name': tool_name, 'remember': remember})


@app.route('/api/agent/models/scan', methods=['GET'])
def api_agent_scan_models():
    from modules.ai.model_router import scan_local_endpoints
    discovered = scan_local_endpoints()
    return jsonify({'success': True, 'discovered': discovered, 'count': len(discovered)})


@app.route('/api/agent/models/config', methods=['POST'])
def api_agent_add_model():
    from modules.ai.model_router import add_model
    data = request.get_json() or {}
    result = add_model(data)
    return jsonify(result)


@app.route('/api/agent/models/<path:model_id>', methods=['DELETE'])
def api_agent_delete_model(model_id):
    from modules.ai.model_router import delete_model
    result = delete_model(model_id)
    return jsonify(result)


@app.route('/api/agent/models/apikey', methods=['POST'])
def api_agent_set_apikey():
    from modules.ai.model_router import update_api_key
    data = request.get_json() or {}
    result = update_api_key(data.get('model_id', ''), data.get('api_key', ''))
    return jsonify(result)


@app.route('/api/agent/workflows')
def api_agent_workflows():
    from modules.ai.workflow_engine import list_workflows
    return jsonify({'success': True, 'workflows': list_workflows()})


@app.route('/api/agent/workflows/<workflow_id>/run', methods=['POST'])
def api_agent_run_workflow(workflow_id):
    from modules.ai.workflow_engine import run_workflow

    data = request.get_json(silent=True) or {}
    try:
        result = run_workflow(
            workflow_id,
            inputs=data.get('inputs'),
            model_id=data.get('model'),
            context={'user_id': _uid()},
        )
        return jsonify({'success': result.get('success', True), **result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/agent/clear', methods=['POST'])
def api_agent_clear():
    uid = _uid()
    if uid and uid in _agent_conversations:
        del _agent_conversations[uid]
    return jsonify({'success': True})


# ============================================================
# API - Agent 扩展开发工作室
# ============================================================

@app.route('/api/agent/develop/files')
def api_agent_develop_files():
    from modules.ai.dev_studio import list_type_files
    ext_type = request.args.get('type', 'skill')
    return jsonify({'success': True, 'type': ext_type, 'files': list_type_files(ext_type)})


@app.route('/api/agent/develop/file')
def api_agent_develop_read():
    from modules.ai.dev_studio import read_file
    path = request.args.get('path', '')
    if not path:
        return jsonify({'success': False, 'error': '缺少 path'})
    try:
        return jsonify({'success': True, **read_file(path)})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/agent/develop/file', methods=['POST'])
def api_agent_develop_save():
    from modules.ai.dev_studio import write_file
    data = request.get_json(silent=True) or {}
    path = (data.get('path') or '').strip()
    content = data.get('content', '')
    if not path:
        return jsonify({'success': False, 'error': '缺少 path'})
    try:
        result = write_file(path, content)
        return jsonify({'success': True, **result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/agent/develop/scaffold', methods=['POST'])
def api_agent_develop_scaffold():
    from modules.ai import dev_studio as ds
    data = request.get_json(silent=True) or {}
    ext_type = data.get('type', 'skill')
    ext_id = (data.get('id') or '').strip()
    name = (data.get('name') or '').strip()
    try:
        if ext_type == 'skill':
            result = ds.scaffold_skill(ext_id, name, data.get('description', ''), data.get('author', ''))
        elif ext_type == 'mcp':
            result = ds.scaffold_mcp(ext_id, name, data.get('url', ''))
        elif ext_type == 'workflow':
            result = ds.scaffold_workflow(ext_id, name)
        elif ext_type == 'agent':
            result = ds.scaffold_agent(ext_id, name)
        elif ext_type == 'miniprogram':
            result = ds.scaffold_miniprogram(ext_id, name, data.get('description', ''))
        else:
            return jsonify({'success': False, 'error': f'未知类型: {ext_type}'})
        return jsonify({'success': True, **result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


@app.route('/api/agent/develop/test-skill', methods=['POST'])
def api_agent_develop_test_skill():
    from modules.ai.dev_studio import test_skill
    data = request.get_json(silent=True) or {}
    skill_id = (data.get('skill_id') or '').strip()
    if not skill_id:
        return jsonify({'success': False, 'error': '缺少 skill_id'})
    try:
        args = data.get('args') or {}
        if isinstance(args, str):
            args = json.loads(args)
        result = test_skill(skill_id, args, {'user_id': _uid()})
        return jsonify({'success': True, 'result': result})
    except Exception as e:
        return jsonify({'success': False, 'error': str(e)})


# ============================================================
# API - 历史记录
# ============================================================

@app.route('/api/history')
def api_history_list():
    """历史记录列表，支持 ?q=关键词&source_type=file|image|import&limit=50"""
    q = (request.args.get('q') or '').strip() or None
    source_type = (request.args.get('source_type') or '').strip() or None
    if source_type and source_type not in ('file', 'image', 'import'):
        source_type = None
    try:
        limit = min(int(request.args.get('limit', 50)), 200)
    except (TypeError, ValueError):
        limit = 50
    records = list_history(
        limit=limit,
        user_id=_uid(),
        q=q,
        source_type=source_type,
    )
    return jsonify({'success': True, 'records': records, 'total': len(records)})


@app.route('/api/history/<int:record_id>')
def api_history_detail(record_id):
    record = get_history_record(record_id, user_id=_uid())
    if not record:
        return jsonify({'success': False, 'error': '历史记录不存在'})
    return jsonify({
        'success': True,
        'record': {
            'id': record['id'],
            'title': record['title'],
            'source_type': record['source_type'],
            'filename': record['filename'],
            'row_count': record['row_count'],
            'column_count': record['column_count'],
            'summary': record['summary'],
            'score': record['score'],
            'created_at': record['created_at'],
        },
    })


@app.route('/api/history/<int:record_id>/load', methods=['POST'])
def api_history_load(record_id):
    """加载历史记录到当前会话"""
    global _analysis_cache
    record = get_history_record(record_id, user_id=_uid())
    if not record:
        return jsonify({'success': False, 'error': '历史记录不存在'})

    table_id = restore_table_from_df(record['df'], record['filename'] or record['title'])
    _analysis_cache = {
        'audit_results': record['audit_results'],
        'audit_summary': get_rule_summary(record['audit_results']),
        'anomaly_results': record['anomaly_results'],
        'score': record['score'],
        'preview_data': record['df'].head(100).fillna('').to_dict(orient='records'),
        'preview_columns': list(record['df'].columns),
        'phase1_results': record.get('phase1_results', {}),
        'phase2_results': record.get('phase2_results', {}),
        'phase3_results': record.get('phase3_results', {}),
        'history_id': record_id,
    }

    # 恢复 v2 评分
    if record.get('phase1_results') or record.get('phase2_results') or record.get('phase3_results'):
        try:
            _analysis_cache['score_v2'] = calculate_overall_score_v2(
                record['audit_results'],
                record['anomaly_results'],
                record.get('phase1_results'),
                record.get('phase2_results'),
                record.get('phase3_results'),
            )
        except Exception:
            pass

    return jsonify({
        'success': True,
        'table_id': table_id,
        'active_table_id': table_id,
        'tables': get_tables(),
        'summary': record['summary'],
        'audit_summary': _analysis_cache['audit_summary'],
        'score': record['score'],
        'history_id': record_id,
    })


@app.route('/api/history/<int:record_id>', methods=['DELETE'])
def api_history_delete(record_id):
    ok = delete_history_record(record_id, user_id=_uid())
    return jsonify({'success': ok, 'error': None if ok else '记录不存在'})


# ============================================================
# 启动
# ============================================================

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    debug = os.environ.get('FLASK_DEBUG', '0') == '1'
    print('=' * 60)
    print('  财务大数据审计系统 v2.1')
    print(f'  访问地址: http://localhost:{port}')
    print('  流程: 上传数据 → 编辑确认 → 仪表盘/预览/分析 → 报告')
    print('=' * 60)
    app.run(debug=debug, host='0.0.0.0', port=port)
