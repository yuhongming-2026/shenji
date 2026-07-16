"""协同编辑：共享表格会话、权限校验、表格操作。"""
from __future__ import annotations

from typing import Any

import pandas as pd

from modules.data_processor import clean_data, detect_column_types, export_table_snapshot
from modules.database import (
    create_collab_session,
    get_collab_online_members,
    get_collab_session,
    is_collab_member,
    join_collab_session,
    list_working_tables,
    set_collab_editing_cell,
    set_collab_source_table_id,
    touch_collab_presence,
    update_collab_table,
)


def _snapshot_to_df(snapshot: dict) -> pd.DataFrame:
    columns = snapshot.get('columns') or []
    rows = snapshot.get('rows') or []
    if not columns and rows:
        columns = list(rows[0].keys())
    df = pd.DataFrame(rows, columns=columns)
    return clean_data(df)


def _df_to_snapshot(df: pd.DataFrame, filename: str = '') -> dict:
    return {
        'columns': list(df.columns),
        'rows': df.fillna('').to_dict(orient='records'),
        'filename': filename,
    }


def can_access_collab(session: dict, user_id: int) -> bool:
    """拥有链接并成功 join 的成员均可编辑；不再强制好友关系。"""
    if not session:
        return False
    if session['owner_id'] == user_id:
        return True
    return is_collab_member(session['id'], user_id)


def resolve_source_table_id(session: dict) -> str | None:
    """解析协同会话对应的普通编辑源表；旧会话无字段时按文件名回填。"""
    if not session:
        return None
    source_id = session.get('source_table_id') or (session.get('table_data') or {}).get('source_table_id')
    if source_id:
        return str(source_id)
    owner_id = session.get('owner_id')
    title = (session.get('title') or '').strip()
    if not owner_id:
        return None
    try:
        items = list_working_tables(int(owner_id))
    except Exception:
        items = []
    if not items:
        return None
    for item in items:
        fn = (item.get('filename') or '').strip()
        if fn and (fn == title or title in fn or fn in title):
            source_id = item['table_key']
            break
    else:
        source_id = items[0]['table_key']
    try:
        set_collab_source_table_id(session['token'], source_id)
    except Exception as exc:
        print(f'[collab bind source] {exc}', flush=True)
    return source_id


def create_session_from_table(owner_id: int, table_id: str) -> dict:
    snapshot = export_table_snapshot(table_id)
    if not snapshot:
        return {'success': False, 'error': '当前表格不存在，请先上传数据'}
    title = snapshot.get('filename') or '协同表格'
    # 创建前先把当前表落库，避免协同写回时找不到 working_tables
    try:
        from modules.data_processor import persist_table
        persist_table(table_id, owner_id)
    except Exception:
        pass
    created = create_collab_session(owner_id, title, snapshot, source_table_id=table_id)
    return {
        'success': True,
        'token': created['token'],
        'title': created['title'],
        'share_url': f'/edit?collab={created["token"]}',
        'version': created['version'],
        'source_table_id': table_id,
    }


def join_session(token: str, user_id: int) -> dict:
    session = get_collab_session(token)
    if not session:
        return {'success': False, 'error': '协同会话不存在或已失效'}
    join_collab_session(session['id'], user_id)
    touch_collab_presence(session['id'], user_id)
    source_id = resolve_source_table_id(session)
    return {
        'success': True,
        'token': token,
        'title': session['title'],
        'owner_id': session['owner_id'],
        'version': session['version'],
        'source_table_id': source_id,
    }


def get_sync_state(token: str, user_id: int, since_version: int = 0) -> dict:
    session = get_collab_session(token)
    if not session:
        return {'success': False, 'error': '协同会话不存在'}
    if not can_access_collab(session, user_id):
        return {'success': False, 'error': '无权访问该协同编辑，请通过邀请链接加入'}
    touch_collab_presence(session['id'], user_id)
    changed = session['version'] > since_version
    members = get_collab_online_members(session['id'])
    result = {
        'success': True,
        'version': session['version'],
        'changed': changed,
        'title': session['title'],
        'members': members,
        'updated_at': session['updated_at'],
        'source_table_id': resolve_source_table_id(session),
    }
    if changed or since_version == 0:
        snapshot = session['table_data']
        df = _snapshot_to_df(snapshot)
        result.update({
            'columns': list(df.columns),
            'column_types': detect_column_types(df),
            'total_rows': len(df),
        })
    return result


def get_collab_page(token: str, user_id: int, page: int = 1, per_page: int = 50) -> dict:
    session = get_collab_session(token)
    if not session:
        return {'success': False, 'error': '协同会话不存在'}
    if not can_access_collab(session, user_id):
        return {'success': False, 'error': '无权访问该协同编辑，请通过邀请链接加入'}
    touch_collab_presence(session['id'], user_id)
    resolve_source_table_id(session)
    df = _snapshot_to_df(session['table_data'])
    total = len(df)
    start = (page - 1) * per_page
    end = start + per_page
    page_df = df.iloc[start:end]
    return {
        'success': True,
        'token': token,
        'title': session['title'],
        'version': session['version'],
        'columns': list(df.columns),
        'column_types': detect_column_types(df),
        'rows': page_df.fillna('').to_dict(orient='records'),
        'total_rows': total,
        'page': page,
        'per_page': per_page,
        'total_pages': max(1, (total + per_page - 1) // per_page),
        'members': get_collab_online_members(session['id']),
    }


def sync_collab_to_source(token: str, owner_id: int | None = None) -> dict:
    """把协同最新快照强制写回普通表格编辑（内存 + SQLite）。"""
    session = get_collab_session(token)
    if not session:
        return {'success': False, 'error': '协同会话不存在'}
    source_id = resolve_source_table_id(session)
    owner_id = owner_id or session.get('owner_id')
    if not source_id:
        return {'success': False, 'error': '无法定位源表格，请重新从表格编辑发起协同'}
    df = _snapshot_to_df(session['table_data']).reset_index(drop=True)
    filename = session.get('title') or '协同表格'
    try:
        from modules.data_processor import apply_df_to_table, persist_table, get_table, restore_table_as
        if get_table(source_id):
            apply_df_to_table(source_id, df)
        else:
            restore_table_as(source_id, df, filename)
        persist_table(source_id, owner_id)
    except Exception as exc:
        print(f'[collab apply] {exc}', flush=True)
        return {'success': False, 'error': str(exc)}
    return {
        'success': True,
        'source_table_id': source_id,
        'rows': len(df),
        'version': session.get('version'),
    }


def _save_session_df(token: str, df: pd.DataFrame, filename: str, owner_id: int | None = None) -> dict:
    session = get_collab_session(token)
    source_id = None
    if session:
        source_id = resolve_source_table_id(session)
        owner_id = owner_id or session.get('owner_id')
    snapshot = _df_to_snapshot(df, filename)
    if source_id:
        snapshot['source_table_id'] = source_id
    new_version = update_collab_table(token, snapshot)
    if source_id:
        try:
            from modules.data_processor import apply_df_to_table, persist_table, get_table, restore_table_as
            if get_table(source_id):
                apply_df_to_table(source_id, df)
            else:
                restore_table_as(source_id, df, filename)
            persist_table(source_id, owner_id)
        except Exception as exc:
            print(f'[collab sync] {exc}', flush=True)
    return {'success': True, 'version': new_version, 'source_table_id': source_id}


def update_collab_cell(token: str, user_id: int, row_idx: int, column: str, value: Any) -> dict:
    session = get_collab_session(token)
    if not session or not can_access_collab(session, user_id):
        return {'success': False, 'error': '无权编辑'}
    df = _snapshot_to_df(session['table_data']).reset_index(drop=True)
    try:
        if row_idx < 0 or row_idx >= len(df):
            return {'success': False, 'error': f'行索引越界: {row_idx}'}
        if column not in df.columns:
            return {'success': False, 'error': f'列不存在: {column}'}
        if df[column].dtype != object:
            df[column] = df[column].astype(object)
        df.iloc[row_idx, df.columns.get_loc(column)] = value
    except Exception as e:
        return {'success': False, 'error': str(e)}
    return _save_session_df(token, df, session['title'], session.get('owner_id'))


def add_collab_row(token: str, user_id: int, row_data: dict | None = None) -> dict:
    session = get_collab_session(token)
    if not session or not can_access_collab(session, user_id):
        return {'success': False, 'error': '无权编辑'}
    df = _snapshot_to_df(session['table_data']).reset_index(drop=True)
    new_row = row_data or {}
    for col in df.columns:
        new_row.setdefault(col, '')
    df = pd.concat([df, pd.DataFrame([new_row])], ignore_index=True)
    result = _save_session_df(token, df, session['title'], session.get('owner_id'))
    result['new_index'] = len(df) - 1
    return result


def delete_collab_row(token: str, user_id: int, row_idx: int) -> dict:
    session = get_collab_session(token)
    if not session or not can_access_collab(session, user_id):
        return {'success': False, 'error': '无权编辑'}
    df = _snapshot_to_df(session['table_data']).reset_index(drop=True)
    if row_idx < 0 or row_idx >= len(df):
        return {'success': False, 'error': '行索引越界'}
    df = df.drop(df.index[row_idx]).reset_index(drop=True)
    return _save_session_df(token, df, session['title'], session.get('owner_id'))


def add_collab_column(token: str, user_id: int, col_name: str, default_value: Any = '') -> dict:
    session = get_collab_session(token)
    if not session or not can_access_collab(session, user_id):
        return {'success': False, 'error': '无权编辑'}
    df = _snapshot_to_df(session['table_data']).reset_index(drop=True)
    if col_name in df.columns:
        return {'success': False, 'error': f'列 "{col_name}" 已存在'}
    df[col_name] = default_value
    return _save_session_df(token, df, session['title'], session.get('owner_id'))


def delete_collab_column(token: str, user_id: int, col_name: str) -> dict:
    session = get_collab_session(token)
    if not session or not can_access_collab(session, user_id):
        return {'success': False, 'error': '无权编辑'}
    df = _snapshot_to_df(session['table_data']).reset_index(drop=True)
    if col_name not in df.columns:
        return {'success': False, 'error': f'列 "{col_name}" 不存在'}
    df = df.drop(columns=[col_name])
    return _save_session_df(token, df, session['title'], session.get('owner_id'))


def build_invite_message(token: str, title: str, sender_name: str) -> str:
    return (
        f'[collab:{token}:{title}]'
        f'{sender_name} 邀请你一起协同编辑表格「{title}」，点击链接共同完成校对。'
    )


def report_editing_cell(token: str, user_id: int, row: int | None, column: str | None) -> dict:
    session = get_collab_session(token)
    if not session:
        return {'success': False, 'error': '协同会话不存在'}
    if not can_access_collab(session, user_id):
        return {'success': False, 'error': '无权访问'}
    set_collab_editing_cell(session['id'], user_id, row, column)
    members = get_collab_online_members(session['id'])
    return {'success': True, 'members': members}
