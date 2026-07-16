"""企业级财务扩展表 — AR/AP、发票、银行对账、审批、任务、版本历史。"""
from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from modules.database import _connect, init_db

_SCHEMA_DONE = False


def ensure_enterprise_schema() -> None:
    global _SCHEMA_DONE
    if _SCHEMA_DONE:
        return
    init_db()
    with _connect() as conn:
        conn.executescript('''
            CREATE TABLE IF NOT EXISTS fin_partners (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                partner_type TEXT NOT NULL,
                code TEXT NOT NULL,
                name TEXT NOT NULL,
                contact TEXT,
                phone TEXT,
                balance REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, partner_type, code)
            );
            CREATE TABLE IF NOT EXISTS fin_invoices (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                invoice_type TEXT NOT NULL,
                partner_id INTEGER,
                invoice_no TEXT NOT NULL,
                invoice_date TEXT NOT NULL,
                due_date TEXT,
                amount REAL NOT NULL DEFAULT 0,
                tax_amount REAL NOT NULL DEFAULT 0,
                paid_amount REAL NOT NULL DEFAULT 0,
                status TEXT NOT NULL DEFAULT 'draft',
                summary TEXT,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, invoice_no),
                FOREIGN KEY (partner_id) REFERENCES fin_partners(id)
            );
            CREATE TABLE IF NOT EXISTS fin_invoice_lines (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                invoice_id INTEGER NOT NULL,
                line_no INTEGER NOT NULL,
                item_name TEXT,
                quantity REAL DEFAULT 1,
                unit_price REAL DEFAULT 0,
                amount REAL NOT NULL DEFAULT 0,
                FOREIGN KEY (invoice_id) REFERENCES fin_invoices(id)
            );
            CREATE TABLE IF NOT EXISTS fin_bank_accounts (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                account_code TEXT NOT NULL,
                bank_name TEXT NOT NULL,
                account_no TEXT NOT NULL,
                book_balance REAL NOT NULL DEFAULT 0,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS fin_bank_txns (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                bank_account_id INTEGER NOT NULL,
                txn_date TEXT NOT NULL,
                summary TEXT,
                amount REAL NOT NULL,
                direction TEXT NOT NULL,
                matched INTEGER NOT NULL DEFAULT 0,
                ref_type TEXT,
                ref_id INTEGER,
                created_at TEXT NOT NULL,
                FOREIGN KEY (bank_account_id) REFERENCES fin_bank_accounts(id)
            );
            CREATE TABLE IF NOT EXISTS fin_recon_runs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                bank_account_id INTEGER NOT NULL,
                period_start TEXT,
                period_end TEXT,
                book_balance REAL,
                bank_balance REAL,
                diff_amount REAL,
                status TEXT NOT NULL DEFAULT 'open',
                created_at TEXT NOT NULL,
                FOREIGN KEY (bank_account_id) REFERENCES fin_bank_accounts(id)
            );
            CREATE TABLE IF NOT EXISTS wf_approvals (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                entity_type TEXT NOT NULL,
                entity_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                current_step INTEGER NOT NULL DEFAULT 1,
                total_steps INTEGER NOT NULL DEFAULT 1,
                requester_id INTEGER NOT NULL,
                created_at TEXT NOT NULL,
                finished_at TEXT
            );
            CREATE TABLE IF NOT EXISTS wf_approval_steps (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                approval_id INTEGER NOT NULL,
                step_no INTEGER NOT NULL,
                approver_id INTEGER,
                approver_role TEXT,
                status TEXT NOT NULL DEFAULT 'pending',
                comment TEXT,
                acted_at TEXT,
                FOREIGN KEY (approval_id) REFERENCES wf_approvals(id)
            );
            CREATE TABLE IF NOT EXISTS wf_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                description TEXT,
                assignee_id INTEGER,
                creator_id INTEGER NOT NULL,
                status TEXT NOT NULL DEFAULT 'todo',
                due_date TEXT,
                related_type TEXT,
                related_id INTEGER,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS wf_task_comments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                task_id INTEGER NOT NULL,
                author_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                mentions_json TEXT NOT NULL DEFAULT '[]',
                created_at TEXT NOT NULL,
                FOREIGN KEY (task_id) REFERENCES wf_tasks(id)
            );
            CREATE TABLE IF NOT EXISTS fin_doc_versions (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                doc_type TEXT NOT NULL,
                doc_id INTEGER NOT NULL,
                version_no INTEGER NOT NULL,
                snapshot_json TEXT NOT NULL,
                change_message TEXT,
                author_id INTEGER,
                created_at TEXT NOT NULL,
                UNIQUE(user_id, doc_type, doc_id, version_no)
            );
        ''')
        conn.commit()
    _SCHEMA_DONE = True


def _now() -> str:
    return datetime.now().strftime('%Y-%m-%d %H:%M:%S')


def _json_dumps(obj: Any) -> str:
    return json.dumps(obj, ensure_ascii=False)


def seed_partners(user_id: int) -> None:
    ensure_enterprise_schema()
    now = _now()
    seeds = [
        ('customer', 'C001', '华东科技有限公司', '张经理', '13800001001'),
        ('customer', 'C002', '星海贸易集团', '李总', '13800001002'),
        ('vendor', 'V001', '办公用品供应商', '王会计', '13800002001'),
        ('vendor', 'V002', '云服务科技', '赵工', '13800002002'),
    ]
    with _connect() as conn:
        for ptype, code, name, contact, phone in seeds:
            conn.execute(
                '''INSERT OR IGNORE INTO fin_partners
                   (user_id, partner_type, code, name, contact, phone, balance, created_at)
                   VALUES (?, ?, ?, ?, ?, ?, 0, ?)''',
                (user_id, ptype, code, name, contact, phone, now),
            )
        conn.commit()


def list_partners(user_id: int, partner_type: str | None = None) -> list[dict]:
    ensure_enterprise_schema()
    seed_partners(user_id)
    with _connect() as conn:
        if partner_type:
            rows = conn.execute(
                'SELECT * FROM fin_partners WHERE user_id=? AND partner_type=? ORDER BY code',
                (user_id, partner_type),
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM fin_partners WHERE user_id=? ORDER BY partner_type, code',
                (user_id,),
            ).fetchall()
    return [dict(r) for r in rows]


def create_partner(user_id: int, data: dict) -> int:
    ensure_enterprise_schema()
    now = _now()
    with _connect() as conn:
        cur = conn.execute(
            '''INSERT INTO fin_partners (user_id, partner_type, code, name, contact, phone, balance, created_at)
               VALUES (?, ?, ?, ?, ?, ?, 0, ?)''',
            (user_id, data['partner_type'], data['code'], data['name'],
             data.get('contact', ''), data.get('phone', ''), now),
        )
        conn.commit()
        return int(cur.lastrowid)


def _next_invoice_no(conn, user_id: int, prefix: str) -> str:
    row = conn.execute(
        'SELECT invoice_no FROM fin_invoices WHERE user_id=? AND invoice_no LIKE ? ORDER BY id DESC LIMIT 1',
        (user_id, f'{prefix}%'),
    ).fetchone()
    if not row:
        return f'{prefix}0001'
    try:
        n = int(row['invoice_no'].replace(prefix, '')) + 1
    except ValueError:
        n = 1
    return f'{prefix}{n:04d}'


def list_invoices(user_id: int, invoice_type: str | None = None, limit: int = 100) -> list[dict]:
    ensure_enterprise_schema()
    with _connect() as conn:
        if invoice_type:
            rows = conn.execute(
                '''SELECT i.*, p.name AS partner_name, p.code AS partner_code
                   FROM fin_invoices i LEFT JOIN fin_partners p ON p.id=i.partner_id
                   WHERE i.user_id=? AND i.invoice_type=? ORDER BY i.invoice_date DESC LIMIT ?''',
                (user_id, invoice_type, limit),
            ).fetchall()
        else:
            rows = conn.execute(
                '''SELECT i.*, p.name AS partner_name, p.code AS partner_code
                   FROM fin_invoices i LEFT JOIN fin_partners p ON p.id=i.partner_id
                   WHERE i.user_id=? ORDER BY i.invoice_date DESC LIMIT ?''',
                (user_id, limit),
            ).fetchall()
    return [dict(r) for r in rows]


def create_invoice(user_id: int, data: dict) -> int:
    ensure_enterprise_schema()
    now = _now()
    inv_type = data['invoice_type']
    prefix = 'AR' if inv_type == 'ar' else 'AP'
    lines = data.get('lines') or []
    amount = sum(float(ln.get('amount') or 0) for ln in lines) or float(data.get('amount') or 0)
    with _connect() as conn:
        invoice_no = data.get('invoice_no') or _next_invoice_no(conn, user_id, prefix)
        cur = conn.execute(
            '''INSERT INTO fin_invoices
               (user_id, invoice_type, partner_id, invoice_no, invoice_date, due_date,
                amount, tax_amount, paid_amount, status, summary, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?)''',
            (
                user_id, inv_type, data.get('partner_id'),
                invoice_no, data.get('invoice_date') or now[:10],
                data.get('due_date'), amount, float(data.get('tax_amount') or 0),
                data.get('status', 'issued'), data.get('summary', ''), now,
            ),
        )
        iid = int(cur.lastrowid)
        for i, ln in enumerate(lines, 1):
            conn.execute(
                '''INSERT INTO fin_invoice_lines (invoice_id, line_no, item_name, quantity, unit_price, amount)
                   VALUES (?, ?, ?, ?, ?, ?)''',
                (iid, i, ln.get('item_name', ''), float(ln.get('quantity') or 1),
                 float(ln.get('unit_price') or 0), float(ln.get('amount') or 0)),
            )
        if data.get('partner_id'):
            conn.execute(
                'UPDATE fin_partners SET balance = balance + ? WHERE id=?',
                (amount if inv_type == 'ar' else -amount, data['partner_id']),
            )
        conn.commit()
    return iid


def record_invoice_payment(user_id: int, invoice_id: int, amount: float) -> None:
    ensure_enterprise_schema()
    with _connect() as conn:
        inv = conn.execute('SELECT * FROM fin_invoices WHERE id=? AND user_id=?', (invoice_id, user_id)).fetchone()
        if not inv:
            raise ValueError('发票不存在')
        paid = float(inv['paid_amount']) + amount
        status = 'paid' if paid >= float(inv['amount']) - 0.01 else 'partial'
        conn.execute('UPDATE fin_invoices SET paid_amount=?, status=? WHERE id=?', (paid, status, invoice_id))
        conn.commit()


def seed_bank_accounts(user_id: int) -> None:
    ensure_enterprise_schema()
    from modules.database import ensure_finance_seed
    ensure_finance_seed(user_id)
    now = _now()
    with _connect() as conn:
        if conn.execute('SELECT 1 FROM fin_bank_accounts WHERE user_id=? LIMIT 1', (user_id,)).fetchone():
            return
        acct = conn.execute(
            'SELECT balance FROM fin_accounts WHERE user_id=? AND code=?', (user_id, '1002'),
        ).fetchone()
        bal = float(acct['balance']) if acct else 0
        conn.execute(
            '''INSERT INTO fin_bank_accounts (user_id, account_code, bank_name, account_no, book_balance, created_at)
               VALUES (?, '1002', '中国工商银行', '6222****8888', ?, ?)''',
            (user_id, bal, now),
        )
        conn.commit()


def list_bank_accounts(user_id: int) -> list[dict]:
    ensure_enterprise_schema()
    seed_bank_accounts(user_id)
    with _connect() as conn:
        rows = conn.execute('SELECT * FROM fin_bank_accounts WHERE user_id=?', (user_id,)).fetchall()
    return [dict(r) for r in rows]


def import_bank_txns(user_id: int, bank_account_id: int, txns: list[dict]) -> int:
    ensure_enterprise_schema()
    now = _now()
    with _connect() as conn:
        if not conn.execute(
            'SELECT id FROM fin_bank_accounts WHERE id=? AND user_id=?', (bank_account_id, user_id),
        ).fetchone():
            raise ValueError('银行账户不存在')
        for t in txns:
            amt = float(t['amount'])
            conn.execute(
                '''INSERT INTO fin_bank_txns
                   (bank_account_id, txn_date, summary, amount, direction, matched, created_at)
                   VALUES (?, ?, ?, ?, ?, 0, ?)''',
                (bank_account_id, t['txn_date'], t.get('summary', ''),
                 abs(amt), 'in' if amt >= 0 else 'out', now),
            )
        conn.commit()
    return len(txns)


def list_bank_txns(bank_account_id: int, user_id: int) -> list[dict]:
    ensure_enterprise_schema()
    with _connect() as conn:
        if not conn.execute(
            'SELECT id FROM fin_bank_accounts WHERE id=? AND user_id=?', (bank_account_id, user_id),
        ).fetchone():
            return []
        rows = conn.execute(
            'SELECT * FROM fin_bank_txns WHERE bank_account_id=? ORDER BY txn_date DESC', (bank_account_id,),
        ).fetchall()
    return [dict(r) for r in rows]


def run_reconciliation(user_id: int, bank_account_id: int) -> dict:
    ensure_enterprise_schema()
    now = _now()
    with _connect() as conn:
        ba = conn.execute(
            'SELECT * FROM fin_bank_accounts WHERE id=? AND user_id=?', (bank_account_id, user_id),
        ).fetchone()
        if not ba:
            raise ValueError('银行账户不存在')
        book = float(ba['book_balance'])
        row = conn.execute(
            '''SELECT COALESCE(SUM(CASE WHEN direction='in' THEN amount ELSE -amount END), 0) AS bal
               FROM fin_bank_txns WHERE bank_account_id=?''',
            (bank_account_id,),
        ).fetchone()
        bank_bal = float(row['bal'])
        diff = round(book - bank_bal, 2)
        cur = conn.execute(
            '''INSERT INTO fin_recon_runs
               (user_id, bank_account_id, book_balance, bank_balance, diff_amount, status, created_at)
               VALUES (?, ?, ?, ?, ?, 'completed', ?)''',
            (user_id, bank_account_id, book, bank_bal, diff, now),
        )
        unmatched = conn.execute(
            'SELECT COUNT(*) AS c FROM fin_bank_txns WHERE bank_account_id=? AND matched=0',
            (bank_account_id,),
        ).fetchone()['c']
        conn.commit()
        return {
            'recon_id': int(cur.lastrowid), 'book_balance': book, 'bank_balance': bank_bal,
            'diff_amount': diff, 'unmatched_count': unmatched, 'balanced': abs(diff) < 0.01,
        }


def create_approval(user_id: int, entity_type: str, entity_id: int, title: str, approver_ids: list[int] | None = None) -> int:
    ensure_enterprise_schema()
    now = _now()
    steps = approver_ids or [user_id]
    with _connect() as conn:
        cur = conn.execute(
            '''INSERT INTO wf_approvals
               (user_id, entity_type, entity_id, title, status, current_step, total_steps, requester_id, created_at)
               VALUES (?, ?, ?, ?, 'pending', 1, ?, ?, ?)''',
            (user_id, entity_type, entity_id, title, len(steps), user_id, now),
        )
        aid = int(cur.lastrowid)
        for i, approver in enumerate(steps, 1):
            conn.execute(
                'INSERT INTO wf_approval_steps (approval_id, step_no, approver_id, status) VALUES (?, ?, ?, ?)',
                (aid, i, approver, 'pending'),
            )
        conn.commit()
    _notify_approval(steps[0], title, aid)
    return aid


def list_approvals(user_id: int, scope: str = 'mine') -> list[dict]:
    ensure_enterprise_schema()
    with _connect() as conn:
        if scope == 'pending':
            rows = conn.execute(
                '''SELECT DISTINCT a.* FROM wf_approvals a
                   JOIN wf_approval_steps s ON s.approval_id=a.id
                   WHERE s.approver_id=? AND s.status='pending' AND a.status='pending'
                   AND s.step_no=a.current_step ORDER BY a.created_at DESC''',
                (user_id,),
            ).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM wf_approvals WHERE user_id=? OR requester_id=? ORDER BY created_at DESC LIMIT 100',
                (user_id, user_id),
            ).fetchall()
    return [dict(r) for r in rows]


def act_approval(user_id: int, approval_id: int, action: str, comment: str = '') -> dict:
    ensure_enterprise_schema()
    now = _now()
    with _connect() as conn:
        appr = conn.execute('SELECT * FROM wf_approvals WHERE id=?', (approval_id,)).fetchone()
        if not appr or appr['status'] != 'pending':
            return {'success': False, 'error': '审批不存在或已结束'}
        step = conn.execute(
            'SELECT * FROM wf_approval_steps WHERE approval_id=? AND step_no=? AND approver_id=?',
            (approval_id, appr['current_step'], user_id),
        ).fetchone()
        if not step:
            return {'success': False, 'error': '无权审批此步骤'}
        conn.execute(
            'UPDATE wf_approval_steps SET status=?, comment=?, acted_at=? WHERE id=?',
            (action, comment, now, step['id']),
        )
        if action == 'rejected':
            conn.execute("UPDATE wf_approvals SET status='rejected', finished_at=? WHERE id=?", (now, approval_id))
            conn.commit()
            return {'success': True, 'status': 'rejected'}
        if appr['current_step'] >= appr['total_steps']:
            conn.execute("UPDATE wf_approvals SET status='approved', finished_at=? WHERE id=?", (now, approval_id))
            conn.commit()
            _on_approval_approved(dict(appr))
            return {'success': True, 'status': 'approved'}
        conn.execute('UPDATE wf_approvals SET current_step=current_step+1 WHERE id=?', (approval_id,))
        conn.commit()
        return {'success': True, 'status': 'pending', 'next_step': appr['current_step'] + 1}


def _on_approval_approved(appr: dict) -> None:
    if appr['entity_type'] == 'voucher':
        from modules.database import post_fin_voucher
        try:
            post_fin_voucher(appr['user_id'], appr['entity_id'])
        except Exception:
            pass


def _notify_approval(user_id: int, title: str, approval_id: int) -> None:
    try:
        from modules.database import create_notification
        create_notification(user_id, 'approval', '待您审批', title, f'/workflow/approvals?id={approval_id}')
    except Exception:
        pass


def list_tasks(user_id: int, scope: str = 'assigned') -> list[dict]:
    ensure_enterprise_schema()
    with _connect() as conn:
        if scope == 'created':
            rows = conn.execute('SELECT * FROM wf_tasks WHERE creator_id=? ORDER BY updated_at DESC', (user_id,)).fetchall()
        else:
            rows = conn.execute(
                'SELECT * FROM wf_tasks WHERE assignee_id=? OR user_id=? ORDER BY updated_at DESC', (user_id, user_id),
            ).fetchall()
    return [dict(r) for r in rows]


def create_task(user_id: int, data: dict) -> int:
    ensure_enterprise_schema()
    now = _now()
    with _connect() as conn:
        cur = conn.execute(
            '''INSERT INTO wf_tasks
               (user_id, title, description, assignee_id, creator_id, status, due_date,
                related_type, related_id, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, 'todo', ?, ?, ?, ?, ?)''',
            (user_id, data['title'], data.get('description', ''), data.get('assignee_id'), user_id,
             data.get('due_date'), data.get('related_type'), data.get('related_id'), now, now),
        )
        tid = int(cur.lastrowid)
        conn.commit()
    assignee = data.get('assignee_id')
    if assignee and assignee != user_id:
        _notify_task(assignee, data['title'], tid)
    return tid


def update_task_status(user_id: int, task_id: int, status: str) -> None:
    ensure_enterprise_schema()
    with _connect() as conn:
        conn.execute('UPDATE wf_tasks SET status=?, updated_at=? WHERE id=?', (status, _now(), task_id))
        conn.commit()


def add_task_comment(user_id: int, task_id: int, content: str) -> int:
    ensure_enterprise_schema()
    now = _now()
    mentions = _parse_mentions(content)
    with _connect() as conn:
        cur = conn.execute(
            '''INSERT INTO wf_task_comments (task_id, author_id, content, mentions_json, created_at)
               VALUES (?, ?, ?, ?, ?)''',
            (task_id, user_id, content, _json_dumps(mentions), now),
        )
        conn.execute('UPDATE wf_tasks SET updated_at=? WHERE id=?', (now, task_id))
        conn.commit()
        cid = int(cur.lastrowid)
    for mid in mentions:
        if mid != user_id:
            _notify_mention(mid, task_id, content)
    return cid


def list_task_comments(task_id: int) -> list[dict]:
    ensure_enterprise_schema()
    with _connect() as conn:
        rows = conn.execute(
            '''SELECT c.*, u.username AS author_name FROM wf_task_comments c
               JOIN users u ON u.id=c.author_id WHERE c.task_id=? ORDER BY c.created_at''',
            (task_id,),
        ).fetchall()
    result = []
    for r in rows:
        d = dict(r)
        d['mentions'] = json.loads(d.get('mentions_json') or '[]')
        result.append(d)
    return result


def _parse_mentions(content: str) -> list[int]:
    import re
    ids = []
    for m in re.finditer(r'@(\w+)', content):
        with _connect() as conn:
            row = conn.execute('SELECT id FROM users WHERE username=?', (m.group(1),)).fetchone()
        if row:
            ids.append(int(row['id']))
    return ids


def _notify_task(user_id: int, title: str, task_id: int) -> None:
    try:
        from modules.database import create_notification
        create_notification(user_id, 'task', '新任务', title, f'/workflow/tasks?id={task_id}')
    except Exception:
        pass


def _notify_mention(user_id: int, task_id: int, content: str) -> None:
    try:
        from modules.database import create_notification
        create_notification(user_id, 'mention', '有人在任务中@了你', content[:80], f'/workflow/tasks?id={task_id}')
    except Exception:
        pass


def save_doc_version(user_id: int, doc_type: str, doc_id: int, snapshot: dict, *, message: str = '', author_id: int | None = None) -> int:
    ensure_enterprise_schema()
    now = _now()
    with _connect() as conn:
        row = conn.execute(
            'SELECT COALESCE(MAX(version_no), 0) AS v FROM fin_doc_versions WHERE user_id=? AND doc_type=? AND doc_id=?',
            (user_id, doc_type, doc_id),
        ).fetchone()
        vno = int(row['v']) + 1
        cur = conn.execute(
            '''INSERT INTO fin_doc_versions
               (user_id, doc_type, doc_id, version_no, snapshot_json, change_message, author_id, created_at)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?)''',
            (user_id, doc_type, doc_id, vno, _json_dumps(snapshot), message, author_id or user_id, now),
        )
        conn.commit()
        return int(cur.lastrowid)


def list_doc_versions(user_id: int, doc_type: str, doc_id: int) -> list[dict]:
    ensure_enterprise_schema()
    with _connect() as conn:
        rows = conn.execute(
            '''SELECT v.id, v.version_no, v.change_message, v.author_id, v.created_at, u.username AS author_name
               FROM fin_doc_versions v LEFT JOIN users u ON u.id=v.author_id
               WHERE v.user_id=? AND v.doc_type=? AND v.doc_id=? ORDER BY v.version_no DESC''',
            (user_id, doc_type, doc_id),
        ).fetchall()
    return [dict(r) for r in rows]


def get_doc_version(user_id: int, doc_type: str, doc_id: int, version_no: int) -> dict | None:
    ensure_enterprise_schema()
    with _connect() as conn:
        row = conn.execute(
            '''SELECT v.*, u.username AS author_name FROM fin_doc_versions v
               LEFT JOIN users u ON u.id=v.author_id
               WHERE v.user_id=? AND v.doc_type=? AND v.doc_id=? AND v.version_no=?''',
            (user_id, doc_type, doc_id, version_no),
        ).fetchone()
    if not row:
        return None
    d = dict(row)
    d['snapshot'] = json.loads(d.pop('snapshot_json') or '{}')
    return d
