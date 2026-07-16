"""
用户认证：密码校验、记住登录、路由保护
"""
from __future__ import annotations

import secrets
from datetime import datetime, timedelta
from functools import wraps

from flask import session, request, redirect, url_for, jsonify, g
from werkzeug.security import generate_password_hash, check_password_hash

from modules.database import (
    create_user as db_create_user,
    get_user_by_username,
    get_user_by_id,
    create_auth_token,
    get_user_by_token,
    delete_auth_token,
    update_user_profile,
    auto_friend_same_company,
)
from modules.roles import resolve_registration_profile

REMEMBER_COOKIE = 'audit_remember'
REMEMBER_DAYS = 30


def hash_password(password: str) -> str:
    return generate_password_hash(password)


def verify_password(password_hash: str, password: str) -> bool:
    return check_password_hash(password_hash, password)


def register_user(username: str, password: str, profile: dict | None = None) -> tuple[bool, str, int | None]:
    username = (username or '').strip()
    if len(username) < 2:
        return False, '用户名至少 2 个字符', None
    if len(password) < 4:
        return False, '密码至少 4 个字符', None
    if get_user_by_username(username):
        return False, '用户名已存在', None
    try:
        resolved = resolve_registration_profile(profile or {})
    except ValueError as exc:
        return False, str(exc), None
    user_id = db_create_user(
        username,
        hash_password(password),
        role=resolved['role'],
        theme=resolved['theme'],
        page_style=resolved['page_style'],
        preferences=resolved['preferences'],
        company=resolved.get('company') or '',
    )
    company = (resolved.get('company') or '').strip()
    if company:
        auto_friend_same_company(user_id, company)
    return True, '注册成功', user_id


def authenticate_user(username: str, password: str) -> tuple[bool, str, dict | None]:
    user = get_user_by_username((username or '').strip())
    if not user or not verify_password(user['password_hash'], password):
        return False, '用户名或密码错误', None
    return True, '登录成功', user


def login_user(user: dict, remember: bool = True) -> str | None:
    """写入 session，可选生成记住登录 token，返回 token 明文"""
    session.clear()
    session['user_id'] = user['id']
    session['username'] = user['username']
    session['user_role'] = user.get('role', 'normal_user')
    session.permanent = remember
    # 清空上一个用户的残留数据
    _clear_app_data()
    token = None
    if remember:
        token = secrets.token_urlsafe(32)
        create_auth_token(user['id'], token, REMEMBER_DAYS)
    return token


def logout_user(token: str | None = None) -> None:
    if token:
        delete_auth_token(token)
    session.clear()
    # 清空内存中的数据表和分析缓存
    _clear_app_data()


def _clear_app_data() -> None:
    """清空 app.py 和 data_processor 中的模块级数据"""
    try:
        from modules.data_processor import _tables, _active_table_id
        _tables.clear()
        # 不能直接改全局变量，通过 data_processor 的接口清理
    except Exception:
        pass
    try:
        import app as _app
        _app._analysis_cache.clear()
        if hasattr(_app, '_ai_conversations'):
            _app._ai_conversations.clear()
    except Exception:
        pass


def restore_user_from_remember(token: str | None) -> bool:
    if not token:
        return False
    user = get_user_by_token(token)
    if not user:
        return False
    session['user_id'] = user['id']
    session['username'] = user['username']
    session.permanent = True
    return True


def get_current_user() -> dict | None:
    user_id = session.get('user_id')
    if not user_id:
        return None
    return get_user_by_id(user_id)


def login_required(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        if g.get('current_user'):
            return view(*args, **kwargs)
        if request.path.startswith('/api/'):
            return jsonify({'success': False, 'error': '请先登录', 'login_required': True}), 401
        return redirect(url_for('login_page', next=request.path))
    return wrapped
