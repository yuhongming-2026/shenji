"""财务核算模块 — 科目、凭证、总账（用友 U8 风格精简版）。"""
from __future__ import annotations

from datetime import datetime
from typing import Any

from modules.database import (
    create_fin_voucher,
    ensure_finance_seed,
    get_fin_accounts,
    get_finance_overview,
    list_fin_vouchers,
    post_fin_voucher,
)


def init_user_finance(user_id: int) -> None:
    ensure_finance_seed(user_id)


def overview(user_id: int) -> dict:
    init_user_finance(user_id)
    return get_finance_overview(user_id)


def accounts(user_id: int) -> list[dict]:
    init_user_finance(user_id)
    return get_fin_accounts(user_id)


def vouchers(user_id: int, *, limit: int = 50, status: str | None = None) -> list[dict]:
    init_user_finance(user_id)
    return list_fin_vouchers(user_id, limit=limit, status=status)


def create_voucher(user_id: int, payload: dict) -> dict:
    init_user_finance(user_id)
    lines = payload.get('lines') or []
    if len(lines) < 2:
        return {'success': False, 'error': '凭证至少需要两条分录'}
    debit = sum(float(ln.get('debit') or 0) for ln in lines)
    credit = sum(float(ln.get('credit') or 0) for ln in lines)
    if abs(debit - credit) > 0.01:
        return {'success': False, 'error': f'借贷不平衡：借方 {debit:.2f} ≠ 贷方 {credit:.2f}'}
    try:
        from modules.database import get_fin_voucher_detail
        from modules.enterprise_db import save_doc_version

        vid = create_fin_voucher(
            user_id,
            voucher_date=payload.get('voucher_date') or datetime.now().strftime('%Y-%m-%d'),
            summary=payload.get('summary') or '记账凭证',
            lines=lines,
            auto_post=bool(payload.get('auto_post')),
        )
        detail = get_fin_voucher_detail(user_id, vid)
        if detail:
            save_doc_version(user_id, 'voucher', vid, detail, message='创建凭证', author_id=user_id)
        return {'success': True, 'voucher_id': vid}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def submit_voucher_approval(user_id: int, voucher_id: int, approver_id: int | None = None) -> dict:
    init_user_finance(user_id)
    from modules.database import get_fin_voucher_detail
    from modules.enterprise_db import create_approval

    detail = get_fin_voucher_detail(user_id, voucher_id)
    if not detail:
        return {'success': False, 'error': '凭证不存在'}
    if detail['status'] != 'draft':
        return {'success': False, 'error': '仅草稿凭证可提交审批'}
    aids = [approver_id] if approver_id else [user_id]
    aid = create_approval(
        user_id, 'voucher', voucher_id,
        f'凭证过账审批 {detail["voucher_no"]}',
        aids,
    )
    return {'success': True, 'approval_id': aid}


def approve_voucher(user_id: int, voucher_id: int) -> dict:
    init_user_finance(user_id)
    try:
        from modules.database import get_fin_voucher_detail
        from modules.enterprise_db import save_doc_version

        post_fin_voucher(user_id, voucher_id)
        detail = get_fin_voucher_detail(user_id, voucher_id)
        if detail:
            save_doc_version(user_id, 'voucher', voucher_id, detail, message='审核记账', author_id=user_id)
        return {'success': True, 'voucher_id': voucher_id, 'status': 'posted'}
    except Exception as e:
        return {'success': False, 'error': str(e)}


def agent_summary(user_id: int) -> dict[str, Any]:
    """供 Agent 工具使用的财务摘要。"""
    data = overview(user_id)
    recent = vouchers(user_id, limit=5)
    return {
        'period': data.get('current_period'),
        'totals': data.get('totals'),
        'top_accounts': data.get('top_accounts', [])[:6],
        'recent_vouchers': [
            {'no': v['voucher_no'], 'date': v['voucher_date'], 'summary': v['summary'], 'status': v['status']}
            for v in recent
        ],
        'voucher_counts': data.get('voucher_counts'),
    }
