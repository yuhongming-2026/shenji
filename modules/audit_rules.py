"""
审计规则引擎 - 7条核心财务审计规则
"""
from __future__ import annotations

import pandas as pd
import numpy as np
from datetime import datetime, timedelta
from collections import Counter


def _detect_columns(df: pd.DataFrame) -> dict:
    """检测关键列"""
    cols = {'amount': None, 'date': None, 'category': None, 'voucher': None}
    for col in df.columns:
        cl = col.lower()
        if not cols['amount'] and any(k in cl for k in [
            '金额', 'amount', '元', 'money', 'value', '总额', '余额', 'balance',
            '账款', '应收', '应付', '收入', '成本', '利润', '资产', '负债', '权益',
            '净值', '现金流', '净利', '毛利', '费用', '支出', '销售', '营业', '税款',
            '税额', '工资', '薪酬', '折旧', '摊销', '存货', '借款', '投资', '融资',
            '汇率', '利率', '单价', '数量', '合计', '总计', '小计', '净额',
        ]):
            cols['amount'] = col
        if not cols['date'] and any(k in cl for k in [
            '日期', 'date', '时间', 'time', '年月日', '年月', '季度', '年度', '期间', 'period',
        ]):
            cols['date'] = col
        if not cols['category'] and any(k in cl for k in [
            '类别', '分类', 'category', 'type', '科目', 'account', '部门', 'dept',
            '摘要', 'description', '公司', '名称', 'name', '客户', '供应商', '项目',
            '产品', '状态', 'status', '说明',
        ]):
            cols['category'] = col
        if not cols['voucher'] and any(k in cl for k in [
            '凭证', 'voucher', '发票', 'invoice', '单据', '编号', '号码', 'no',
            'id', '序号', '代码', 'code', '单号', '流水号', '合同号',
        ]):
            cols['voucher'] = col

    # 兜底：用数值列做金额，用第一列字符串做分类
    if not cols['amount']:
        num_cols = df.select_dtypes(include=[np.number]).columns
        if len(num_cols) > 0:
            cols['amount'] = num_cols[0]
        else:
            # 最后回退：在非数值列中尝试发现数值内容
            for col in df.columns:
                if cols['amount']:
                    break
                try:
                    sample = df[col].dropna()
                    if len(sample) == 0:
                        continue
                    numeric_sample = pd.to_numeric(sample, errors='coerce')
                    if numeric_sample.notna().sum() / len(sample) > 0.7:
                        cols['amount'] = col
                except Exception:
                    continue
    if not cols['category']:
        str_cols = df.select_dtypes(include=['object']).columns
        if len(str_cols) > 1:
            cols['category'] = str_cols[0]
    return cols


# ============================================================
# 规则1：Benford 定律分析
# ============================================================
def rule_benford(df: pd.DataFrame, amount_col: str = None) -> dict:
    """
    本福特定律：自然生成的财务数据，首位数字1-9的概率不是均匀的，
    1约占30%，9约占4.6%。人为数据常违反此分布。
    """
    if not amount_col:
        amount_col = _detect_columns(df)['amount']
    if not amount_col:
        return {'rule': 'benford', 'name': 'Benford定律分析', 'error': '未检测到金额列'}

    amounts = pd.to_numeric(df[amount_col], errors='coerce').dropna()
    amounts = amounts[amounts > 0]  # 只取正数

    if len(amounts) < 50:
        return {'rule': 'benford', 'name': 'Benford定律分析', 'warning': '数据量不足（需≥50条）', 'data_count': len(amounts)}

    # 提取首位数字
    first_digits = amounts.apply(lambda x: int(str(abs(x)).strip('0.').lstrip('0')[:1]) if x > 0 else np.nan)
    first_digits = first_digits.dropna()
    first_digits = first_digits[first_digits.between(1, 9)]

    observed = first_digits.value_counts().reindex(range(1, 10), fill_value=0)
    observed_pct = (observed / observed.sum() * 100).round(2)

    # Benford 期望分布
    benford_expected = {d: round(np.log10(1 + 1 / d) * 100, 2) for d in range(1, 10)}

    # 计算偏差
    deviations = {}
    for d in range(1, 10):
        deviations[d] = round(observed_pct.get(d, 0) - benford_expected[d], 2)

    # 卡方检验简易版：最大偏差 > 10% 则标记可疑
    max_deviation = max(abs(v) for v in deviations.values())
    suspicious = max_deviation > 10

    return {
        'rule': 'benford',
        'name': 'Benford定律分析',
        'suspicious': suspicious,
        'risk': 'high' if max_deviation > 15 else ('medium' if suspicious else 'low'),
        'data_count': len(first_digits),
        'observed': {str(k): v for k, v in observed_pct.to_dict().items()},
        'expected': {str(k): v for k, v in benford_expected.items()},
        'deviations': {str(k): v for k, v in deviations.items()},
        'max_deviation': round(max_deviation, 2),
        'description': '首位数字分布偏离Benford定律' if suspicious else '首位数字分布符合Benford定律',
    }


# ============================================================
# 规则2：重复交易检测
# ============================================================
def rule_duplicates(df: pd.DataFrame, amount_col: str = None) -> dict:
    """检测完全重复及高度相似的交易记录"""
    if not amount_col:
        amount_col = _detect_columns(df)['amount']

    # 完全重复行
    dup_mask = df.duplicated(keep=False)
    full_dups = df[dup_mask].copy()
    full_dup_count = int(dup_mask.sum())

    # 关键列组合重复（金额+日期+分类）
    cols = _detect_columns(df)
    key_cols = [c for c in [cols['amount'], cols['date'], cols['category']] if c]
    key_dup_count = 0
    if len(key_cols) >= 2:
        key_dup_count = int(df.duplicated(subset=key_cols, keep=False).sum())

    risk = 'high' if full_dup_count > 10 else ('medium' if full_dup_count > 3 else 'low')

    return {
        'rule': 'duplicates',
        'name': '重复交易检测',
        'full_duplicates': full_dup_count,
        'key_field_duplicates': key_dup_count,
        'suspicious': full_dup_count > 0,
        'risk': risk,
        'duplicate_groups': int(full_dups.duplicated().sum()) if full_dup_count > 0 else 0,
        'description': f'发现 {full_dup_count} 条完全重复记录，{key_dup_count} 条关键字段重复' if full_dup_count > 0 else '未发现重复记录',
    }


# ============================================================
# 规则3：大额交易检测
# ============================================================
def rule_large_amounts(df: pd.DataFrame, amount_col: str = None) -> dict:
    """基于统计分位数标记异常大额交易"""
    if not amount_col:
        cols = _detect_columns(df)
        amount_col = cols['amount']
    if not amount_col:
        return {'rule': 'large_amounts', 'name': '大额交易检测', 'error': '未检测到金额列'}

    amounts = pd.to_numeric(df[amount_col], errors='coerce')
    valid = amounts.dropna()
    valid_pos = valid[valid > 0]

    if len(valid_pos) < 10:
        return {'rule': 'large_amounts', 'name': '大额交易检测', 'warning': '数据量不足'}

    # 用99分位数和3倍标准差两种方式
    q99 = valid_pos.quantile(0.99)
    std_threshold = valid_pos.mean() + 3 * valid_pos.std()

    large_q99 = (valid > q99).sum()
    large_std = (valid > std_threshold).sum()

    # 取更严格的那个
    threshold = min(q99, std_threshold) if std_threshold > 0 else q99
    large_count = int((valid > threshold).sum())

    suspicious = large_count > 0
    risk = 'high' if large_count > len(df) * 0.05 else ('medium' if large_count > len(df) * 0.01 else 'low')

    return {
        'rule': 'large_amounts',
        'name': '大额交易检测',
        'suspicious': suspicious,
        'risk': risk,
        'threshold_99pct': round(float(q99), 2),
        'threshold_3std': round(float(std_threshold), 2),
        'used_threshold': round(float(threshold), 2),
        'large_transaction_count': int(large_count),
        'largest_amount': round(float(valid.max()), 2),
        'description': f'标记 {int(large_count)} 笔大额交易（阈值: {threshold:,.2f}）' if large_count > 0 else '未发现异常大额交易',
    }


# ============================================================
# 规则4：整数/整round数分析
# ============================================================
def rule_round_numbers(df: pd.DataFrame, amount_col: str = None) -> dict:
    """检测以0或5结尾的金额占比，人为数据常有过多取整"""
    if not amount_col:
        cols = _detect_columns(df)
        amount_col = cols['amount']
    if not amount_col:
        return {'rule': 'round_numbers', 'name': '整数/取整分析', 'error': '未检测到金额列'}

    amounts = pd.to_numeric(df[amount_col], errors='coerce').dropna()
    amounts = amounts[amounts != 0]

    if len(amounts) < 20:
        return {'rule': 'round_numbers', 'name': '整数/取整分析', 'warning': '数据量不足'}

    total = len(amounts)
    round_to_0 = int((amounts % 10 == 0).sum())  # 整十
    round_to_00 = int((amounts % 100 == 0).sum())  # 整百
    round_to_000 = int((amounts % 1000 == 0).sum())  # 整千
    round_to_5 = int((amounts % 10 == 5).sum())  # 以5结尾

    pct_round_0 = round(round_to_0 / total * 100, 2)
    pct_round_5 = round(round_to_5 / total * 100, 2)
    pct_round_any = round((round_to_0 + round_to_5) / total * 100, 2)

    # 自然数据中，末尾为0或5约占20%。超过35%标记可疑
    suspicious = pct_round_any > 35
    risk = 'high' if pct_round_any > 50 else ('medium' if suspicious else 'low')

    return {
        'rule': 'round_numbers',
        'name': '整数/取整分析',
        'suspicious': suspicious,
        'risk': risk,
        'total_count': total,
        'round_to_0': round_to_0,
        'round_to_00': round_to_00,
        'round_to_000': round_to_000,
        'round_to_5': round_to_5,
        'pct_round_0': pct_round_0,
        'pct_round_5': pct_round_5,
        'pct_round_any': pct_round_any,
        'expected_pct': 20.0,
        'description': f'以0或5结尾的金额占 {pct_round_any}%（期望约20%）' + (' — 可疑' if suspicious else ''),
    }


# ============================================================
# 规则5：负数/冲销交易检测
# ============================================================
def rule_negative_amounts(df: pd.DataFrame, amount_col: str = None) -> dict:
    """检测异常负数交易和冲销分录"""
    if not amount_col:
        cols = _detect_columns(df)
        amount_col = cols['amount']
    if not amount_col:
        return {'rule': 'negatives', 'name': '负数/冲销检测', 'error': '未检测到金额列'}

    amounts = pd.to_numeric(df[amount_col], errors='coerce')
    valid = amounts.dropna()

    negative = valid[valid < 0]
    negative_count = len(negative)

    if negative_count == 0:
        return {
            'rule': 'negatives',
            'name': '负数/冲销检测',
            'suspicious': False,
            'risk': 'low',
            'negative_count': 0,
            'negative_total': 0,
            'description': '未发现负数/冲销交易',
        }

    suspicious = negative_count > len(df) * 0.1
    risk = 'medium' if suspicious else 'low'

    return {
        'rule': 'negatives',
        'name': '负数/冲销检测',
        'suspicious': suspicious,
        'risk': risk,
        'negative_count': negative_count,
        'negative_total': round(float(negative.sum()), 2),
        'negative_ratio': round(negative_count / len(valid) * 100, 2),
        'description': f'发现 {negative_count} 笔负数/冲销交易，合计 {negative.sum():,.2f}',
    }


# ============================================================
# 规则6：日期异常检测
# ============================================================
def rule_date_anomalies(df: pd.DataFrame, date_col: str = None) -> dict:
    """检测周末交易、未来日期、日期跨度异常"""
    if not date_col:
        cols = _detect_columns(df)
        date_col = cols['date']
    if not date_col:
        return {'rule': 'date_anomalies', 'name': '日期异常检测', 'error': '未检测到日期列'}

    dates = pd.to_datetime(df[date_col], errors='coerce')
    valid = dates.dropna()

    if len(valid) == 0:
        return {'rule': 'date_anomalies', 'name': '日期异常检测', 'error': '日期列无法解析'}

    # 未来日期
    today = pd.Timestamp.now().normalize()
    future = valid[valid > today + timedelta(days=1)]
    future_count = len(future)

    # 周末交易 (weekday: 5=Sat, 6=Sun)
    weekend = valid[valid.dt.weekday >= 5]
    weekend_count = len(weekend)

    # 月初/月末集中（每月1号、最后一天）
    first_day = valid[valid.dt.day == 1]
    last_day = valid[valid.dt.day == valid.dt.days_in_month]
    month_edge_count = len(first_day) + len(last_day)

    findings = []
    if future_count > 0:
        findings.append(f'{future_count} 条未来日期记录')
    if weekend_count > 0:
        findings.append(f'{weekend_count} 条周末交易')
    if month_edge_count / len(valid) > 0.2:
        findings.append(f'月初/月末交易占比偏高 ({month_edge_count}条)')

    suspicious = len(findings) > 0
    risk = 'high' if future_count > 0 else ('medium' if weekend_count > len(valid) * 0.1 else 'low')

    return {
        'rule': 'date_anomalies',
        'name': '日期异常检测',
        'suspicious': suspicious,
        'risk': risk,
        'total_dates': len(valid),
        'date_range_start': valid.min().strftime('%Y-%m-%d'),
        'date_range_end': valid.max().strftime('%Y-%m-%d'),
        'future_dates': int(future_count),
        'weekend_transactions': int(weekend_count),
        'month_edge_transactions': int(month_edge_count),
        'findings': findings,
        'description': '；'.join(findings) if findings else '未发现日期异常',
    }


# ============================================================
# 规则7：凭证号连续性检查
# ============================================================
def rule_voucher_sequence(df: pd.DataFrame, voucher_col: str = None) -> dict:
    """检测凭证号/发票号的断号和重号"""
    if not voucher_col:
        cols = _detect_columns(df)
        voucher_col = cols['voucher']
    if not voucher_col:
        return {'rule': 'voucher_sequence', 'name': '凭证号连续性检查', 'error': '未检测到凭证号列'}

    # 尝试提取数字
    vouchers = df[voucher_col].dropna().astype(str)
    # 提取纯数字部分
    numeric_vouchers = pd.to_numeric(vouchers, errors='coerce')
    valid = numeric_vouchers.dropna().sort_values()

    if len(valid) < 2:
        # 尝试从字符串中提取数字
        extracted = vouchers.str.extract(r'(\d+)', expand=False)
        valid = pd.to_numeric(extracted, errors='coerce').dropna().sort_values()
        if len(valid) < 2:
            return {'rule': 'voucher_sequence', 'name': '凭证号连续性检查', 'warning': '凭证号无法识别为数字序列'}

    valid = valid.astype(int)
    min_v, max_v = int(valid.min()), int(valid.max())

    # 重复号
    dup_count = int(valid.duplicated().sum())
    dup_values = valid[valid.duplicated()].unique().tolist()[:10]

    # 断号
    full_range = set(range(min_v, max_v + 1))
    actual = set(valid.values)
    gaps = sorted(full_range - actual)[:20]  # 最多显示20个断号
    gap_count = len(full_range - actual)

    suspicious = gap_count > 0 or dup_count > 0
    risk = 'high' if (gap_count > len(df) * 0.05 or dup_count > 5) else ('medium' if suspicious else 'low')

    return {
        'rule': 'voucher_sequence',
        'name': '凭证号连续性检查',
        'suspicious': suspicious,
        'risk': risk,
        'min_voucher': min_v,
        'max_voucher': max_v,
        'total_numbers': len(valid.unique()),
        'expected_count': max_v - min_v + 1,
        'gap_count': gap_count,
        'gap_examples': gaps,
        'duplicate_count': dup_count,
        'duplicate_examples': [int(x) for x in dup_values],
        'description': f'发现 {gap_count} 个断号，{dup_count} 个重号' if suspicious else '凭证号连续完整',
    }


# ============================================================
# 批量执行所有规则
# ============================================================
def run_all_rules(df: pd.DataFrame) -> list[dict]:
    """执行全部7条审计规则，返回结果列表"""
    rules = [
        rule_benford,
        rule_duplicates,
        rule_large_amounts,
        rule_round_numbers,
        rule_negative_amounts,
        rule_date_anomalies,
        rule_voucher_sequence,
    ]
    results = []
    for rule_fn in rules:
        try:
            result = rule_fn(df)
            results.append(result)
        except Exception as e:
            results.append({
                'rule': rule_fn.__name__.replace('rule_', ''),
                'name': rule_fn.__name__.replace('rule_', '').replace('_', ' ').title(),
                'error': str(e),
                'suspicious': False,
                'risk': 'unknown',
            })
    return results


def get_rule_summary(results: list[dict]) -> dict:
    """汇总所有规则结果"""
    total = len(results)
    suspicious = sum(1 for r in results if r.get('suspicious'))
    high_risk = sum(1 for r in results if r.get('risk') == 'high')
    medium_risk = sum(1 for r in results if r.get('risk') == 'medium')
    low_risk = sum(1 for r in results if r.get('risk') == 'low')

    return {
        'total_rules': total,
        'suspicious_count': suspicious,
        'high_risk': high_risk,
        'medium_risk': medium_risk,
        'low_risk': low_risk,
        'overall_risk': 'high' if high_risk > 0 else ('medium' if medium_risk > 2 else 'low'),
    }
