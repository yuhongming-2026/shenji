"""
实质性程序 - 12项详细实质性审计程序

包含：凭证抽查、存货计价测试、费用截止测试、货币资金审计、
往来款项审计、存货审计、固定资产审计、收入成本审计、费用审计、
税费审计、期后事项审计、或有事项与持续经营评估
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from modules.audit_data_helpers import detect_financial_columns, analyze_concentration


# ============================================================
# 内部辅助
# ============================================================

def _detect_columns(df: pd.DataFrame) -> dict[str, str | None]:
    cols = detect_financial_columns(df)
    return {
        'amount': cols['amount'][0] if cols['amount'] else None,
        'date': cols['date'][0] if cols['date'] else None,
        'category': cols['category'][0] if cols['category'] else None,
        'voucher': cols['voucher'][0] if cols['voucher'] else None,
        'customer': cols['customer'][0] if cols['customer'] else None,
        'supplier': cols['supplier'][0] if cols['supplier'] else None,
        'counterparty': cols['counterparty'][0] if cols['counterparty'] else None,
        'receivable': cols['receivable'][0] if cols['receivable'] else None,
        'payable': cols['payable'][0] if cols['payable'] else None,
        'inventory': cols['inventory'][0] if cols['inventory'] else None,
        'fixed_asset': cols['fixed_asset'][0] if cols['fixed_asset'] else None,
        'bank': cols['bank'][0] if cols['bank'] else None,
        'revenue': cols['revenue'][0] if cols['revenue'] else None,
        'cost': cols['cost'][0] if cols['cost'] else None,
        'expense': cols['expense'][0] if cols['expense'] else None,
        'tax': cols['tax'][0] if cols['tax'] else None,
        'department': cols['department'][0] if cols['department'] else None,
        'approver': cols['approver'][0] if cols['approver'] else None,
    }


def _safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors='coerce')


def _as_float(val) -> float:
    try:
        return float(val)
    except (ValueError, TypeError):
        return 0.0


# ============================================================
# 1. 凭证抽查
# ============================================================

def inspect_vouchers(
    df: pd.DataFrame,
    amount_col: str | None = None,
    voucher_col: str | None = None,
    date_col: str | None = None,
    approver_col: str | None = None,
    sample_size: int = 20,
) -> dict:
    """
    凭证抽查：模拟 OCR 识别发票/报销单与记账凭证核对，
    标记金额不符、审批不全等问题。

    抽样策略：高风险（大额 + 整数金额 + 日期异常）优先。
    """
    cols = _detect_columns(df)
    amount_col = amount_col or cols['amount']
    voucher_col = voucher_col or cols['voucher']
    date_col = date_col or cols['date']
    approver_col = approver_col or cols['approver']

    total = len(df)
    findings = []

    if amount_col is None:
        return {
            'rule': 'voucher_inspection', 'name': '凭证抽查',
            'suspicious': False, 'risk': 'low', 'findings': [],
            'description': '未检测到金额列',
        }

    amounts = _safe_numeric(df[amount_col])
    # 风险评分：大额 + 整数金额 + 缺失审批
    risk_scores = np.zeros(total)

    if len(amounts.dropna()) > 0:
        median = amounts.median()
        mad = (amounts - median).abs().median() or 1.0
        risk_scores += np.minimum(np.abs(amounts.fillna(0) - median) / mad, 5)

    # 整数金额加分
    int_mask = amounts.fillna(0) % 1 == 0
    risk_scores += int_mask.astype(float) * 0.5

    # 缺失审批加分
    if approver_col:
        missing_approval = df[approver_col].isna().astype(float)
        risk_scores += missing_approval * 3

    # 抽取高风险样本
    n_sample = min(sample_size, total)
    if n_sample > 0:
        top_indices = np.argsort(risk_scores)[-n_sample:][::-1]
    else:
        top_indices = []

    for idx in top_indices:
        row = df.iloc[idx]
        issues = []

        amt = _as_float(row[amount_col])
        if amt == 0:
            issues.append('零值交易')
        elif amt > amounts.median() * 3:
            issues.append(f'大额交易（金额={amt:,.0f}，>中位数3倍）')

        if approver_col and pd.isna(row.get(approver_col)):
            issues.append('缺少审批记录')
        if voucher_col and pd.isna(row.get(voucher_col)):
            issues.append('缺少凭证编号')

        # 模拟发票信息抽取（实际需OCR，此处做逻辑推断）
        simulated_invoice = {
            'matched': len(issues) == 0,
            'amount_match': True,
            'approval_complete': not (approver_col and pd.isna(row.get(approver_col))),
            'voucher_present': not (voucher_col and pd.isna(row.get(voucher_col))),
            'risk_flags': issues,
        }

        findings.append({
            'index': int(idx),
            'amount': amt,
            'date': str(row[date_col]) if date_col and date_col in df.columns else None,
            'voucher': str(row[voucher_col]) if voucher_col and voucher_col in df.columns else None,
            'issues': issues,
            'invoice_check': simulated_invoice,
            'risk': 'high' if len(issues) >= 2 else ('medium' if len(issues) == 1 else 'low'),
        })

    suspicious_count = sum(1 for f in findings if f['risk'] != 'low')
    risk = 'high' if suspicious_count > n_sample * 0.3 else ('medium' if suspicious_count > 0 else 'low')

    return {
        'rule': 'voucher_inspection',
        'name': '凭证抽查',
        'suspicious': suspicious_count > 0,
        'risk': risk,
        'sample_size': n_sample,
        'suspicious_count': suspicious_count,
        'findings': findings,
        'description': f"抽查{n_sample}笔凭证，发现{suspicious_count}笔异常",
    }


# ============================================================
# 2. 存货计价测试
# ============================================================

def test_inventory_valuation(
    df: pd.DataFrame,
    method: str = 'weighted_avg',
    cost_col: str | None = None,
    qty_col: str | None = None,
    book_cost_col: str | None = None,
) -> dict:
    """
    存货计价测试：分别按 FIFO、加权平均法计算存货成本，与账面成本对比。
    """
    cols = _detect_columns(df)
    cost_col = cost_col or cols['cost'] or cols['amount']
    qty_col = qty_col or cols['inventory']
    book_cost_col = book_cost_col or cols['amount']

    if cost_col is None:
        return {
            'rule': 'inventory_valuation', 'name': '存货计价测试',
            'suspicious': False, 'risk': 'low', 'findings': [],
            'description': '未检测到成本/数量列',
        }

    costs = _safe_numeric(df[cost_col]).dropna()

    # 模拟：假设数据中包含成本和数量信息
    findings = []
    total = len(df)

    # 加权平均法
    avg_cost = float(costs.mean())
    # FIFO 模拟：按时序取最早的成本
    fifo_cost = float(costs.iloc[:max(1, len(costs) // 2)].mean()) if len(costs) > 1 else avg_cost
    waffo_cost = float(costs.median())

    # 计算差异
    book_cost = float(costs.iloc[-1]) if len(costs) > 0 else 0

    calculated = {
        'fifo': round(fifo_cost, 2),
        'weighted_average': round(avg_cost, 2),
        'moving_average': round(waffo_cost, 2),
        'method_used': method,
    }

    if book_cost > 0 and avg_cost > 0:
        diff_pct = abs(book_cost - avg_cost) / avg_cost * 100
        if diff_pct > 10:
            findings.append({
                'type': '计价差异', 'risk': 'high',
                'book_value': round(book_cost, 2),
                'calculated_value': round(avg_cost, 2),
                'difference_pct': round(diff_pct, 2),
                'description': f'账面成本与加权平均成本差异{diff_pct:.1f}%，超过10%阈值',
            })
        elif diff_pct > 5:
            findings.append({
                'type': '计价差异', 'risk': 'medium',
                'book_value': round(book_cost, 2),
                'calculated_value': round(avg_cost, 2),
                'difference_pct': round(diff_pct, 2),
                'description': f'账面成本与加权平均成本差异{diff_pct:.1f}%',
            })

    risk = 'high' if any(f['risk'] == 'high' for f in findings) else ('medium' if findings else 'low')

    return {
        'rule': 'inventory_valuation',
        'name': '存货计价测试',
        'suspicious': len(findings) > 0,
        'risk': risk,
        'method': method,
        'calculated_costs': calculated,
        'book_cost': round(book_cost, 2),
        'findings': findings,
        'description': f"{method}法计算成本={calculated.get(method, avg_cost):.2f}，账面={book_cost:.2f}" +
                       (f"，差异{abs(book_cost-avg_cost)/max(avg_cost,1)*100:.1f}%" if book_cost and avg_cost else ""),
    }


# ============================================================
# 3. 费用截止测试
# ============================================================

def test_expense_cutoff(
    df: pd.DataFrame,
    date_col: str | None = None,
    amount_col: str | None = None,
    bs_date: str | None = None,
    days_window: int = 15,
) -> dict:
    """
    费用截止测试：筛选资产负债表日前后的费用凭证，标记跨期费用。
    """
    cols = _detect_columns(df)
    date_col = date_col or cols['date']
    amount_col = amount_col or cols['amount'] or cols['expense']

    if date_col is None:
        return {
            'rule': 'expense_cutoff', 'name': '费用截止测试',
            'suspicious': False, 'risk': 'low', 'findings': [],
            'description': '未检测到日期列',
        }

    try:
        dates = pd.to_datetime(df[date_col], errors='coerce')
    except Exception:
        return {
            'rule': 'expense_cutoff', 'name': '费用截止测试',
            'suspicious': False, 'risk': 'low', 'findings': [],
            'description': '日期列解析失败',
        }

    # 如果没有指定 BS 日期，自动推断（数据的中间日期或年末）
    valid_dates = dates.dropna()
    if len(valid_dates) == 0:
        return {
            'rule': 'expense_cutoff', 'name': '费用截止测试',
            'suspicious': False, 'risk': 'low', 'findings': [],
            'description': '无有效日期数据',
        }

    if bs_date:
        bs_dt = pd.Timestamp(bs_date)
    else:
        # 自动推断：取数据范围的中点或最近的年末/季末
        mid_date = valid_dates.median()
        # 取最近的季度末
        quarter_end_month = ((mid_date.month - 1) // 3 + 1) * 3
        bs_dt = pd.Timestamp(year=mid_date.year, month=quarter_end_month, day=1) + pd.offsets.MonthEnd(1)
        if bs_dt > mid_date:
            bs_dt = bs_dt - pd.DateOffset(months=3)

    # 筛选窗口期
    window_start = bs_dt - timedelta(days=days_window)
    window_end = bs_dt + timedelta(days=days_window)

    in_window = (dates >= window_start) & (dates <= window_end)
    window_df = df[in_window].copy()
    window_df['_date'] = dates[in_window]

    pre_bs = window_df[window_df['_date'] <= bs_dt]
    post_bs = window_df[window_df['_date'] > bs_dt]

    findings = []

    # 检查 BS 日前后大额交易
    if amount_col:
        pre_amounts = _safe_numeric(pre_bs[amount_col]) if len(pre_bs) > 0 else pd.Series()
        post_amounts = _safe_numeric(post_bs[amount_col]) if len(post_bs) > 0 else pd.Series()

        pre_total = float(pre_amounts.sum())
        post_total = float(post_amounts.sum())

        # 大额不对称：如果 BS 日前后的费用差异巨大
        if pre_total > 0 or post_total > 0:
            if pre_total > post_total * 3:
                findings.append({
                    'type': '跨期费用-前置', 'risk': 'high',
                    'pre_bs_total': round(pre_total, 2),
                    'post_bs_total': round(post_total, 2),
                    'description': f'BS日前{days_window}天费用({pre_total:,.0f})远超BS日后({post_total:,.0f})，可能存在提前确认费用',
                })
            elif post_total > pre_total * 3:
                findings.append({
                    'type': '跨期费用-后置', 'risk': 'high',
                    'pre_bs_total': round(pre_total, 2),
                    'post_bs_total': round(post_total, 2),
                    'description': f'BS日后{days_window}天费用({post_total:,.0f})远超BS日前({pre_total:,.0f})，可能存在推迟确认费用',
                })

    risk = 'high' if any(f['risk'] == 'high' for f in findings) else ('medium' if findings else 'low')

    return {
        'rule': 'expense_cutoff',
        'name': '费用截止测试',
        'suspicious': len(findings) > 0,
        'risk': risk,
        'bs_date': bs_dt.strftime('%Y-%m-%d'),
        'window_days': days_window,
        'pre_bs_count': len(pre_bs),
        'post_bs_count': len(post_bs),
        'findings': findings,
        'description': f"截止日{bs_dt.strftime('%Y-%m-%d')}前后{days_window}天：前{len(pre_bs)}笔/后{len(post_bs)}笔" +
                       (f"，发现{len(findings)}项截止问题" if findings else "，未发现截止问题"),
    }


# ============================================================
# 4. 货币资金审计
# ============================================================

def audit_cash_bank(
    df: pd.DataFrame,
    amount_col: str | None = None,
    bank_col: str | None = None,
    date_col: str | None = None,
) -> dict:
    """
    货币资金审计：银行函证模拟、现金盘点分析。
    """
    cols = _detect_columns(df)
    amount_col = amount_col or cols['amount'] or cols['bank']
    bank_col = bank_col or cols['bank'] or cols['category']
    date_col = date_col or cols['date']

    findings = []
    amount_stats = {}

    if amount_col:
        amounts = _safe_numeric(df[amount_col]).dropna()
        if len(amounts) > 0:
            amount_stats = {
                'total': round(float(amounts.sum()), 2),
                'mean': round(float(amounts.mean()), 2),
                'max': round(float(amounts.max()), 2),
                'min': round(float(amounts.min()), 2),
                'std': round(float(amounts.std()), 2),
                'negative_count': int((amounts < 0).sum()),
            }

            # 负值警报
            if amount_stats['negative_count'] > 0:
                findings.append({
                    'type': '负值货币资金', 'risk': 'high',
                    'count': amount_stats['negative_count'],
                    'description': f'发现{amount_stats["negative_count"]}条负值货币资金记录，存在银行透支或记账错误',
                })

            # 异常大额波动
            if amount_stats['std'] > amount_stats['mean'] * 2:
                findings.append({
                    'type': '大额波动', 'risk': 'medium',
                    'std': amount_stats['std'],
                    'description': f'货币资金波动过大（标准差={amount_stats["std"]:,.0f}，均值={amount_stats["mean"]:,.0f}）',
                })

    # 银行分布分析
    bank_distribution = {}
    if bank_col:
        banks = df[bank_col].fillna('未知').value_counts()
        bank_distribution = {k: int(v) for k, v in banks.head(10).items()}

    risk = 'high' if any(f['risk'] == 'high' for f in findings) else ('medium' if findings else 'low')

    return {
        'rule': 'cash_bank', 'name': '货币资金审计',
        'suspicious': len(findings) > 0,
        'risk': risk,
        'amount_stats': amount_stats,
        'bank_distribution': bank_distribution,
        'findings': findings,
        'description': f"货币资金审计" + (f"：发现{len(findings)}项问题" if findings else "：未发现重大问题"),
    }


# ============================================================
# 5-12. 以下为其余实质性程序（简化但实用）
# ============================================================

def audit_receivables_payables(
    df: pd.DataFrame,
    amount_col: str | None = None,
    counterparty_col: str | None = None,
    date_col: str | None = None,
) -> dict:
    """往来款项审计：函证模拟、账龄分析"""
    cols = _detect_columns(df)
    amount_col = amount_col or cols['amount'] or cols['receivable'] or cols['payable']
    counterparty_col = counterparty_col or cols['counterparty'] or cols['customer'] or cols['supplier']
    date_col = date_col or cols['date']

    findings = []
    aging = {}
    concentration = {}

    if amount_col and counterparty_col:
        amounts = _safe_numeric(df[amount_col])
        parties = df[counterparty_col].fillna('未知')

        # 账龄分析（基于日期）
        if date_col:
            try:
                dates = pd.to_datetime(df[date_col], errors='coerce')
                now = dates.max() if dates.notna().any() else datetime.now()
                age_days = (now - dates).dt.days

                aging_bins = [0, 30, 90, 180, 365, float('inf')]
                aging_labels = ['30天内', '31-90天', '91-180天', '181-365天', '1年以上']
                age_group = pd.cut(age_days.fillna(0), bins=aging_bins, labels=aging_labels)
                aging_amounts = amounts.groupby(age_group).sum()
                aging = {str(k): round(float(v), 2) for k, v in aging_amounts.items()}

                long_overdue = aging_amounts.get('1年以上', 0) + aging_amounts.get('181-365天', 0)
                total_amounts = float(amounts.sum())
                if total_amounts > 0 and long_overdue / total_amounts > 0.2:
                    findings.append({
                        'type': '长期挂账', 'risk': 'high',
                        'overdue_ratio': round(float(long_overdue) / max(total_amounts, 1) * 100, 1),
                        'description': f'长期挂账（>180天）占比{float(long_overdue)/max(total_amounts,1)*100:.1f}%，坏账风险高',
                    })
            except Exception:
                pass

        # 集中度分析
        party_amounts = amounts.groupby(parties).sum()
        concentration = analyze_concentration(party_amounts.values, party_amounts.index.tolist())
        if concentration.get('concentration') == 'high':
            findings.append({
                'type': '对手方集中', 'risk': 'high',
                'hhi': concentration['hhi'],
                'description': f"往来款项集中度过高（HHI={concentration['hhi']:.0f}），前几位占比{concentration['top_n_pct']}%",
            })

    risk = 'high' if any(f['risk'] == 'high' for f in findings) else ('medium' if findings else 'low')

    return {
        'rule': 'receivables_payables', 'name': '往来款项审计',
        'suspicious': len(findings) > 0,
        'risk': risk,
        'aging': aging,
        'concentration': concentration,
        'findings': findings,
        'description': f"往来款项审计" + (f"：发现{len(findings)}项问题" if findings else "：未发现重大问题"),
    }


def audit_inventory(
    df: pd.DataFrame,
    amount_col: str | None = None,
    qty_col: str | None = None,
    date_col: str | None = None,
) -> dict:
    """存货审计：监盘分析、计价测试"""
    cols = _detect_columns(df)
    amount_col = amount_col or cols['amount'] or cols['inventory']
    date_col = date_col or cols['date']

    findings = []

    if amount_col:
        amounts = _safe_numeric(df[amount_col]).dropna()
        if len(amounts) > 0:
            negative_count = int((amounts < 0).sum())
            zero_count = int((amounts == 0).sum())

            if negative_count > 0:
                findings.append({
                    'type': '负库存', 'risk': 'high',
                    'count': negative_count,
                    'description': f'发现{negative_count}条负值库存记录，存货监盘异常',
                })
            if zero_count > len(amounts) * 0.3:
                findings.append({
                    'type': '零值库存', 'risk': 'medium',
                    'count': zero_count,
                    'description': f'零值库存占{zero_count/max(len(amounts),1)*100:.1f}%，可能未及时更新',
                })

            # 异常波动
            cv = float(amounts.std() / max(abs(amounts.mean()), 1))
            if cv > 2:
                findings.append({
                    'type': '存货波动', 'risk': 'medium',
                    'cv': round(cv, 2),
                    'description': f'存货价值波动系数={cv:.2f}，波动过大',
                })

    risk = 'high' if any(f['risk'] == 'high' for f in findings) else ('medium' if findings else 'low')

    return {
        'rule': 'inventory', 'name': '存货审计',
        'suspicious': len(findings) > 0,
        'risk': risk, 'findings': findings,
        'description': f"存货审计" + (f"：发现{len(findings)}项问题" if findings else "：未发现重大问题"),
    }


def audit_fixed_assets(
    df: pd.DataFrame,
    amount_col: str | None = None,
    date_col: str | None = None,
    depreciation_rate: float = 0.05,
) -> dict:
    """固定资产审计：盘点分析、折旧测算（直线法）"""
    cols = _detect_columns(df)
    amount_col = amount_col or cols['amount'] or cols['fixed_asset']

    findings = []
    depreciation_schedule = []

    if amount_col:
        amounts = _safe_numeric(df[amount_col]).dropna()
        if len(amounts) > 0:
            total_assets = float(amounts.sum())
            # 模拟折旧计算
            for i in range(min(5, len(amounts))):
                yr = f'第{i+1}年'
                annual_dep = round(total_assets * depreciation_rate, 2)
                nbv = round(total_assets - annual_dep * (i + 1), 2)
                depreciation_schedule.append({
                    'year': yr, 'annual_depreciation': annual_dep, 'net_book_value': max(nbv, 0),
                })

            # 检查异常
            zero_count = int((amounts == 0).sum())
            if zero_count > 0:
                findings.append({
                    'type': '零值资产', 'risk': 'medium',
                    'count': zero_count,
                    'description': f'{zero_count}项零值固定资产，需核实是否已处置或报废',
                })

    risk = 'low' if not findings else 'medium'

    return {
        'rule': 'fixed_assets', 'name': '固定资产审计',
        'suspicious': len(findings) > 0,
        'risk': risk,
        'depreciation_method': '直线法',
        'depreciation_rate': depreciation_rate,
        'depreciation_schedule': depreciation_schedule,
        'findings': findings,
        'description': f"固定资产审计（折旧率{depreciation_rate*100:.0f}%）" + (f"：发现{len(findings)}项问题" if findings else ""),
    }


def audit_revenue_cost(
    df: pd.DataFrame,
    amount_col: str | None = None,
    revenue_col: str | None = None,
    cost_col: str | None = None,
    date_col: str | None = None,
) -> dict:
    """收入成本审计：截止测试、毛利率分析"""
    cols = _detect_columns(df)
    amount_col = amount_col or cols['amount']
    revenue_col = revenue_col or cols['revenue']
    cost_col = cost_col or cols['cost']
    date_col = date_col or cols['date']

    findings = []
    margin_analysis = {}

    # 毛利率分析
    rev_col = revenue_col or amount_col
    if rev_col and cost_col:
        revenue = _safe_numeric(df[rev_col]).sum()
        cost = _safe_numeric(df[cost_col]).sum()
        if revenue > 0:
            gross_margin = float((revenue - cost) / revenue)
            margin_analysis = {
                'revenue': round(float(revenue), 2),
                'cost': round(float(cost), 2),
                'gross_profit': round(float(revenue - cost), 2),
                'gross_margin': round(gross_margin * 100, 2),
            }

            if gross_margin < 0.05:
                findings.append({
                    'type': '毛利率偏低', 'risk': 'high',
                    'margin': round(gross_margin * 100, 2),
                    'description': f'毛利率仅{gross_margin*100:.2f}%，显著偏低，需关注收入确认或成本归集',
                })
            elif gross_margin < 0.15:
                findings.append({
                    'type': '毛利率偏低', 'risk': 'medium',
                    'margin': round(gross_margin * 100, 2),
                    'description': f'毛利率{gross_margin*100:.2f}%偏低',
                })
        elif revenue < 0:
            findings.append({
                'type': '负收入', 'risk': 'high',
                'description': '存在负收入，可能是销售退回或冲销异常',
            })

    risk = 'high' if any(f['risk'] == 'high' for f in findings) else ('medium' if findings else 'low')

    return {
        'rule': 'revenue_cost', 'name': '收入成本审计',
        'suspicious': len(findings) > 0,
        'risk': risk,
        'margin_analysis': margin_analysis,
        'findings': findings,
        'description': f"毛利率{margin_analysis.get('gross_margin', 'N/A')}%" + (f"，发现{len(findings)}项问题" if findings else ""),
    }


def audit_expenses(
    df: pd.DataFrame,
    amount_col: str | None = None,
    category_col: str | None = None,
    date_col: str | None = None,
) -> dict:
    """费用审计：异常支出检查、分类分析"""
    cols = _detect_columns(df)
    amount_col = amount_col or cols['amount'] or cols['expense']
    category_col = category_col or cols['category']
    date_col = date_col or cols['date']

    findings = []
    category_breakdown = {}

    if amount_col:
        amounts = _safe_numeric(df[amount_col]).dropna()
        if len(amounts) > 0:
            mean = amounts.mean()
            std = amounts.std() or 1.0
            # Z-Score 检测异常费用
            z_scores = np.abs((amounts.values - mean) / std)
            anomaly_idx = np.where(z_scores > 3)[0]

            if len(anomaly_idx) > 0:
                top_anomalies = []
                for idx in anomaly_idx[:10]:
                    row = df.iloc[idx]
                    top_anomalies.append({
                        'index': int(idx),
                        'amount': float(amounts.iloc[idx]),
                        'zscore': round(float(z_scores[idx]), 2),
                        'category': str(row[category_col]) if category_col and category_col in df.columns else None,
                        'date': str(row[date_col]) if date_col and date_col in df.columns else None,
                    })
                findings.append({
                    'type': '异常大额支出', 'risk': 'high',
                    'count': len(anomaly_idx),
                    'top_anomalies': top_anomalies,
                    'description': f'{len(anomaly_idx)}笔支出偏离均值超过3倍标准差，需逐一核实',
                })

    # 费用分类分布
    if category_col:
        cat_amounts = amounts.groupby(df[category_col].fillna('未知')).sum()
        category_breakdown = {str(k): round(float(v), 2) for k, v in cat_amounts.head(10).items()}

    risk = 'high' if any(f['risk'] == 'high' for f in findings) else ('medium' if findings else 'low')

    return {
        'rule': 'expenses', 'name': '费用审计',
        'suspicious': len(findings) > 0,
        'risk': risk,
        'category_breakdown': category_breakdown,
        'findings': findings,
        'description': f"费用审计" + (f"：发现{len(findings)}项问题" if findings else "：未发现异常"),
    }


def audit_taxes(
    df: pd.DataFrame,
    amount_col: str | None = None,
    tax_col: str | None = None,
    tax_rate: float = 0.25,
) -> dict:
    """税费审计：税费测算、申报核对"""
    cols = _detect_columns(df)
    amount_col = amount_col or cols['amount'] or cols['tax']
    tax_col = tax_col or cols['tax']

    findings = []

    if amount_col:
        amounts = _safe_numeric(df[amount_col]).dropna()
        if len(amounts) > 0:
            total = float(amounts.sum())
            estimated_tax = round(total * tax_rate, 2)

            # 如果有税金列，做比对
            if tax_col:
                actual_tax = float(_safe_numeric(df[tax_col]).sum())
                if actual_tax > 0 and estimated_tax > 0:
                    diff_pct = abs(actual_tax - estimated_tax) / estimated_tax * 100
                    if diff_pct > 20:
                        findings.append({
                            'type': '税费差异', 'risk': 'high',
                            'estimated': estimated_tax,
                            'actual': actual_tax,
                            'difference_pct': round(diff_pct, 1),
                            'description': f'估算税费({estimated_tax:,.0f})与实际税费({actual_tax:,.0f})差异{diff_pct:.1f}%，存在少缴或多缴风险',
                        })
            else:
                findings.append({
                    'type': '税费估算', 'risk': 'low',
                    'estimated_tax': estimated_tax,
                    'description': f'基于税率{tax_rate*100:.0f}%估算应缴税费约{estimated_tax:,.0f}元（无实际税金列可比对）',
                })

    risk = 'high' if any(f['risk'] == 'high' for f in findings) else ('medium' if findings else 'low')

    return {
        'rule': 'taxes', 'name': '税费审计',
        'suspicious': len(findings) > 0,
        'risk': risk,
        'tax_rate': tax_rate,
        'findings': findings,
        'description': f"税费审计（税率{tax_rate*100:.0f}%）" + (f"：发现{len(findings)}项问题" if findings else ""),
    }


def audit_subsequent_events(
    df: pd.DataFrame,
    date_col: str | None = None,
    amount_col: str | None = None,
    bs_date: str | None = None,
    lookback_days: int = 30,
) -> dict:
    """期后事项审计：资产负债表日后重大事项检查"""
    cols = _detect_columns(df)
    date_col = date_col or cols['date']
    amount_col = amount_col or cols['amount']

    findings = []

    if date_col:
        try:
            dates = pd.to_datetime(df[date_col], errors='coerce').dropna()
            if len(dates) > 0:
                if bs_date:
                    bs_dt = pd.Timestamp(bs_date)
                else:
                    bs_dt = dates.median()

                post_bs = dates[dates > bs_dt]
                pre_bs = dates[dates <= bs_dt]

                if len(post_bs) > 0:
                    if amount_col:
                        post_amounts = _safe_numeric(df.loc[post_bs.index, amount_col])
                        total_post = float(post_amounts.sum())

                        if total_post > 0:
                            findings.append({
                                'type': '期后重大交易', 'risk': 'medium',
                                'bs_date': bs_dt.strftime('%Y-%m-%d'),
                                'post_bs_count': len(post_bs),
                                'post_bs_total': round(total_post, 2),
                                'description': f'资产负债表日后发生{len(post_bs)}笔交易（合计{total_post:,.0f}），需评估是否需调整或披露',
                            })

                # 评估持续经营信号
                if len(pre_bs) > len(post_bs) * 3 and len(pre_bs) > 10:
                    findings.append({
                        'type': '交易骤减', 'risk': 'high',
                        'pre_bs_count': len(pre_bs),
                        'post_bs_count': len(post_bs),
                        'description': f'期后交易({len(post_bs)}笔)远少于此前的{len(pre_bs)}笔，是否存在持续经营问题',
                    })
        except Exception:
            pass

    risk = 'high' if any(f['risk'] == 'high' for f in findings) else ('medium' if findings else 'low')

    return {
        'rule': 'subsequent_events', 'name': '期后事项审计',
        'suspicious': len(findings) > 0,
        'risk': risk, 'findings': findings,
        'description': f"期后事项审计" + (f"：发现{len(findings)}项需关注事项" if findings else "：未发现重大期后事项"),
    }


def audit_contingencies_going_concern(
    df: pd.DataFrame,
    amount_col: str | None = None,
    date_col: str | None = None,
) -> dict:
    """或有事项与持续经营能力评估"""
    cols = _detect_columns(df)
    amount_col = amount_col or cols['amount']
    date_col = date_col or cols['date']

    findings = []
    indicators = {}

    if amount_col:
        amounts = _safe_numeric(df[amount_col]).dropna()
        if len(amounts) > 0:
            # 亏损信号
            negative_pct = (amounts < 0).sum() / len(amounts) * 100
            indicators['negative_pct'] = round(negative_pct, 1)

            if negative_pct > 50:
                findings.append({
                    'type': '持续亏损', 'risk': 'high',
                    'negative_ratio': round(negative_pct, 1),
                    'description': f'超50%记录为负值（{negative_pct:.1f}%），持续经营能力存疑',
                })

            # 趋势下降
            if date_col:
                try:
                    dates = pd.to_datetime(df[date_col], errors='coerce')
                    valid = dates.notna() & pd.to_numeric(df[amount_col], errors='coerce').notna()
                    if valid.sum() >= 6:
                        chronological = df[valid].sort_values(date_col)
                        chron_amounts = _safe_numeric(chronological[amount_col]).values
                        mid = len(chron_amounts) // 2
                        first_half = np.mean(chron_amounts[:mid])
                        second_half = np.mean(chron_amounts[mid:])
                        indicators['trend'] = '上升' if second_half > first_half else '下降'
                        indicators['change_pct'] = round(float((second_half - first_half) / max(abs(first_half), 1) * 100), 1)

                        if first_half > 0 and second_half < first_half * 0.5:
                            findings.append({
                                'type': '收入/资金断崖下降', 'risk': 'high',
                                'first_half_avg': round(float(first_half), 2),
                                'second_half_avg': round(float(second_half), 2),
                                'description': f'后期均值({second_half:.0f})较前期({first_half:.0f})下降{abs(indicators["change_pct"]):.1f}%，持续经营能力需评估',
                            })
                except Exception:
                    pass

    risk = 'high' if any(f['risk'] == 'high' for f in findings) else ('medium' if findings else 'low')

    return {
        'rule': 'contingencies_going_concern', 'name': '或有事项与持续经营评估',
        'suspicious': len(findings) > 0,
        'risk': risk,
        'indicators': indicators,
        'findings': findings,
        'description': f"持续经营评估" + (f"：发现{len(findings)}项风险信号" if findings else "：未发现重大疑虑"),
    }


# ============================================================
# 批量执行
# ============================================================

def run_substantive_procedures(
    df: pd.DataFrame,
    procedures: list[str] | None = None,
    bs_date: str | None = None,
) -> dict:
    """
    批量执行实质性程序。

    Args:
        df: 数据 DataFrame
        procedures: 要执行的程序列表，None 表示全部执行
        bs_date: 资产负债表日

    Returns:
        {
            'procedures': {key: {...}, ...},
            'summary': {...}
        }
    """
    all_procedures = {
        'voucher_inspection': inspect_vouchers,
        'inventory_valuation': test_inventory_valuation,
        'expense_cutoff': lambda d: test_expense_cutoff(d, bs_date=bs_date),
        'cash_bank': audit_cash_bank,
        'receivables_payables': audit_receivables_payables,
        'inventory': audit_inventory,
        'fixed_assets': audit_fixed_assets,
        'revenue_cost': audit_revenue_cost,
        'expenses': audit_expenses,
        'taxes': audit_taxes,
        'subsequent_events': lambda d: audit_subsequent_events(d, bs_date=bs_date),
        'contingencies_going_concern': audit_contingencies_going_concern,
    }

    to_run = procedures if procedures else list(all_procedures.keys())
    results = {}

    for key in to_run:
        if key in all_procedures:
            try:
                results[key] = all_procedures[key](df)
            except Exception as e:
                results[key] = {
                    'rule': key, 'name': key,
                    'suspicious': False, 'risk': 'low',
                    'error': str(e),
                    'findings': [],
                    'description': f'执行异常: {e}',
                }

    # 汇总
    proc_list = list(results.values())
    suspicious = [p for p in proc_list if p.get('suspicious')]
    risks = [p.get('risk', 'low') for p in proc_list]
    high_count = risks.count('high')
    medium_count = risks.count('medium')
    low_count = risks.count('low')

    total_findings = sum(len(p.get('findings', [])) for p in proc_list)

    if high_count >= 3:
        overall_risk = 'high'
    elif high_count >= 1 or medium_count >= 4:
        overall_risk = 'medium'
    else:
        overall_risk = 'low'

    return {
        'procedures': results,
        'summary': {
            'total_procedures': len(proc_list),
            'suspicious_count': len(suspicious),
            'high_risk': high_count,
            'medium_risk': medium_count,
            'low_risk': low_count,
            'overall_risk': overall_risk,
            'total_findings': total_findings,
        },
    }
