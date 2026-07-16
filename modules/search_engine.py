"""
开源全文检索引擎（SQLite FTS5）

完全在应用内运行，不依赖百度或任何第三方搜索 API。
"""
from __future__ import annotations

import os
import re
import sqlite3
from pathlib import Path

_DB_PATH = Path(__file__).resolve().parent.parent / 'data' / 'search_index.db'
_README_PATH = Path(__file__).resolve().parent.parent / 'README.md'

# 财务审计知识库
_KNOWLEDGE: list[tuple[str, str, str, str]] = [
    ('应付账款', '负债类科目，记录因采购商品、接受劳务等应向供应商支付的款项。审计需关注截止认定、函证、账龄分析与关联方披露。', '/analysis', '会计科目 负债 应付 应付账款'),
    ('应收账款', '资产类科目，记录因销售商品、提供劳务应向购货方收取的款项。关注坏账计提、账龄分析、函证与收入勾稽。', '/analysis', '会计科目 资产 应收 应收账款'),
    ('其他应收款', '资产类科目，核算除应收账款、预付账款以外的其他各种应收及暂付款项。关注关联方资金占用、长期挂账、可回收性与坏账准备。', '/analysis', '会计科目 资产 其他应收款 应收'),
    ('预付账款', '资产类科目，企业预先支付给供应商的款项。关注长期挂账、商业实质与关联方资金占用。', '/analysis', '会计科目 资产 预付'),
    ('其他应付款', '负债类科目，核算除应付票据、应付账款等以外的其他应付暂收款项。', '/analysis', '会计科目 负债'),
    ('Benford定律', '自然财务数据首位数字呈对数分布；人为编造数据常偏离该规律，是舞弊筛查常用统计方法。', '/analysis', '审计规则 舞弊 Benford 数字分析'),
    ('重复交易检测', '识别凭证号、金额、日期等关键字段完全相同的重复记录，防范重复入账或重复报销。', '/analysis', '审计规则 重复 凭证'),
    ('大额交易检测', '筛选超过设定阈值的交易，识别异常大额支付、资金挪用或关联方非公允交易。', '/analysis', '审计规则 大额 阈值'),
    ('整数取整分析', '金额大量以整百、整千结尾可能暗示人为估算或虚构交易，需结合业务实质判断。', '/analysis', '审计规则 取整 整数'),
    ('负数冲销检测', '异常负数或频繁冲销可能掩盖错误或舞弊，应核对原始凭证与审批流程。', '/analysis', '审计规则 冲销 负数'),
    ('日期异常检测', '识别周末、节假日或未来日期的交易，排查截止日前后人为调节利润的行为。', '/analysis', '审计规则 日期 截止'),
    ('凭证号连续性', '凭证编号断号、跳号可能意味着凭证缺失或销毁，需追查缺号原因。', '/analysis', '审计规则 凭证 断号'),
    ('Z-Score异常检测', '基于标准分数识别远离均值的离群值，适用于发现极端金额或异常波动。', '/analysis', '异常检测 统计 Z-Score'),
    ('IQR离群值', '利用四分位距识别异常值，对非正态分布的财务数据较为稳健。', '/analysis', '异常检测 统计 IQR 四分位'),
    ('审计报告', '汇总规则检测、异常分析与风险评分，支持导出 HTML 与 Excel 供项目组复核。', '/report', '报告 导出 风险'),
    ('数据导入', '支持 CSV、Excel 批量上传及表格截图识别，自动识别金额、日期、凭证等字段。', '/', '上传 导入 CSV Excel'),
    ('表格编辑', '上传后可在线修正字段、增删行列，校对完成后再进入规则检测。', '/edit', '编辑 校对 表格'),
    ('三阶段审计', '风险评估、控制测试与实质性程序三阶段流程，可在审计概览页分步执行。', '/dashboard', '审计流程 内控 实质性程序'),
    ('历史记录', '每次导入与分析自动存档，可随时加载历史数据集继续审计。', '/history', '存档 历史 记录'),
    ('固定资产', '使用年限较长的有形资产。关注资本化与费用化划分、折旧政策一致性及减值测试。', '/analysis', '会计科目 资产 固定资产 折旧'),
    ('存货', '企业持有以备出售的产成品或商品。关注计价方法、盘点程序与跌价准备计提。', '/analysis', '会计科目 资产 存货 盘点'),
    ('营业收入', '企业主营业务产生的收入。审计关注收入确认五步法、截止测试与毛利率异常分析。', '/analysis', '会计科目 损益 收入 确认'),
    ('营业成本', '与营业收入配比的直接成本。关注成本结转、计价方法与毛利率波动。', '/analysis', '会计科目 损益 成本'),
    ('现金流量表', '反映现金及等价物流入流出。关注与利润表、资产负债表的勾稽关系。', '/analysis', '报表 现金流 三大报表'),
    ('资产负债表', '反映特定日期的财务状况。关注资产完整性、负债完整性及报表平衡。', '/analysis', '报表 资产负债'),
    ('利润表', '反映一定期间经营成果。关注收入成本配比、费用资本化与异常波动。', '/analysis', '报表 利润 损益'),
    ('关联方交易', '与关联方之间的交易需充分披露，关注定价公允性、商业实质与资金占用。', '/analysis', '关联交易 披露 关联方'),
    ('函证', '向银行、客户、供应商等第三方发函核实余额，是实质性程序的重要手段。', '/analysis', '审计程序 函证 银行'),
    ('截止测试', '验证交易是否计入正确会计期间，防止跨期调节利润。', '/analysis', '审计程序 截止 跨期'),
    ('重要性水平', '确定错报是否影响报表使用者决策的临界值，指导抽样范围与测试深度。', '/analysis', '审计概念 重要性 抽样'),
    ('舞弊风险', '财务舞弊常表现为虚构收入、隐瞒负债、滥用会计估计。需保持职业怀疑。', '/analysis', '舞弊 风险 职业怀疑'),
    ('内控测试', '评价控制设计和运行有效性，确定实质性程序的性质、时间和范围。', '/dashboard', '内控 控制测试'),
    ('实质性程序', '直接检查交易和余额以发现重大错报，包括细节测试与分析性程序。', '/dashboard', '实质性程序 细节测试'),
    ('增值税', '流转税主要税种。关注销项进项匹配、发票真实性与税负率异常。', '/analysis', '税务 增值税 发票'),
    ('企业所得税', '关注应纳税所得额调整、税前扣除合规性与递延所得税确认。', '/analysis', '税务 所得税 纳税调整'),
]


def _connect() -> sqlite3.Connection:
    _DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(_DB_PATH))
    conn.row_factory = sqlite3.Row
    return conn


def _chunk_readme() -> list[tuple[str, str, str, str]]:
    if not _README_PATH.is_file():
        return []
    text = _README_PATH.read_text(encoding='utf-8', errors='replace')
    chunks: list[tuple[str, str, str, str]] = []
    for block in re.split(r'\n##\s+', text):
        block = block.strip()
        if not block or len(block) < 20:
            continue
        lines = block.splitlines()
        title = lines[0].strip('# ').strip()
        body = '\n'.join(lines[1:]).strip()
        if not title or not body:
            continue
        body = re.sub(r'[#*`|]', '', body)[:400]
        chunks.append((f'文档：{title}', body, '/dashboard', f'文档 README {title}'))
    return chunks


def _collect_history_docs(user_id: int | None = None, limit: int = 200) -> list[tuple[str, str, str, str]]:
    """将历史审计记录标题、文件名、摘要字段编入索引。"""
    try:
        from modules.database import list_history
        records = list_history(limit=limit, user_id=user_id)
    except Exception:
        return []
    docs: list[tuple[str, str, str, str]] = []
    for r in records:
        title = r.get('title') or r.get('filename') or '未命名记录'
        summary = r.get('summary') or {}
        parts = [
            r.get('filename') or '',
            r.get('source_type') or '',
            str(r.get('row_count') or ''),
        ]
        if isinstance(summary, dict):
            for key in ('amount_stats', 'date_range', 'category_counts'):
                block = summary.get(key)
                if isinstance(block, dict):
                    parts.extend(str(v) for v in block.values() if v)
        body = ' · '.join(p for p in parts if p)[:400]
        tags = f'历史记录 {title} {r.get("filename") or ""}'
        docs.append((f'历史：{title}', body or '审计历史记录', '/history', tags))
    return docs


def _collect_table_docs() -> list[tuple[str, str, str, str]]:
    """将当前会话中的表名、列名编入索引。"""
    try:
        from modules.data_processor import get_tables, get_table
        docs: list[tuple[str, str, str, str]] = []
        for t in get_tables():
            tid = t.get('id')
            if not tid:
                continue
            full = get_table(tid)
            if not full:
                continue
            cols = full.get('preview_columns') or []
            filename = full.get('filename') or t.get('filename') or '数据表'
            col_text = ' '.join(str(c) for c in cols[:30])
            docs.append((
                f'数据表：{filename}',
                f'共 {full.get("row_count", 0)} 行，字段：{col_text}',
                '/preview',
                f'上传数据 {filename} {" ".join(str(c) for c in cols)}',
            ))
        return docs
    except Exception:
        return []


def rebuild_index(user_id: int | None = None) -> None:
    """重建全文索引（知识库 + README + 历史记录 + 当前数据表）。"""
    conn = _connect()
    try:
        conn.execute('DROP TABLE IF EXISTS docs')
        conn.execute(
            'CREATE VIRTUAL TABLE docs USING fts5('
            'title, content, url, tags, source, tokenize="unicode61"'
            ')'
        )
        rows = [
            (*item, 'knowledge') for item in _KNOWLEDGE
        ] + [
            (*item, 'readme') for item in _chunk_readme()
        ] + [
            (*item, 'history') for item in _collect_history_docs(user_id)
        ] + [
            (*item, 'table') for item in _collect_table_docs()
        ]
        conn.executemany(
            'INSERT INTO docs(title, content, url, tags, source) VALUES (?,?,?,?,?)',
            rows,
        )
        conn.commit()
    finally:
        conn.close()


def refresh_dynamic_index(user_id: int | None = None) -> None:
    """上传或分析后刷新用户相关索引（历史记录 + 当前表）。"""
    rebuild_index(user_id=user_id)


def _ensure_index(user_id: int | None = None) -> None:
    conn = _connect()
    try:
        exists = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='docs'"
        ).fetchone()
        if not exists:
            rebuild_index(user_id=user_id)
            return
        count = conn.execute('SELECT COUNT(*) FROM docs').fetchone()[0]
        if count == 0:
            rebuild_index(user_id=user_id)
    finally:
        conn.close()


def _fts_search(query: str, limit: int, user_id: int | None = None) -> list[dict]:
    _ensure_index(user_id=user_id)
    conn = _connect()
    try:
        like = f'%{query}%'
        rows = conn.execute(
            '''
            SELECT title, content, url, tags, source, 0 AS rank
            FROM docs
            WHERE title LIKE ? OR content LIKE ? OR tags LIKE ?
            LIMIT ?
            ''',
            (like, like, like, limit),
        ).fetchall()

        if not rows:
            terms = [t for t in query.split() if t]
            fts_q = ' '.join(f'"{t}"' for t in terms) if terms else f'"{query}"'
            rows = conn.execute(
                '''
                SELECT title, content, url, tags, source, bm25(docs) AS rank
                FROM docs
                WHERE docs MATCH ?
                ORDER BY rank
                LIMIT ?
                ''',
                (fts_q, limit),
            ).fetchall()

        return [
            {
                'title': r['title'],
                'content': r['content'],
                'url': r['url'],
                'engine': 'SQLite FTS5',
                'source': r['source'],
            }
            for r in rows
        ]
    except sqlite3.OperationalError:
        rebuild_index(user_id=user_id)
        return _fts_search(query, limit, user_id=user_id)
    finally:
        conn.close()


def _history_search(user_id: int | None, query: str, limit: int) -> list[dict]:
    if not user_id:
        return []
    try:
        from modules.database import list_history
        records = list_history(limit=limit, user_id=user_id, q=query)
        return [
            {
                'title': f'历史：{r.get("title") or r.get("filename") or "未命名"}',
                'content': (
                    f'{r.get("created_at", "")} · '
                    f'{r.get("row_count") or 0} 行 · '
                    f'来源 {r.get("source_type", "")}'
                ),
                'url': '/history',
                'engine': '历史记录',
                'source': 'history',
            }
            for r in records
        ]
    except Exception:
        return []


def search(query: str, user_id: int | None = None, limit: int = 20) -> dict:
    """
    开源全文检索入口。
    引擎：SQLite FTS5（内置，离线可用）
    """
    query = (query or '').strip()
    if not query:
        return {
            'success': False,
            'query': '',
            'results': [],
            'error': '请输入搜索关键词',
            'engine': 'SQLite FTS5',
        }

    fts_limit = max(limit - 5, 8)
    results = _fts_search(query, fts_limit, user_id=user_id)
    results.extend(_history_search(user_id, query, limit=5))

    # 去重（按标题）
    seen: set[str] = set()
    unique: list[dict] = []
    for item in results:
        key = item['title']
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
        if len(unique) >= limit:
            break

    return {
        'success': bool(unique),
        'query': query,
        'results': unique,
        'total': len(unique),
        'engine': 'SQLite FTS5',
        'engine_note': 'SQLite FTS5 + BM25 相关性排序，已索引知识库、历史记录与上传数据',
    }
