"""
风险评估阶段 - 财务指标异常分析、交易流水异常检测、收入舞弊风险识别
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime

from modules.audit_data_helpers import (
    detect_financial_columns,
    calculate_financial_ratios,
    cluster_outliers,
    time_series_decompose,
    analyze_concentration,
)

# ============================================================
# 内部辅助
# ============================================================

def _detect_columns(df: pd.DataFrame) -> dict[str, str | None]:
    """从 DataFrame 中探测关键列名"""
    cols = detect_financial_columns(df)
    return {
        'amount': cols['amount'][0] if cols['amount'] else None,
        'date': cols['date'][0] if cols['date'] else None,
        'category': cols['category'][0] if cols['category'] else None,
        'customer': cols['customer'][0] if cols['customer'] else None,
        'counterparty': cols['counterparty'][0] if cols['counterparty'] else None,
        'voucher': cols['voucher'][0] if cols['voucher'] else None,
        'revenue': cols['revenue'][0] if cols['revenue'] else None,
        'cost': cols['cost'][0] if cols['cost'] else None,
        'expense': cols['expense'][0] if cols['expense'] else None,
    }


def _safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors='coerce')


# ============================================================
# 1. 财务指标异常分析
# ============================================================

def analyze_financial_ratios(
    df: pd.DataFrame,
    benchmarks: dict | None = None,
) -> dict:
    """
    自动计算流动比率、毛利率、资产负债率等财务指标，
    与行业基准对比，标记异常波动。

    Returns:
        {
            'rule': 'financial_ratios',
            'name': '财务指标异常分析',
            'suspicious': bool,
            'risk': 'high'|'medium'|'low',
            'ratios': [...],
            'anomalies': [...],
            'description': str,
        }
    """
    ratio_result = calculate_financial_ratios(df, benchmarks=benchmarks)
    anomalies = ratio_result.get('anomalies', [])
    risk = ratio_result.get('risk', 'low')

    return {
        'rule': 'financial_ratios',
        'name': '财务指标异常分析',
        'suspicious': len(anomalies) > 0,
        'risk': risk,
        'ratios': ratio_result.get('ratios', []),
        'anomalies': anomalies,
        'summary': ratio_result.get('summary', {}),
        'description': ratio_result.get('description', '无法计算财务比率'),
    }


# ============================================================
# 2. 交易流水异常检测
# ============================================================

def detect_flow_anomalies(
    df: pd.DataFrame,
    amount_col: str | None = None,
    date_col: str | None = None,
    counterparty_col: str | None = None,
    n_clusters: int = 3,
    std_threshold: float = 2.0,
) -> dict:
    """
    通过 K-Means 聚类和离群点分析，自动识别：
    - 大额异常交易
    - 异常时间交易
    - 异常对手方交易

    Returns:
        {
            'rule': 'flow_anomalies',
            'name': '交易流水异常检测',
            'suspicious': bool,
            'risk': 'high'|'medium'|'low',
            'outliers': [...],
            'clusters': {...},
            'description': str,
        }
    """
    cols = _detect_columns(df)
    amount_col = amount_col or cols['amount']
    date_col = date_col or cols['date']
    counterparty_col = counterparty_col or cols['counterparty']

    if amount_col is None:
        return {
            'rule': 'flow_anomalies', 'name': '交易流水异常检测',
            'suspicious': False, 'risk': 'low',
            'outliers': [], 'clusters': {},
            'description': '未检测到金额列，无法执行交易流水异常检测',
        }

    # 准备聚类特征
    amounts = _safe_numeric(df[amount_col]).fillna(0).values
    features = np.column_stack([amounts])

    # 如果有日期列，添加时间特征
    if date_col:
        try:
            dates = pd.to_datetime(df[date_col], errors='coerce')
            day_of_week = dates.dt.dayofweek.fillna(0).values.astype(float)
            day_of_month = dates.dt.day.fillna(1).values.astype(float)
            # 归一化
            day_of_week = day_of_week / 6.0
            day_of_month = day_of_month / 31.0
            features = np.column_stack([amounts, day_of_week, day_of_month])
        except Exception:
            pass

    # 标准化金额（log 变换减少偏度）
    amounts_abs = np.abs(amounts)
    amounts_abs[amounts_abs == 0] = 1.0
    log_amounts = np.log1p(amounts_abs)
    log_amounts = (log_amounts - log_amounts.mean()) / (log_amounts.std() or 1.0)
    features[:, 0] = log_amounts

    # K-Means 聚类
    cluster_result = cluster_outliers(features, n_clusters=n_clusters, std_threshold=std_threshold)

    outlier_indices = cluster_result.get('outlier_indices', [])
    total = len(df)

    # 构建离群点详情
    outliers = []
    for idx in outlier_indices[:100]:  # 最多返回100条
        if idx < total:
            row = df.iloc[idx]
            outliers.append({
                'index': int(idx),
                'amount': float(row[amount_col]) if amount_col in df.columns else None,
                'date': str(row[date_col]) if date_col and date_col in df.columns else None,
                'counterparty': str(row[counterparty_col]) if counterparty_col and counterparty_col in df.columns else None,
                'distance': round(cluster_result.get('distances', [0])[idx], 4) if idx < len(cluster_result.get('distances', [])) else 0,
                'cluster': int(cluster_result.get('labels', [0])[idx]) if idx < len(cluster_result.get('labels', [])) else -1,
            })

    outlier_pct = len(outlier_indices) / max(total, 1) * 100
    risk = 'high' if outlier_pct > 10 else ('medium' if outlier_pct > 3 else 'low')

    return {
        'rule': 'flow_anomalies',
        'name': '交易流水异常检测',
        'suspicious': len(outliers) > 0,
        'risk': risk,
        'outliers': outliers,
        'outlier_count': len(outlier_indices),
        'outlier_pct': round(outlier_pct, 2),
        'total_records': total,
        'n_clusters': n_clusters,
        'clusters': {
            'labels': cluster_result.get('labels', []),
            'centroids': cluster_result.get('centroids', []),
        },
        'description': f"共{total}条交易记录，聚类发现{len(outlier_indices)}条异常交易（{outlier_pct:.1f}%）",
    }


# ============================================================
# 3. 收入舞弊风险识别
# ============================================================

def analyze_revenue_fraud_risk(
    df: pd.DataFrame,
    amount_col: str | None = None,
    date_col: str | None = None,
    customer_col: str | None = None,
    counterparty_col: str | None = None,
) -> dict:
    """
    收入舞弊风险识别：
    - 月度/季度收入分布分析
    - 客户集中度分析（HHI）
    - 关联交易占比检查

    Returns:
        {
            'rule': 'revenue_fraud',
            'name': '收入舞弊风险识别',
            'suspicious': bool,
            'risk': 'high'|'medium'|'low',
            'monthly_revenue': [...],
            'concentration': {...},
            'related_party_ratio': float,
            'findings': [...],
            'description': str,
        }
    """
    cols = _detect_columns(df)
    amount_col = amount_col or cols['amount']
    date_col = date_col or cols['date']
    customer_col = customer_col or cols['customer']
    counterparty_col = counterparty_col or cols['counterparty']

    if amount_col is None:
        return {
            'rule': 'revenue_fraud', 'name': '收入舞弊风险识别',
            'suspicious': False, 'risk': 'low',
            'monthly_revenue': [], 'concentration': {},
            'related_party_ratio': 0, 'findings': [],
            'description': '未检测到金额列，无法执行收入舞弊分析',
        }

    amounts = _safe_numeric(df[amount_col]).fillna(0)
    findings = []

    # --- 月度/季度收入分布 ---
    monthly_revenue = []
    seasonal_anomaly = None

    if date_col:
        try:
            dates = pd.to_datetime(df[date_col], errors='coerce')
            valid_mask = dates.notna()
            valid_dates = dates[valid_mask]
            valid_amounts = amounts[valid_mask]

            # 月度汇总
            monthly = valid_amounts.groupby(valid_dates.dt.to_period('M')).sum().sort_index()
            monthly_revenue = [
                {'month': str(k), 'total': round(float(v), 2)}
                for k, v in monthly.items()
            ]

            # 季度汇总
            if len(monthly) >= 4:
                quarterly = valid_amounts.groupby(valid_dates.dt.to_period('Q')).sum()
                q_values = quarterly.values
                q_mean = q_values.mean()
                q_std = q_values.std() or 1.0
                q_cv = q_std / q_mean if q_mean > 0 else 0

                if q_cv > 0.5:
                    findings.append({
                        'type': '季节性异常',
                        'risk': 'high',
                        'description': f'季度收入波动系数为{q_cv:.2f}（变异系数>0.5），存在显著的季节性/周期性异常，需关注是否存在跨期调节收入',
                        'detail': {str(k): round(float(v), 2) for k, v in quarterly.items()},
                    })

            # 月度趋势分解
            if len(monthly) >= 6:
                decomp = time_series_decompose(monthly.values)
                anomaly_months = decomp.get('anomaly_indices', [])
                if anomaly_months:
                    anomaly_details = []
                    for idx in anomaly_months:
                        if idx < len(monthly):
                            anomaly_details.append({
                                'month': str(monthly.index[idx]),
                                'value': round(float(monthly.values[idx]), 2),
                            })
                    findings.append({
                        'type': '月度异常波动',
                        'risk': 'high' if len(anomaly_months) >= 3 else 'medium',
                        'description': f'发现{len(anomaly_months)}个月度收入异常波动（偏离趋势±2.5σ），可能是收入操纵信号',
                        'detail': anomaly_details,
                    })
                    seasonal_anomaly = decomp
        except Exception as e:
            findings.append({
                'type': '日期解析错误',
                'risk': 'low',
                'description': f'日期列解析异常: {str(e)}',
            })

    # --- 客户集中度分析 ---
    concentration = {}
    if customer_col:
        try:
            customer_amounts = amounts.groupby(df[customer_col].fillna('未知')).sum()
            customer_vals = customer_amounts.values
            customer_names = customer_amounts.index.tolist()
            concentration = analyze_concentration(customer_vals, customer_names)

            if concentration.get('concentration') == 'high':
                findings.append({
                    'type': '客户集中度风险',
                    'risk': 'high',
                    'description': f"客户集中度过高（HHI={concentration['hhi']:.0f}），前{len(concentration.get('top_n',[]))}大客户占比{concentration.get('top_n_pct',0)}%，存在客户依赖风险",
                    'detail': concentration.get('top_n', []),
                })
            elif concentration.get('concentration') == 'moderate':
                findings.append({
                    'type': '客户集中度风险',
                    'risk': 'medium',
                    'description': f"客户集中度中等（HHI={concentration['hhi']:.0f}），前{len(concentration.get('top_n',[]))}大客户占比{concentration.get('top_n_pct',0)}%",
                    'detail': concentration.get('top_n', []),
                })
        except Exception:
            pass

    # --- 关联交易占比（如果有对手方列，检查频繁交易） ---
    related_party_ratio = 0.0
    if counterparty_col:
        try:
            party_counts = df[counterparty_col].fillna('未知').value_counts()
            # 高频交易对手方（超过总交易量20%的视为潜在关联方）
            total_txns = len(df)
            frequent_parties = party_counts[party_counts > total_txns * 0.1]
            if len(frequent_parties) > 0:
                related_amount = 0.0
                for party in frequent_parties.index:
                    related_amount += amounts[df[counterparty_col] == party].sum()
                related_party_ratio = float(related_amount / max(amounts.sum(), 1))

                if related_party_ratio > 0.3:
                    findings.append({
                        'type': '关联交易风险',
                        'risk': 'high',
                        'description': f'高频交易对手方（>10%交易量）涉及金额占比{related_party_ratio*100:.1f}%，可能存在未披露关联交易',
                        'detail': {party: int(count) for party, count in frequent_parties.items()},
                    })
        except Exception:
            pass

    # --- 综合评估 ---
    risk = 'low'
    high_count = sum(1 for f in findings if f.get('risk') == 'high')
    med_count = sum(1 for f in findings if f.get('risk') == 'medium')
    if high_count >= 2:
        risk = 'high'
    elif high_count >= 1 or med_count >= 2:
        risk = 'medium'

    return {
        'rule': 'revenue_fraud',
        'name': '收入舞弊风险识别',
        'suspicious': len(findings) > 0,
        'risk': risk,
        'monthly_revenue': monthly_revenue,
        'concentration': concentration,
        'related_party_ratio': round(related_party_ratio, 4),
        'seasonal_decomposition': seasonal_anomaly,
        'findings': findings,
        'findings_count': len(findings),
        'description': f"发现{len(findings)}项收入舞弊风险信号" + (
            f"，{high_count}项高风险" if high_count > 0 else ""
        ) if findings else "未发现明显收入舞弊风险信号",
    }


# ============================================================
# 批量执行
# ============================================================

def run_risk_assessment(df: pd.DataFrame) -> dict:
    """
    批量执行所有风险评估函数。

    Returns:
        {
            'financial_ratios': {...},
            'flow_anomalies': {...},
            'revenue_fraud': {...},
            'summary': {
                'total_procedures': int,
                'suspicious_count': int,
                'high_risk': int,
                'medium_risk': int,
                'low_risk': int,
                'overall_risk': str,
                'total_findings': int,
            }
        }
    """
    results = {}

    # 1. 财务指标分析
    try:
        results['financial_ratios'] = analyze_financial_ratios(df)
    except Exception as e:
        results['financial_ratios'] = {
            'rule': 'financial_ratios', 'name': '财务指标异常分析',
            'suspicious': False, 'risk': 'low', 'error': str(e),
            'ratios': [], 'anomalies': [], 'description': f'执行异常: {e}',
        }

    # 2. 交易流水异常检测
    try:
        results['flow_anomalies'] = detect_flow_anomalies(df)
    except Exception as e:
        results['flow_anomalies'] = {
            'rule': 'flow_anomalies', 'name': '交易流水异常检测',
            'suspicious': False, 'risk': 'low', 'error': str(e),
            'outliers': [], 'description': f'执行异常: {e}',
        }

    # 3. 收入舞弊风险识别
    try:
        results['revenue_fraud'] = analyze_revenue_fraud_risk(df)
    except Exception as e:
        results['revenue_fraud'] = {
            'rule': 'revenue_fraud', 'name': '收入舞弊风险识别',
            'suspicious': False, 'risk': 'low', 'error': str(e),
            'findings': [], 'description': f'执行异常: {e}',
        }

    # 汇总
    procedures = list(results.values())
    suspicious = [p for p in procedures if p.get('suspicious')]
    risks = [p.get('risk', 'low') for p in procedures]
    high_count = risks.count('high')
    medium_count = risks.count('medium')
    low_count = risks.count('low')

    # 统计总发现数
    total_findings = 0
    for p in procedures:
        if 'outlier_count' in p:
            total_findings += p['outlier_count']
        if 'findings_count' in p:
            total_findings += p['findings_count']
        if 'anomalies' in p:
            total_findings += len(p.get('anomalies', []))

    if high_count > 0:
        overall_risk = 'high'
    elif medium_count >= 2:
        overall_risk = 'medium'
    else:
        overall_risk = 'low'

    return {
        'procedures': results,
        'summary': {
            'total_procedures': 3,
            'suspicious_count': len(suspicious),
            'high_risk': high_count,
            'medium_risk': medium_count,
            'low_risk': low_count,
            'overall_risk': overall_risk,
            'total_findings': total_findings,
        },
    }
