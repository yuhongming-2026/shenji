"""LLM 响应缓存 — 相同 prompt 直接返回，避免重复推理。"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections import OrderedDict
from typing import Any

_MAX_ENTRIES = int(os.environ.get('LLM_CACHE_SIZE', '128'))
_TTL_SEC = int(os.environ.get('LLM_CACHE_TTL', '3600'))

_lock = threading.Lock()
_cache: OrderedDict[str, dict[str, Any]] = OrderedDict()


def _key(messages: list[dict[str, str]], max_tokens: int, temperature: float, fast: bool) -> str:
    payload = json.dumps({
        'm': messages[-6:],
        'max': max_tokens,
        't': round(temperature, 2),
        'f': fast,
    }, ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(payload.encode()).hexdigest()


def get(messages: list[dict[str, str]], *, max_tokens: int, temperature: float, fast: bool) -> str | None:
    k = _key(messages, max_tokens, temperature, fast)
    now = time.time()
    with _lock:
        item = _cache.get(k)
        if not item:
            return None
        if now - item['ts'] > _TTL_SEC:
            del _cache[k]
            return None
        _cache.move_to_end(k)
        return item['text']


def put(messages: list[dict[str, str]], *, max_tokens: int, temperature: float, fast: bool, text: str) -> None:
    k = _key(messages, max_tokens, temperature, fast)
    with _lock:
        _cache[k] = {'text': text, 'ts': time.time()}
        _cache.move_to_end(k)
        while len(_cache) > _MAX_ENTRIES:
            _cache.popitem(last=False)


def stats() -> dict:
    with _lock:
        return {'entries': len(_cache), 'max_entries': _MAX_ENTRIES, 'ttl_sec': _TTL_SEC}
