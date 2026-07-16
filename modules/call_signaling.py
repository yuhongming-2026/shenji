"""WebRTC 信令（SQLite 持久化，HTTP 轮询）。"""
from __future__ import annotations

import json
import time
from typing import Any

from modules.database import init_db, _connect

_TTL = 3600


def _room_key(a: int, b: int) -> str:
    return f'{min(a, b)}_{max(a, b)}'


def _cleanup(conn) -> None:
    now = time.time()
    conn.execute('DELETE FROM call_rooms WHERE updated_at < ?', (now - _TTL,))


def _get_room(conn, key: str) -> dict | None:
    row = conn.execute('SELECT * FROM call_rooms WHERE room_key=?', (key,)).fetchone()
    if not row:
        return None
    data = dict(row)
    data['caller_ice'] = json.loads(data.get('caller_ice') or '[]')
    data['callee_ice'] = json.loads(data.get('callee_ice') or '[]')
    if data.get('offer'):
        data['offer'] = json.loads(data['offer'])
    if data.get('answer'):
        data['answer'] = json.loads(data['answer'])
    return data


def start_call(caller_id: int, callee_id: int) -> dict:
    init_db()
    key = _room_key(caller_id, callee_id)
    now = time.time()
    with _connect() as conn:
        _cleanup(conn)
        conn.execute(
            '''INSERT INTO call_rooms (room_key, caller_id, callee_id, offer, answer,
               caller_ice, callee_ice, status, updated_at)
               VALUES (?, ?, ?, NULL, NULL, '[]', '[]', 'ringing', ?)
               ON CONFLICT(room_key) DO UPDATE SET
                 caller_id=excluded.caller_id,
                 callee_id=excluded.callee_id,
                 offer=NULL,
                 answer=NULL,
                 caller_ice='[]',
                 callee_ice='[]',
                 status='ringing',
                 updated_at=excluded.updated_at''',
            (key, caller_id, callee_id, now),
        )
        conn.commit()
    return {'room': key, 'status': 'ringing'}


def set_offer(caller_id: int, callee_id: int, sdp: dict) -> bool:
    init_db()
    key = _room_key(caller_id, callee_id)
    with _connect() as conn:
        room = _get_room(conn, key)
        if not room:
            return False
        conn.execute(
            'UPDATE call_rooms SET offer=?, status=?, updated_at=? WHERE room_key=?',
            (json.dumps(sdp), 'offered', time.time(), key),
        )
        conn.commit()
    return True


def set_answer(caller_id: int, callee_id: int, sdp: dict) -> bool:
    init_db()
    key = _room_key(caller_id, callee_id)
    with _connect() as conn:
        room = _get_room(conn, key)
        if not room:
            return False
        conn.execute(
            'UPDATE call_rooms SET answer=?, status=?, updated_at=? WHERE room_key=?',
            (json.dumps(sdp), 'answered', time.time(), key),
        )
        conn.commit()
    return True


def add_ice(user_id: int, peer_id: int, candidate: dict) -> bool:
    init_db()
    key = _room_key(user_id, peer_id)
    with _connect() as conn:
        room = _get_room(conn, key)
        if not room:
            return False
        bucket = 'caller_ice' if user_id == room['caller_id'] else 'callee_ice'
        ice_list = list(room[bucket])
        ice_list.append(candidate)
        conn.execute(
            f'UPDATE call_rooms SET {bucket}=?, updated_at=? WHERE room_key=?',
            (json.dumps(ice_list), time.time(), key),
        )
        conn.commit()
    return True


def poll(user_id: int, peer_id: int) -> dict:
    init_db()
    key = _room_key(user_id, peer_id)
    with _connect() as conn:
        _cleanup(conn)
        room = _get_room(conn, key)
        if not room:
            return {'active': False}
        is_caller = user_id == room['caller_id']
        peer_ice_key = 'callee_ice' if is_caller else 'caller_ice'
        peer_ice = list(room[peer_ice_key])
        # 不在 poll 时清除 ICE，避免客户端尚未成功 add 时丢失候选
        conn.commit()
        return {
            'active': True,
            'status': room['status'],
            'offer': room.get('offer') if not is_caller else None,
            'answer': room.get('answer') if is_caller else None,
            'ice': peer_ice,
            'caller_id': room['caller_id'],
            'callee_id': room['callee_id'],
        }


def end_call(user_id: int, peer_id: int) -> None:
    init_db()
    key = _room_key(user_id, peer_id)
    with _connect() as conn:
        conn.execute('DELETE FROM call_rooms WHERE room_key=?', (key,))
        conn.commit()


def poll_incoming(user_id: int) -> dict:
    """被叫方：查找发给自己的待接听通话"""
    init_db()
    with _connect() as conn:
        _cleanup(conn)
        rows = conn.execute(
            '''SELECT * FROM call_rooms
               WHERE callee_id=? AND status IN ('ringing', 'offered', 'answered')
               ORDER BY updated_at DESC LIMIT 1''',
            (user_id,),
        ).fetchall()
        if not rows:
            return {'active': False}
        room = dict(rows[0])
        offer = room.get('offer')
        if offer:
            offer = json.loads(offer)
        return {
            'active': True,
            'caller_id': room['caller_id'],
            'offer': offer,
            'status': room['status'],
        }
