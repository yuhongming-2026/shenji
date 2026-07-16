"""
审计历史记录 - SQLite 持久化存储
"""
from __future__ import annotations

import os
import json
import sqlite3
import hashlib
import threading
from datetime import datetime, timedelta
from typing import Any

import numpy as np
import pandas as pd


class _NumpyJSONEncoder(json.JSONEncoder):
    """兼容 numpy 类型的 JSON 编码器"""

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


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False, cls=_NumpyJSONEncoder)

DB_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'data')
DB_PATH = os.path.join(DB_DIR, 'audit_history.db')
_db_initialized = False
_init_lock = threading.Lock()


def _connect() -> sqlite3.Connection:
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute('PRAGMA journal_mode=WAL')
    conn.execute('PRAGMA synchronous=NORMAL')
    conn.execute('PRAGMA busy_timeout=30000')
    return conn


def _ensure_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    cols = {row[1] for row in conn.execute(f'PRAGMA table_info({table})')}
    if column not in cols:
        conn.execute(f'ALTER TABLE {table} ADD COLUMN {column} {definition}')


def init_db() -> None:
    """初始化 SQLite：用户表、记住登录 token 表、审计历史记录表、审计发现表、审计底稿表、好友表、消息表"""
    global _db_initialized
    if _db_initialized:
        return
    with _init_lock:
        if _db_initialized:
            return
        _init_db_schema()
        _db_initialized = True


def _init_db_schema() -> None:
    with _connect() as conn:
        conn.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                username TEXT NOT NULL UNIQUE,
                password_hash TEXT NOT NULL,
                created_at TEXT NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS auth_tokens (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                token_hash TEXT NOT NULL UNIQUE,
                expires_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS history_records (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                title TEXT NOT NULL,
                source_type TEXT NOT NULL DEFAULT 'file',
                filename TEXT,
                row_count INTEGER DEFAULT 0,
                column_count INTEGER DEFAULT 0,
                table_data TEXT,
                summary TEXT,
                audit_results TEXT,
                anomaly_results TEXT,
                score TEXT,
                phase1_results TEXT,
                phase2_results TEXT,
                phase3_results TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS audit_findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                history_id INTEGER NOT NULL,
                user_id INTEGER,
                phase TEXT NOT NULL,
                procedure_name TEXT NOT NULL,
                risk_level TEXT NOT NULL DEFAULT 'low',
                findings_json TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (history_id) REFERENCES history_records(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS audit_workpapers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                history_id INTEGER NOT NULL,
                user_id INTEGER,
                workpaper_type TEXT NOT NULL,
                title TEXT NOT NULL,
                data_json TEXT NOT NULL,
                conclusion TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (history_id) REFERENCES history_records(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        # --- 好友系统 ---
        conn.execute('''
            CREATE TABLE IF NOT EXISTS friends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                friend_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (friend_id) REFERENCES users(id),
                UNIQUE(user_id, friend_id)
            )
        ''')
        # --- 文件共享 ---
        conn.execute('''
            CREATE TABLE IF NOT EXISTS shared_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                file_type TEXT DEFAULT '',
                is_read INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (sender_id) REFERENCES users(id),
                FOREIGN KEY (receiver_id) REFERENCES users(id)
            )
        ''')
        # --- 即时消息 ---
        conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (sender_id) REFERENCES users(id),
                FOREIGN KEY (receiver_id) REFERENCES users(id)
            )
        ''')
        _ensure_column(conn, 'history_records', 'user_id', 'INTEGER')
        _ensure_column(conn, 'history_records', 'phase1_results', 'TEXT')
        _ensure_column(conn, 'history_records', 'phase2_results', 'TEXT')
        _ensure_column(conn, 'history_records', 'phase3_results', 'TEXT')
        _ensure_column(conn, 'users', 'role', "TEXT NOT NULL DEFAULT 'normal_user'")
        _ensure_column(conn, 'users', 'theme', "TEXT NOT NULL DEFAULT 'default'")
        _ensure_column(conn, 'users', 'page_style', "TEXT NOT NULL DEFAULT 'classic'")
        _ensure_column(conn, 'users', 'preferences', "TEXT NOT NULL DEFAULT '{}'")
        _ensure_column(conn, 'users', 'company', "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, 'messages', 'is_read', 'INTEGER DEFAULT 0')
        _ensure_column(conn, 'messages', 'msg_type', "TEXT NOT NULL DEFAULT 'text'")
        _ensure_column(conn, 'messages', 'media_url', "TEXT NOT NULL DEFAULT ''")
        _ensure_column(conn, 'collab_sessions', 'source_table_id', 'TEXT')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS notifications (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                ntype TEXT NOT NULL,
                title TEXT NOT NULL,
                body TEXT,
                link TEXT,
                is_read INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER,
                page TEXT,
                rating INTEGER DEFAULT 0,
                message TEXT NOT NULL,
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS collab_sessions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                token TEXT NOT NULL UNIQUE,
                owner_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                table_data TEXT NOT NULL,
                version INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (owner_id) REFERENCES users(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS collab_members (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                session_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                joined_at TEXT NOT NULL,
                FOREIGN KEY (session_id) REFERENCES collab_sessions(id),
                FOREIGN KEY (user_id) REFERENCES users(id),
                UNIQUE(session_id, user_id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS collab_presence (
                session_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                last_seen TEXT NOT NULL,
                PRIMARY KEY (session_id, user_id),
                FOREIGN KEY (session_id) REFERENCES collab_sessions(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        _ensure_column(conn, 'collab_presence', 'editing_row', 'INTEGER')
        _ensure_column(conn, 'collab_presence', 'editing_column', 'TEXT')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS agent_conversations (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL DEFAULT '新对话',
                messages_json TEXT NOT NULL DEFAULT '[]',
                model_id TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS working_tables (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                table_key TEXT NOT NULL,
                filename TEXT NOT NULL DEFAULT '',
                table_json TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(user_id, table_key),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS fin_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                category TEXT NOT NULL,
                parent_code TEXT,
                balance REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, code),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS fin_periods (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                name TEXT NOT NULL,
                start_date TEXT NOT NULL,
                end_date TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS fin_vouchers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                period_id INTEGER,
                voucher_no TEXT NOT NULL,
                voucher_date TEXT NOT NULL,
                summary TEXT,
                status TEXT NOT NULL DEFAULT 'draft',
                total_debit REAL NOT NULL DEFAULT 0,
                total_credit REAL NOT NULL DEFAULT 0,
                created_by INTEGER,
                created_at TEXT NOT NULL,
                posted_at TEXT,
                UNIQUE(user_id, voucher_no),
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (period_id) REFERENCES fin_periods(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS fin_voucher_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                voucher_id INTEGER NOT NULL,
                line_no INTEGER NOT NULL,
                account_code TEXT NOT NULL,
                account_name TEXT,
                summary TEXT,
                debit REAL NOT NULL DEFAULT 0,
                credit REAL NOT NULL DEFAULT 0,
                FOREIGN KEY (voucher_id) REFERENCES fin_vouchers(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS call_rooms (
                room_key TEXT PRIMARY KEY,
                caller_id INTEGER NOT NULL,
                callee_id INTEGER NOT NULL,
                offer TEXT,
                answer TEXT,
                caller_ice TEXT NOT NULL DEFAULT '[]',
                callee_ice TEXT NOT NULL DEFAULT '[]',
                status TEXT NOT NULL DEFAULT 'ringing',
                updated_at REAL NOT NULL
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS audit_findings (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                history_id INTEGER NOT NULL,
                user_id INTEGER,
                phase TEXT NOT NULL,
                procedure_name TEXT NOT NULL,
                risk_level TEXT NOT NULL DEFAULT 'low',
                findings_json TEXT NOT NULL,
                description TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (history_id) REFERENCES history_records(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        conn.execute('''
            CREATE TABLE IF NOT EXISTS audit_workpapers (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                history_id INTEGER NOT NULL,
                user_id INTEGER,
                workpaper_type TEXT NOT NULL,
                title TEXT NOT NULL,
                data_json TEXT NOT NULL,
                conclusion TEXT,
                created_at TEXT NOT NULL,
                FOREIGN KEY (history_id) REFERENCES history_records(id),
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
        ''')
        # --- 好友系统 ---
        conn.execute('''
            CREATE TABLE IF NOT EXISTS friends (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                friend_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id),
                FOREIGN KEY (friend_id) REFERENCES users(id),
                UNIQUE(user_id, friend_id)
            )
        ''')
        # --- 文件共享 ---
        conn.execute('''
            CREATE TABLE IF NOT EXISTS shared_files (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                original_name TEXT NOT NULL,
                stored_name TEXT NOT NULL,
                file_size INTEGER DEFAULT 0,
                file_type TEXT DEFAULT '',
                is_read INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (sender_id) REFERENCES users(id),
                FOREIGN KEY (receiver_id) REFERENCES users(id)
            )
        ''')
        # --- 即时消息 ---
        conn.execute('''
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                sender_id INTEGER NOT NULL,
                receiver_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                is_read INTEGER DEFAULT 0,
                created_at TEXT NOT NULL,
                FOREIGN KEY (sender_id) REFERENCES users(id),
                FOREIGN KEY (receiver_id) REFERENCES users(id)
            )
        ''')
        _ensure_column(conn, 'history_records', 'user_id', 'INTEGER')
        _ensure_column(conn, 'history_records', 'phase1_results', 'TEXT')
        _ensure_column(conn, 'history_records', 'phase2_results', 'TEXT')
        _ensure_column(conn, 'history_records', 'phase3_results', 'TEXT')
        _ensure_column(conn, 'collab_presence', 'editing_row', 'INTEGER')
        _ensure_column(conn, 'collab_presence', 'editing_column', 'TEXT')
        conn.commit()


# ---- 用户 ----

def create_user(
    username: str,
    password_hash: str,
    role: str = 'normal_user',
    theme: str = 'default',
    page_style: str = 'classic',
    preferences: str | dict | None = None,
    company: str = '',
) -> int:
    init_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if isinstance(preferences, dict):
        preferences = _json_dumps(preferences)
    preferences = preferences or '{}'
    company = (company or '').strip()
    with _connect() as conn:
        cur = conn.execute(
            '''INSERT INTO users (username, password_hash, created_at, role, theme, page_style, preferences, company)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (username, password_hash, now, role, theme, page_style, preferences, company),
        )
        conn.commit()
        return int(cur.lastrowid)


def update_user_profile(user_id: int, **fields) -> bool:
    init_db()
    allowed = {'role', 'theme', 'page_style', 'preferences', 'company'}
    updates = {k: v for k, v in fields.items() if k in allowed and v is not None}
    if not updates:
        return False
    if 'preferences' in updates and isinstance(updates['preferences'], dict):
        updates['preferences'] = _json_dumps(updates['preferences'])
    sets = ', '.join(f'{k}=?' for k in updates)
    with _connect() as conn:
        conn.execute(
            f'UPDATE users SET {sets} WHERE id=?',
            [*updates.values(), user_id],
        )
        conn.commit()
    return True


def auto_friend_same_company(user_id: int, company: str) -> int:
    """同公司用户自动成为双向已接受好友，返回新建/更新数量。"""
    company = (company or '').strip()
    if not company or not user_id:
        return 0
    init_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    count = 0
    with _connect() as conn:
        peers = conn.execute(
            'SELECT id FROM users WHERE company=? AND id!=? AND TRIM(company) != ""',
            (company, user_id),
        ).fetchall()
        for p in peers:
            peer_id = int(p['id'])
            existing = conn.execute(
                '''SELECT id, status FROM friends
                   WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)''',
                (user_id, peer_id, peer_id, user_id),
            ).fetchone()
            if existing:
                if existing['status'] != 'accepted':
                    conn.execute('UPDATE friends SET status=? WHERE id=?', ('accepted', existing['id']))
                    count += 1
            else:
                conn.execute(
                    'INSERT INTO friends (user_id, friend_id, status, created_at) VALUES (?, ?, ?, ?)',
                    (user_id, peer_id, 'accepted', now),
                )
                count += 1
        conn.commit()
    return count


def list_company_colleagues(user_id: int) -> list[dict]:
    """同公司同事（含已是好友的），用于聊天联系人。"""
    init_db()
    with _connect() as conn:
        me = conn.execute('SELECT company FROM users WHERE id=?', (user_id,)).fetchone()
        company = (me['company'] if me else '') or ''
        company = company.strip()
        if not company:
            return []
        rows = conn.execute(
            '''SELECT id, username, role, company FROM users
               WHERE company=? AND id!=? ORDER BY username''',
            (company, user_id),
        ).fetchall()
    return [dict(r) for r in rows]

def get_user_by_username(username: str) -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute('SELECT * FROM users WHERE username = ?', (username,)).fetchone()
    return dict(row) if row else None


def get_user_by_id(user_id: int) -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute('SELECT * FROM users WHERE id = ?', (user_id,)).fetchone()
    return dict(row) if row else None


def _hash_token(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def create_auth_token(user_id: int, token: str, days: int = 30) -> None:
    init_db()
    now = datetime.now()
    expires = now + timedelta(days=days)
    with _connect() as conn:
        conn.execute(
            '''INSERT INTO auth_tokens (user_id, token_hash, expires_at, created_at)
               VALUES (?, ?, ?, ?)''',
            (user_id, _hash_token(token), expires.strftime('%Y-%m-%d %H:%M:%S'),
             now.strftime('%Y-%m-%d %H:%M:%S')),
        )
        conn.commit()


def get_user_by_token(token: str) -> dict | None:
    init_db()
    token_hash = _hash_token(token)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with _connect() as conn:
        row = conn.execute(
            '''SELECT u.* FROM users u
               JOIN auth_tokens t ON t.user_id = u.id
               WHERE t.token_hash = ? AND t.expires_at > ?''',
            (token_hash, now),
        ).fetchone()
    return dict(row) if row else None


def delete_auth_token(token: str) -> None:
    init_db()
    with _connect() as conn:
        conn.execute('DELETE FROM auth_tokens WHERE token_hash = ?', (_hash_token(token),))
        conn.commit()


# ---- 历史记录 ----

def save_history_record(
    title: str,
    source_type: str,
    filename: str,
    df: pd.DataFrame,
    summary: dict | None = None,
    audit_results: list | None = None,
    anomaly_results: dict | None = None,
    score: dict | None = None,
    user_id: int | None = None,
    phase1_results: dict | None = None,
    phase2_results: dict | None = None,
    phase3_results: dict | None = None,
) -> int:
    """保存一条历史记录，返回 record id"""
    init_db()
    table_json = _json_dumps({
        'columns': list(df.columns),
        'rows': df.fillna('').astype(str).values.tolist(),
    })

    with _connect() as conn:
        cur = conn.execute(
            '''INSERT INTO history_records
               (user_id, title, source_type, filename, row_count, column_count,
                table_data, summary, audit_results, anomaly_results, score,
                phase1_results, phase2_results, phase3_results, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                user_id,
                title,
                source_type,
                filename,
                len(df),
                len(df.columns),
                table_json,
                _json_dumps(summary or {}),
                _json_dumps(audit_results or []),
                _json_dumps(anomaly_results or {}),
                _json_dumps(score or {}),
                _json_dumps(phase1_results or {}),
                _json_dumps(phase2_results or {}),
                _json_dumps(phase3_results or {}),
                datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            ),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_history(
    limit: int = 50,
    user_id: int | None = None,
    q: str | None = None,
    source_type: str | None = None,
) -> list[dict]:
    """
    查询历史记录列表（不含完整 table_data，减轻传输量）。

    Args:
        limit: 返回条数上限
        user_id: 仅返回该用户的数据；None 表示不过滤用户
        q: 关键词，模糊匹配 title / filename
        source_type: 来源类型筛选：file / image / import
    """
    init_db()
    conditions: list[str] = []
    params: list[Any] = []

    if user_id is not None:
        conditions.append('user_id = ?')
        params.append(user_id)
    if q:
        # LIKE 通配符转义，避免用户输入 % _ 影响查询
        safe_q = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
        conditions.append('(title LIKE ? ESCAPE \'\\\' OR filename LIKE ? ESCAPE \'\\\')')
        like = f'%{safe_q}%'
        params.extend([like, like])
    if source_type:
        conditions.append('source_type = ?')
        params.append(source_type)

    where_clause = f" WHERE {' AND '.join(conditions)}" if conditions else ''
    sql = f'''SELECT id, title, source_type, filename, row_count, column_count,
                     summary, score, created_at
              FROM history_records{where_clause}
              ORDER BY id DESC LIMIT ?'''
    params.append(limit)

    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        try:
            item['summary'] = json.loads(item.pop('summary') or '{}')
        except Exception:
            item['summary'] = {}
        try:
            item['score'] = json.loads(item.pop('score') or '{}')
        except Exception:
            item['score'] = {}
        result.append(item)
    return result


def get_history_record(record_id: int, user_id: int | None = None) -> dict | None:
    """读取单条完整历史（含 DataFrame），用于加载到当前会话"""
    init_db()
    with _connect() as conn:
        if user_id is not None:
            row = conn.execute(
                'SELECT * FROM history_records WHERE id = ? AND user_id = ?',
                (record_id, user_id),
            ).fetchone()
        else:
            row = conn.execute(
                'SELECT * FROM history_records WHERE id = ?', (record_id,)
            ).fetchone()
    if not row:
        return None

    data = dict(row)
    table = json.loads(data['table_data'] or '{}')
    df = pd.DataFrame(table.get('rows', []), columns=table.get('columns', []))
    data['df'] = df
    data['summary'] = json.loads(data['summary'] or '{}')
    data['audit_results'] = json.loads(data['audit_results'] or '[]')
    data['anomaly_results'] = json.loads(data['anomaly_results'] or '{}')
    data['score'] = json.loads(data['score'] or '{}')
    data['phase1_results'] = json.loads(data.get('phase1_results') or '{}')
    data['phase2_results'] = json.loads(data.get('phase2_results') or '{}')
    data['phase3_results'] = json.loads(data.get('phase3_results') or '{}')
    del data['table_data']
    return data


def delete_history_record(record_id: int, user_id: int | None = None) -> bool:
    init_db()
    with _connect() as conn:
        if user_id is not None:
            cur = conn.execute(
                'DELETE FROM history_records WHERE id = ? AND user_id = ?',
                (record_id, user_id),
            )
        else:
            cur = conn.execute('DELETE FROM history_records WHERE id = ?', (record_id,))
        conn.commit()
        return cur.rowcount > 0


# ---- 审计发现 ----

def save_audit_findings(
    history_id: int,
    phase: str,
    findings_list: list[dict],
    user_id: int | None = None,
) -> list[int]:
    """批量保存审计发现，返回 ID 列表"""
    init_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    ids = []
    with _connect() as conn:
        for f in findings_list:
            cur = conn.execute(
                '''INSERT INTO audit_findings
                   (history_id, user_id, phase, procedure_name, risk_level,
                    findings_json, description, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
                (
                    history_id,
                    user_id,
                    phase,
                    f.get('procedure_name', f.get('name', 'unknown')),
                    f.get('risk_level', f.get('risk', 'low')),
                    _json_dumps(f),
                    f.get('description', ''),
                    now,
                ),
            )
            ids.append(int(cur.lastrowid))
        conn.commit()
    return ids


def get_audit_findings(
    history_id: int | None = None,
    phase: str | None = None,
    user_id: int | None = None,
) -> list[dict]:
    """查询审计发现"""
    init_db()
    conditions = []
    params: list[Any] = []
    if history_id is not None:
        conditions.append('history_id = ?')
        params.append(history_id)
    if phase is not None:
        conditions.append('phase = ?')
        params.append(phase)
    if user_id is not None:
        conditions.append('user_id = ?')
        params.append(user_id)

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ''
    with _connect() as conn:
        rows = conn.execute(
            f'SELECT * FROM audit_findings{where} ORDER BY risk_level DESC, id DESC',
            params,
        ).fetchall()

    results = []
    for r in rows:
        item = dict(r)
        try:
            item['findings'] = json.loads(item.pop('findings_json') or '{}')
        except Exception:
            item['findings'] = {}
        results.append(item)
    return results


def delete_audit_findings(history_id: int) -> bool:
    """删除指定历史记录的所有审计发现"""
    init_db()
    with _connect() as conn:
        cur = conn.execute('DELETE FROM audit_findings WHERE history_id = ?', (history_id,))
        conn.commit()
    return cur.rowcount > 0


# ---- 审计底稿 ----

def save_workpaper(
    history_id: int,
    workpaper_type: str,
    title: str,
    data: dict,
    conclusion: str = '',
    user_id: int | None = None,
) -> int:
    """保存审计底稿，返回 ID"""
    init_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with _connect() as conn:
        cur = conn.execute(
            '''INSERT INTO audit_workpapers
               (history_id, user_id, workpaper_type, title, data_json, conclusion, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (history_id, user_id, workpaper_type, title, _json_dumps(data), conclusion, now),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_workpapers(
    history_id: int | None = None,
    workpaper_type: str | None = None,
    user_id: int | None = None,
) -> list[dict]:
    """查询审计底稿"""
    init_db()
    conditions = []
    params: list[Any] = []
    if history_id is not None:
        conditions.append('history_id = ?')
        params.append(history_id)
    if workpaper_type is not None:
        conditions.append('workpaper_type = ?')
        params.append(workpaper_type)
    if user_id is not None:
        conditions.append('user_id = ?')
        params.append(user_id)

    where = f" WHERE {' AND '.join(conditions)}" if conditions else ''
    with _connect() as conn:
        rows = conn.execute(
            f'SELECT * FROM audit_workpapers{where} ORDER BY id DESC',
            params,
        ).fetchall()

    results = []
    for r in rows:
        item = dict(r)
        try:
            item['data'] = json.loads(item.pop('data_json') or '{}')
        except Exception:
            item['data'] = {}
        results.append(item)
    return results


def delete_workpaper(workpaper_id: int) -> bool:
    """删除审计底稿"""
    init_db()
    with _connect() as conn:
        cur = conn.execute('DELETE FROM audit_workpapers WHERE id = ?', (workpaper_id,))
        conn.commit()
    return cur.rowcount > 0


# ---- 用户搜索 ----

def search_users(q: str, exclude_id: int | None = None, limit: int = 20) -> list[dict]:
    """搜索用户（模糊匹配 username）"""
    init_db()
    safe_q = q.replace('\\', '\\\\').replace('%', '\\%').replace('_', '\\_')
    like = f'%{safe_q}%'
    if exclude_id is not None:
        rows = _connect().execute(
            '''SELECT id, username, created_at FROM users
               WHERE username LIKE ? ESCAPE '\\' AND id != ?
               ORDER BY username LIMIT ?''',
            (like, exclude_id, limit),
        ).fetchall()
    else:
        rows = _connect().execute(
            '''SELECT id, username, created_at FROM users
               WHERE username LIKE ? ESCAPE '\\'
               ORDER BY username LIMIT ?''',
            (like, limit),
        ).fetchall()
    return [dict(r) for r in rows]


# ---- 好友系统 ----

def send_friend_request(user_id: int, friend_id: int) -> dict:
    """发送好友申请，返回 {success, error, status}"""
    init_db()
    if user_id == friend_id:
        return {'success': False, 'error': '不能添加自己为好友'}
    with _connect() as conn:
        # 检查是否已存在
        existing = conn.execute(
            'SELECT * FROM friends WHERE (user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?)',
            (user_id, friend_id, friend_id, user_id),
        ).fetchone()
        if existing:
            e = dict(existing)
            if e['status'] == 'accepted':
                return {'success': False, 'error': '已经是好友'}
            if e['status'] == 'pending' and e['user_id'] == user_id:
                return {'success': False, 'error': '已发送过申请，请等待对方同意'}
            if e['status'] == 'pending' and e['friend_id'] == user_id:
                # 对方已向你发送申请，自动接受
                conn.execute(
                    'UPDATE friends SET status = ? WHERE id = ?',
                    ('accepted', e['id']),
                )
                conn.commit()
                return {'success': True, 'status': 'accepted', 'message': '已自动接受对方的好友申请'}
            if e['status'] == 'rejected':
                conn.execute('DELETE FROM friends WHERE id = ?', (e['id'],))
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        conn.execute(
            'INSERT INTO friends (user_id, friend_id, status, created_at) VALUES (?, ?, ?, ?)',
            (user_id, friend_id, 'pending', now),
        )
        conn.commit()
        return {'success': True, 'status': 'pending', 'message': '好友申请已发送'}


def accept_friend_request(user_id: int, request_id: int) -> dict:
    """接受好友申请"""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            'SELECT * FROM friends WHERE id=? AND friend_id=? AND status=?',
            (request_id, user_id, 'pending'),
        ).fetchone()
        if not row:
            return {'success': False, 'error': '申请不存在或已处理'}
        conn.execute('UPDATE friends SET status=? WHERE id=?', ('accepted', request_id))
        conn.commit()
        return {'success': True, 'message': '已接受好友申请'}


def reject_friend_request(user_id: int, request_id: int) -> dict:
    """拒绝好友申请"""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            'SELECT * FROM friends WHERE id=? AND friend_id=? AND status=?',
            (request_id, user_id, 'pending'),
        ).fetchone()
        if not row:
            return {'success': False, 'error': '申请不存在或已处理'}
        conn.execute('DELETE FROM friends WHERE id=?', (request_id,))
        conn.commit()
        return {'success': True, 'message': '已拒绝好友申请'}


def remove_friend(user_id: int, friend_id: int) -> dict:
    """删除好友"""
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            '''DELETE FROM friends WHERE
               (user_id=? AND friend_id=? AND status=?)
               OR (user_id=? AND friend_id=? AND status=?)''',
            (user_id, friend_id, 'accepted', friend_id, user_id, 'accepted'),
        )
        conn.commit()
        if cur.rowcount > 0:
            return {'success': True, 'message': '已删除好友'}
        return {'success': False, 'error': '好友关系不存在'}


def get_friends(user_id: int) -> list[dict]:
    """获取好友列表（含 other_id：对方用户 ID）"""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            '''SELECT f.id, f.user_id, f.friend_id, f.status, f.created_at, u.username,
                      CASE WHEN f.user_id=? THEN f.friend_id ELSE f.user_id END AS other_id
               FROM friends f
               JOIN users u ON u.id = CASE WHEN f.user_id=? THEN f.friend_id ELSE f.user_id END
               WHERE (f.user_id=? OR f.friend_id=?) AND f.status=?
               ORDER BY u.username''',
            (user_id, user_id, user_id, user_id, 'accepted'),
        ).fetchall()
    return [dict(r) for r in rows]


def get_friend_requests(user_id: int) -> list[dict]:
    """获取待处理的好友申请（发给我的）"""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            '''SELECT f.id, f.user_id, f.friend_id, f.status, f.created_at, u.username
               FROM friends f JOIN users u ON u.id = f.user_id
               WHERE f.friend_id=? AND f.status='pending'
               ORDER BY f.created_at DESC''',
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


# ---- 即时消息 ----

def send_message(
    sender_id: int,
    receiver_id: int,
    content: str,
    msg_type: str = 'text',
    media_url: str = '',
) -> int:
    """发送消息，返回消息 ID"""
    init_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with _connect() as conn:
        cur = conn.execute(
            '''INSERT INTO messages (sender_id, receiver_id, content, created_at, msg_type, media_url)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (sender_id, receiver_id, content, now, msg_type or 'text', media_url or ''),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_messages(user_id: int, other_id: int, limit: int = 100, before_id: int | None = None) -> list[dict]:
    """获取两个用户之间的消息列表"""
    init_db()
    with _connect() as conn:
        if before_id:
            rows = conn.execute(
                '''SELECT * FROM messages
                   WHERE id < ? AND ((sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?))
                   ORDER BY id DESC LIMIT ?''',
                (before_id, user_id, other_id, other_id, user_id, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                '''SELECT * FROM messages
                   WHERE (sender_id=? AND receiver_id=?) OR (sender_id=? AND receiver_id=?)
                   ORDER BY id DESC LIMIT ?''',
                (user_id, other_id, other_id, user_id, limit),
            ).fetchall()
    # 反转以正序显示
    result = [dict(r) for r in rows]
    result.reverse()
    return result


def mark_messages_read(user_id: int, sender_id: int) -> int:
    """将对方发给我的未读消息标记为已读，返回更新数量"""
    init_db()
    with _connect() as conn:
        cur = conn.execute(
            '''UPDATE messages SET is_read=1
               WHERE sender_id=? AND receiver_id=? AND is_read=0''',
            (sender_id, user_id),
        )
        conn.commit()
        return cur.rowcount


def get_conversations(user_id: int) -> list[dict]:
    """获取会话列表（最近联系人 + 未读数）"""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            '''WITH pairs AS (
                 SELECT CASE WHEN sender_id=? THEN receiver_id ELSE sender_id END AS other_id,
                        MAX(id) AS last_id
                 FROM messages
                 WHERE sender_id=? OR receiver_id=?
                 GROUP BY other_id
               )
               SELECT p.other_id, u.username, m.content AS last_msg, m.msg_type AS last_msg_type,
                      m.created_at AS last_time,
                      (SELECT COUNT(*) FROM messages m4
                       WHERE m4.sender_id=p.other_id AND m4.receiver_id=? AND m4.is_read=0) AS unread
               FROM pairs p
               JOIN messages m ON m.id = p.last_id
               JOIN users u ON u.id = p.other_id
               ORDER BY p.last_id DESC''',
            (user_id, user_id, user_id, user_id),
        ).fetchall()
    result = []
    for r in rows:
        item = dict(r)
        if (item.get('last_msg_type') or 'text') == 'voice':
            item['last_msg'] = '[语音消息]'
        result.append(item)
    return result


def poll_incoming_messages(user_id: int, last_id: int = 0) -> list[dict]:
    """获取发给当前用户的新消息（id > last_id）"""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            '''SELECT m.*, u.username AS sender_name
               FROM messages m
               JOIN users u ON u.id = m.sender_id
               WHERE m.receiver_id=? AND m.id > ?
               ORDER BY m.id ASC LIMIT 50''',
            (user_id, last_id),
        ).fetchall()
    return [dict(r) for r in rows]


def get_unread_count(user_id: int) -> int:
    """获取总未读消息数"""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            'SELECT COUNT(*) AS cnt FROM messages WHERE receiver_id=? AND is_read=0',
            (user_id,),
        ).fetchone()
    return row['cnt'] if row else 0


# ---- 文件共享 ----

SHARED_FILES_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'shared_files')


def _ensure_shared_dir() -> None:
    os.makedirs(SHARED_FILES_DIR, exist_ok=True)


def save_shared_file(sender_id: int, receiver_id: int, original_name: str, file_data: bytes) -> int | None:
    """保存共享文件，返回记录 ID"""
    init_db()
    _ensure_shared_dir()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    # 用时间戳 + 用户 ID 生成唯一存储名
    stored_name = f"{sender_id}_{receiver_id}_{int(datetime.now().timestamp()*1000)}_{original_name}"
    file_path = os.path.join(SHARED_FILES_DIR, stored_name)
    with open(file_path, 'wb') as f:
        f.write(file_data)
    file_size = len(file_data)
    ext = original_name.rsplit('.', 1)[1].lower() if '.' in original_name else ''
    with _connect() as conn:
        cur = conn.execute(
            '''INSERT INTO shared_files
               (sender_id, receiver_id, original_name, stored_name, file_size, file_type, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?)''',
            (sender_id, receiver_id, original_name, stored_name, file_size, ext, now),
        )
        conn.commit()
        return int(cur.lastrowid)


def get_received_files(user_id: int, limit: int = 50) -> list[dict]:
    """获取我收到的文件列表"""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            '''SELECT sf.*, u.username AS sender_name
               FROM shared_files sf JOIN users u ON u.id = sf.sender_id
               WHERE sf.receiver_id=?
               ORDER BY sf.id DESC LIMIT ?''',
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_sent_files(user_id: int, limit: int = 50) -> list[dict]:
    """获取我发送的文件列表"""
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            '''SELECT sf.*, u.username AS receiver_name
               FROM shared_files sf JOIN users u ON u.id = sf.receiver_id
               WHERE sf.sender_id=?
               ORDER BY sf.id DESC LIMIT ?''',
            (user_id, limit),
        ).fetchall()
    return [dict(r) for r in rows]


def get_shared_file(file_id: int, user_id: int | None = None) -> dict | None:
    """获取单条文件记录（用于下载），校验权限"""
    init_db()
    with _connect() as conn:
        if user_id is not None:
            row = conn.execute(
                'SELECT * FROM shared_files WHERE id=? AND (sender_id=? OR receiver_id=?)',
                (file_id, user_id, user_id),
            ).fetchone()
        else:
            row = conn.execute('SELECT * FROM shared_files WHERE id=?', (file_id,)).fetchone()
        if row:
            result = dict(row)
            # 标记已读
            if user_id and not result['is_read'] and result['receiver_id'] == user_id:
                conn.execute('UPDATE shared_files SET is_read=1 WHERE id=?', (file_id,))
                conn.commit()
            return result
    return None


def get_unread_files_count(user_id: int) -> int:
    """未下载/未读文件数"""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            'SELECT COUNT(*) AS cnt FROM shared_files WHERE receiver_id=? AND is_read=0',
            (user_id,),
        ).fetchone()
    return row['cnt'] if row else 0


def mark_shared_file_read(file_id: int, user_id: int) -> None:
    """标记文件为已读"""
    init_db()
    with _connect() as conn:
        conn.execute(
            'UPDATE shared_files SET is_read=1 WHERE id=? AND receiver_id=?',
            (file_id, user_id),
        )
        conn.commit()


# ---- 消息提醒 ----

def create_notification(
    user_id: int,
    ntype: str,
    title: str,
    body: str = '',
    link: str = '',
) -> int:
    init_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with _connect() as conn:
        cur = conn.execute(
            '''INSERT INTO notifications (user_id, ntype, title, body, link, created_at)
               VALUES (?, ?, ?, ?, ?, ?)''',
            (user_id, ntype, title, body, link, now),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_notifications(user_id: int, limit: int = 30, unread_only: bool = False) -> list[dict]:
    init_db()
    sql = 'SELECT * FROM notifications WHERE user_id=?'
    params: list = [user_id]
    if unread_only:
        sql += ' AND is_read=0'
    sql += ' ORDER BY id DESC LIMIT ?'
    params.append(limit)
    with _connect() as conn:
        rows = conn.execute(sql, params).fetchall()
    return [dict(r) for r in rows]


def get_notification_unread_count(user_id: int) -> int:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            'SELECT COUNT(*) AS cnt FROM notifications WHERE user_id=? AND is_read=0',
            (user_id,),
        ).fetchone()
    return int(row['cnt']) if row else 0


def mark_notifications_read(user_id: int, notification_ids: list[int] | None = None) -> None:
    init_db()
    with _connect() as conn:
        if notification_ids:
            placeholders = ','.join('?' * len(notification_ids))
            conn.execute(
                f'UPDATE notifications SET is_read=1 WHERE user_id=? AND id IN ({placeholders})',
                [user_id, *notification_ids],
            )
        else:
            conn.execute(
                'UPDATE notifications SET is_read=1 WHERE user_id=?',
                (user_id,),
            )
        conn.commit()


# ---- 用户反馈 ----

def save_feedback(user_id: int | None, page: str, rating: int, message: str) -> int:
    init_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with _connect() as conn:
        cur = conn.execute(
            'INSERT INTO feedback (user_id, page, rating, message, created_at) VALUES (?, ?, ?, ?, ?)',
            (user_id, page, rating, message, now),
        )
        conn.commit()
        return int(cur.lastrowid)


# ---- 好友校验 ----

def is_friend(user_id: int, other_id: int) -> bool:
    if user_id == other_id:
        return True
    init_db()
    with _connect() as conn:
        row = conn.execute(
            '''SELECT 1 FROM friends WHERE status='accepted' AND
               ((user_id=? AND friend_id=?) OR (user_id=? AND friend_id=?))''',
            (user_id, other_id, other_id, user_id),
        ).fetchone()
    return row is not None


# ---- 协同编辑 ----

def create_collab_session(owner_id: int, title: str, table_data: dict, source_table_id: str | None = None) -> dict:
    import secrets
    init_db()
    token = secrets.token_urlsafe(12)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if source_table_id:
        table_data = dict(table_data)
        table_data['source_table_id'] = source_table_id
    payload = _json_dumps(table_data)
    with _connect() as conn:
        cur = conn.execute(
            '''INSERT INTO collab_sessions (token, owner_id, title, table_data, version, created_at, updated_at, source_table_id)
               VALUES (?, ?, ?, ?, 1, ?, ?, ?)''',
            (token, owner_id, title, payload, now, now, source_table_id),
        )
        session_id = int(cur.lastrowid)
        conn.execute(
            'INSERT INTO collab_members (session_id, user_id, joined_at) VALUES (?, ?, ?)',
            (session_id, owner_id, now),
        )
        conn.commit()
    return {'id': session_id, 'token': token, 'title': title, 'version': 1, 'source_table_id': source_table_id}


def get_collab_session(token: str) -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute('SELECT * FROM collab_sessions WHERE token=?', (token,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data['table_data'] = json.loads(data['table_data'] or '{}')
    return data


def join_collab_session(session_id: int, user_id: int) -> None:
    init_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with _connect() as conn:
        conn.execute(
            'INSERT OR IGNORE INTO collab_members (session_id, user_id, joined_at) VALUES (?, ?, ?)',
            (session_id, user_id, now),
        )
        conn.commit()


def is_collab_member(session_id: int, user_id: int) -> bool:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            'SELECT 1 FROM collab_members WHERE session_id=? AND user_id=?',
            (session_id, user_id),
        ).fetchone()
    return row is not None


def update_collab_table(token: str, table_data: dict) -> int:
    init_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    payload = _json_dumps(table_data)
    source_id = None
    if isinstance(table_data, dict):
        source_id = table_data.get('source_table_id')
    with _connect() as conn:
        row = conn.execute('SELECT version FROM collab_sessions WHERE token=?', (token,)).fetchone()
        if not row:
            return 0
        new_version = int(row['version']) + 1
        if source_id:
            conn.execute(
                '''UPDATE collab_sessions
                   SET table_data=?, version=?, updated_at=?, source_table_id=?
                   WHERE token=?''',
                (payload, new_version, now, source_id, token),
            )
        else:
            conn.execute(
                'UPDATE collab_sessions SET table_data=?, version=?, updated_at=? WHERE token=?',
                (payload, new_version, now, token),
            )
        conn.commit()
    return new_version


def set_collab_source_table_id(token: str, source_table_id: str) -> bool:
    """补写协同会话的源表 ID，并写入 table_data JSON。"""
    if not token or not source_table_id:
        return False
    init_db()
    with _connect() as conn:
        row = conn.execute('SELECT table_data FROM collab_sessions WHERE token=?', (token,)).fetchone()
        if not row:
            return False
        try:
            data = json.loads(row['table_data'] or '{}')
        except Exception:
            data = {}
        data['source_table_id'] = source_table_id
        conn.execute(
            '''UPDATE collab_sessions SET source_table_id=?, table_data=? WHERE token=?''',
            (source_table_id, _json_dumps(data), token),
        )
        conn.commit()
    return True


def touch_collab_presence(session_id: int, user_id: int) -> None:
    init_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with _connect() as conn:
        conn.execute(
            '''INSERT INTO collab_presence (session_id, user_id, last_seen) VALUES (?, ?, ?)
               ON CONFLICT(session_id, user_id) DO UPDATE SET last_seen=excluded.last_seen''',
            (session_id, user_id, now),
        )
        conn.commit()


def get_collab_online_members(session_id: int, within_seconds: int = 30) -> list[dict]:
    init_db()
    cutoff = (datetime.now() - timedelta(seconds=within_seconds)).strftime('%Y-%m-%d %H:%M:%S')
    with _connect() as conn:
        rows = conn.execute(
            '''SELECT cp.user_id, u.username, cp.last_seen, cp.editing_row, cp.editing_column
               FROM collab_presence cp JOIN users u ON u.id = cp.user_id
               WHERE cp.session_id=? AND cp.last_seen >= ?
               ORDER BY cp.last_seen DESC''',
            (session_id, cutoff),
        ).fetchall()
    return [dict(r) for r in rows]


def set_collab_editing_cell(session_id: int, user_id: int, row: int | None, column: str | None) -> None:
    """上报或清除当前用户正在编辑的单元格。"""
    init_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with _connect() as conn:
        conn.execute(
            '''INSERT INTO collab_presence (session_id, user_id, last_seen, editing_row, editing_column)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(session_id, user_id) DO UPDATE SET
                 last_seen=excluded.last_seen,
                 editing_row=excluded.editing_row,
                 editing_column=excluded.editing_column''',
            (session_id, user_id, now, row, column),
        )
        conn.commit()


# ---- 财务核算 ----

_FIN_SEED_ACCOUNTS = [
    ('1001', '库存现金', 'asset', None),
    ('1002', '银行存款', 'asset', None),
    ('1122', '应收账款', 'asset', None),
    ('1403', '原材料', 'asset', None),
    ('1601', '固定资产', 'asset', None),
    ('2202', '应付账款', 'liability', None),
    ('2221', '应交税费', 'liability', None),
    ('4001', '实收资本', 'equity', None),
    ('4103', '本年利润', 'equity', None),
    ('6001', '主营业务收入', 'revenue', None),
    ('6401', '主营业务成本', 'expense', None),
    ('6602', '管理费用', 'expense', None),
    ('6603', '财务费用', 'expense', None),
]


def ensure_finance_seed(user_id: int) -> None:
    init_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with _connect() as conn:
        row = conn.execute('SELECT 1 FROM fin_accounts WHERE user_id=? LIMIT 1', (user_id,)).fetchone()
        if not row:
            for code, name, cat, parent in _FIN_SEED_ACCOUNTS:
                conn.execute(
                    '''INSERT INTO fin_accounts (user_id, code, name, category, parent_code, balance, created_at)
                       VALUES (?, ?, ?, ?, ?, 0, ?)''',
                    (user_id, code, name, cat, parent, now),
                )
        prow = conn.execute(
            "SELECT id FROM fin_periods WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        if not prow:
            year = datetime.now().year
            conn.execute(
                '''INSERT INTO fin_periods (user_id, name, start_date, end_date, status, created_at)
                   VALUES (?, ?, ?, ?, 'open', ?)''',
                (user_id, f'{year}年度', f'{year}-01-01', f'{year}-12-31', now),
            )
        conn.commit()


def get_fin_accounts(user_id: int) -> list[dict]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            'SELECT * FROM fin_accounts WHERE user_id=? ORDER BY code',
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def _next_voucher_no(conn, user_id: int) -> str:
    row = conn.execute(
        'SELECT voucher_no FROM fin_vouchers WHERE user_id=? ORDER BY id DESC LIMIT 1',
        (user_id,),
    ).fetchone()
    if not row:
        return '记-0001'
    no = row['voucher_no']
    try:
        num = int(no.split('-')[-1]) + 1
    except ValueError:
        num = 1
    return f'记-{num:04d}'


def create_fin_voucher(
    user_id: int,
    *,
    voucher_date: str,
    summary: str,
    lines: list[dict],
    auto_post: bool = False,
) -> int:
    init_db()
    ensure_finance_seed(user_id)
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    total_debit = sum(float(ln.get('debit') or 0) for ln in lines)
    total_credit = sum(float(ln.get('credit') or 0) for ln in lines)
    with _connect() as conn:
        period = conn.execute(
            "SELECT id FROM fin_periods WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        period_id = period['id'] if period else None
        voucher_no = _next_voucher_no(conn, user_id)
        status = 'posted' if auto_post else 'draft'
        cur = conn.execute(
            '''INSERT INTO fin_vouchers
               (user_id, period_id, voucher_no, voucher_date, summary, status,
                total_debit, total_credit, created_by, created_at, posted_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)''',
            (
                user_id, period_id, voucher_no, voucher_date, summary, status,
                total_debit, total_credit, user_id, now,
                now if auto_post else None,
            ),
        )
        vid = int(cur.lastrowid)
        for i, ln in enumerate(lines, 1):
            code = str(ln.get('account_code', '')).strip()
            acct = conn.execute(
                'SELECT name FROM fin_accounts WHERE user_id=? AND code=?',
                (user_id, code),
            ).fetchone()
            conn.execute(
                '''INSERT INTO fin_voucher_lines
                   (voucher_id, line_no, account_code, account_name, summary, debit, credit)
                   VALUES (?, ?, ?, ?, ?, ?, ?)''',
                (
                    vid, i, code,
                    acct['name'] if acct else ln.get('account_name', ''),
                    ln.get('summary') or summary,
                    float(ln.get('debit') or 0),
                    float(ln.get('credit') or 0),
                ),
            )
            if auto_post:
                _apply_line_balance(conn, user_id, code, float(ln.get('debit') or 0), float(ln.get('credit') or 0))
        conn.commit()
    return vid


def _apply_line_balance(conn, user_id: int, code: str, debit: float, credit: float) -> None:
    row = conn.execute(
        'SELECT category, balance FROM fin_accounts WHERE user_id=? AND code=?',
        (user_id, code),
    ).fetchone()
    if not row:
        return
    cat = row['category']
    bal = float(row['balance'] or 0)
    if cat in ('asset', 'expense'):
        bal += debit - credit
    else:
        bal += credit - debit
    conn.execute(
        'UPDATE fin_accounts SET balance=? WHERE user_id=? AND code=?',
        (bal, user_id, code),
    )


def post_fin_voucher(user_id: int, voucher_id: int) -> None:
    init_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with _connect() as conn:
        v = conn.execute(
            'SELECT * FROM fin_vouchers WHERE id=? AND user_id=?',
            (voucher_id, user_id),
        ).fetchone()
        if not v:
            raise ValueError('凭证不存在')
        if v['status'] == 'posted':
            return
        lines = conn.execute(
            'SELECT * FROM fin_voucher_lines WHERE voucher_id=? ORDER BY line_no',
            (voucher_id,),
        ).fetchall()
        for ln in lines:
            _apply_line_balance(conn, user_id, ln['account_code'], float(ln['debit']), float(ln['credit']))
        conn.execute(
            "UPDATE fin_vouchers SET status='posted', posted_at=? WHERE id=?",
            (now, voucher_id),
        )
        conn.commit()


def list_fin_vouchers(user_id: int, *, limit: int = 50, status: str | None = None) -> list[dict]:
    init_db()
    with _connect() as conn:
        if status:
            rows = conn.execute(
                '''SELECT * FROM fin_vouchers WHERE user_id=? AND status=?
                   ORDER BY voucher_date DESC, id DESC LIMIT ?''',
                (user_id, status, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM fin_vouchers WHERE user_id=? ORDER BY voucher_date DESC, id DESC LIMIT ?',
                (user_id, limit),
            ).fetchall()
    return [dict(r) for r in rows]


def get_fin_voucher_detail(user_id: int, voucher_id: int) -> dict | None:
    init_db()
    with _connect() as conn:
        v = conn.execute(
            'SELECT * FROM fin_vouchers WHERE id=? AND user_id=?',
            (voucher_id, user_id),
        ).fetchone()
        if not v:
            return None
        lines = conn.execute(
            'SELECT * FROM fin_voucher_lines WHERE voucher_id=? ORDER BY line_no',
            (voucher_id,),
        ).fetchall()
    data = dict(v)
    data['lines'] = [dict(ln) for ln in lines]
    return data


def get_finance_overview(user_id: int) -> dict:
    init_db()
    ensure_finance_seed(user_id)
    with _connect() as conn:
        period = conn.execute(
            "SELECT * FROM fin_periods WHERE user_id=? AND status='open' ORDER BY id DESC LIMIT 1",
            (user_id,),
        ).fetchone()
        accounts = conn.execute(
            'SELECT code, name, category, balance FROM fin_accounts WHERE user_id=? ORDER BY ABS(balance) DESC',
            (user_id,),
        ).fetchall()
        counts = conn.execute(
            '''SELECT status, COUNT(*) AS cnt FROM fin_vouchers WHERE user_id=? GROUP BY status''',
            (user_id,),
        ).fetchall()
    accts = [dict(a) for a in accounts]
    totals = {
        'assets': sum(a['balance'] for a in accts if a['category'] == 'asset'),
        'liabilities': sum(a['balance'] for a in accts if a['category'] == 'liability'),
        'equity': sum(a['balance'] for a in accts if a['category'] == 'equity'),
        'revenue': sum(a['balance'] for a in accts if a['category'] == 'revenue'),
        'expense': sum(a['balance'] for a in accts if a['category'] == 'expense'),
    }
    return {
        'current_period': dict(period) if period else None,
        'totals': totals,
        'top_accounts': accts[:10],
        'voucher_counts': {r['status']: r['cnt'] for r in counts},
        'account_count': len(accts),
    }


# ── Agent 会话管理（SQLite 持久化）──

def create_agent_conversation(user_id: int, title: str = '新对话', model_id: str | None = None) -> dict:
    init_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    title = title.strip()[:100] or '新对话'
    with _connect() as conn:
        cur = conn.execute(
            '''INSERT INTO agent_conversations (user_id, title, messages_json, model_id, created_at, updated_at)
               VALUES (?, ?, '[]', ?, ?, ?)''',
            (user_id, title, model_id, now, now),
        )
        conn.commit()
        return {
            'id': cur.lastrowid, 'title': title, 'model_id': model_id,
            'created_at': now, 'updated_at': now, 'message_count': 0,
        }


def list_agent_conversations(user_id: int) -> list[dict]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            '''SELECT id, title, model_id, created_at, updated_at, messages_json
               FROM agent_conversations WHERE user_id=?
               ORDER BY updated_at DESC''',
            (user_id,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        try:
            msgs = json.loads(d.pop('messages_json', '[]') or '[]')
            d['message_count'] = len(msgs) if isinstance(msgs, list) else 0
        except (json.JSONDecodeError, TypeError):
            d.pop('messages_json', None)
            d['message_count'] = 0
        result.append(d)
    return result


def get_agent_conversation(conv_id: int, user_id: int) -> dict | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            'SELECT * FROM agent_conversations WHERE id=? AND user_id=?', (conv_id, user_id),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    try:
        d['messages'] = json.loads(d.get('messages_json', '[]'))
    except (json.JSONDecodeError, TypeError):
        d['messages'] = []
    return d


def save_agent_messages(conv_id: int, user_id: int, messages: list[dict], title: str | None = None) -> bool:
    init_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    if len(messages) > 80:
        messages = messages[-80:]
    messages_json = json.dumps(messages, ensure_ascii=False)
    with _connect() as conn:
        if title:
            conn.execute(
                'UPDATE agent_conversations SET messages_json=?, updated_at=?, title=? WHERE id=? AND user_id=?',
                (messages_json, now, title[:100], conv_id, user_id),
            )
        else:
            conn.execute(
                'UPDATE agent_conversations SET messages_json=?, updated_at=? WHERE id=? AND user_id=?',
                (messages_json, now, conv_id, user_id),
            )
        conn.commit()
        return conn.total_changes > 0
    return False


def delete_agent_conversation(conv_id: int, user_id: int) -> bool:
    init_db()
    with _connect() as conn:
        conn.execute('DELETE FROM agent_conversations WHERE id=? AND user_id=?', (conv_id, user_id))
        conn.commit()
        return conn.total_changes > 0


def auto_title_from_message(message: str) -> str:
    msg = message.strip()
    title = msg[:30].replace('\n', ' ')
    if len(msg) > 30:
        title += '…'
    return title if title else '新对话'


# ── 编辑中的工作表持久化（防止退出编辑后修改丢失）──

def upsert_working_table(user_id: int, table_key: str, filename: str, df: pd.DataFrame) -> None:
    """将当前编辑表写入 SQLite，覆盖同 user+key。"""
    if not user_id or not table_key:
        return
    init_db()
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    payload = _json_dumps({
        'columns': list(df.columns),
        'rows': df.fillna('').astype(str).values.tolist(),
    })
    with _connect() as conn:
        conn.execute(
            '''INSERT INTO working_tables (user_id, table_key, filename, table_json, updated_at)
               VALUES (?, ?, ?, ?, ?)
               ON CONFLICT(user_id, table_key) DO UPDATE SET
                 filename=excluded.filename,
                 table_json=excluded.table_json,
                 updated_at=excluded.updated_at''',
            (user_id, table_key, filename or '', payload, now),
        )
        conn.commit()


def list_working_tables(user_id: int) -> list[dict]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            '''SELECT table_key, filename, updated_at FROM working_tables
               WHERE user_id=? ORDER BY updated_at DESC''',
            (user_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def load_working_table(user_id: int, table_key: str) -> dict | None:
    """返回 {filename, df} 或 None。"""
    init_db()
    with _connect() as conn:
        row = conn.execute(
            'SELECT filename, table_json FROM working_tables WHERE user_id=? AND table_key=?',
            (user_id, table_key),
        ).fetchone()
    if not row:
        return None
    try:
        data = json.loads(row['table_json'] or '{}')
        cols = data.get('columns') or []
        rows = data.get('rows') or []
        df = pd.DataFrame(rows, columns=cols) if cols else pd.DataFrame(rows)
        return {'filename': row['filename'] or '未命名', 'df': df}
    except Exception:
        return None


def delete_working_table(user_id: int, table_key: str) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            'DELETE FROM working_tables WHERE user_id=? AND table_key=?',
            (user_id, table_key),
        )
        conn.commit()


def update_history_table_data(record_id: int, df: pd.DataFrame, user_id: int | None = None) -> bool:
    """同步更新历史记录中的表格快照（编辑后不丢改）。"""
    if not record_id:
        return False
    init_db()
    table_json = _json_dumps({
        'columns': list(df.columns),
        'rows': df.fillna('').astype(str).values.tolist(),
    })
    with _connect() as conn:
        if user_id is not None:
            cur = conn.execute(
                '''UPDATE history_records SET table_data=?, row_count=?, column_count=?
                   WHERE id=? AND (user_id=? OR user_id IS NULL)''',
                (table_json, len(df), len(df.columns), record_id, user_id),
            )
        else:
            cur = conn.execute(
                '''UPDATE history_records SET table_data=?, row_count=?, column_count=?
                   WHERE id=?''',
                (table_json, len(df), len(df.columns), record_id),
            )
        conn.commit()
        return cur.rowcount > 0
