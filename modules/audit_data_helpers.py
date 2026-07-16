"""
审计数据辅助工具 - 增强列识别、财务比率计算、聚类异常检测、时间序列分解
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from typing import Any


# ============================================================
# 增强版列识别
# ============================================================

COLUMN_KEYWORDS = {
    'asset': ['asset', 'assets'],
    'liability': ['liability'],
    'equity': ['equity'],
    'revenue': ['revenue', 'sales', 'income'],
    'cost': ['cost'],
    'expense': ['expense'],
    'profit': ['profit'],
    'tax': ['tax'],
    'amount': ['amount', 'sum', 'total', 'value', 'price'],
    'date': ['date', 'time'],
    'voucher': ['voucher', 'invoice', 'no', 'id', 'number'],
    'category': ['category', 'type', 'class', 'account'],
    'customer': ['customer', 'client', 'buyer'],
    'supplier': ['supplier', 'vendor', 'seller'],
    'counterparty': ['counterparty', 'party'],
    'inventory': ['inventory', 'stock'],
    'fixed_asset': ['fixed_asset', 'fixed asset'],
    'receivable': ['receivable', 'AR'],
    'payable': ['payable', 'AP'],
    'bank': ['bank', 'cash'],
    'department': ['department', 'dept'],
    'approver': ['approver', 'approval'],
}

CHINESE_KEYWORDS = {
    'asset': ['资产', '固定资产', '流动资产', '无形资产', '总资产'],
    'liability': ['负债', '流动负债', '长期负债', '应付', '总负债'],
    'equity': ['所有者权益', '权益', '净资产', '资本'],
    'revenue': ['收入', '营收', '主营业务收入', '营业收入', '销售'],
    'cost': ['成本', '主营业务成本', '营业成本', '销售成本'],
    'expense': ['费用', '管理费用', '销售费用', '财务费用', '支出'],
    'profit': ['利润', '净利润', '毛利润', '营业利润'],
    'tax': ['税金', '税费', '所得税', '增值税'],
    'amount': ['金额', '总计', '合计', '总额'],
    'date': ['日期', '时间'],
    'voucher': ['凭证', '发票', '单据', '编号', '单号'],
    'category': ['分类', '类别', '类型', '科目'],
    'customer': ['客户', '购货方', '买方'],
    'supplier': ['供应商', '销货方', '卖方'],
    'counterparty': ['对手方', '交易对手', '对方单位', '往来'],
    'inventory': ['存货', '库存', '原材料', '产成品'],
    'fixed_asset': ['固定资产', '设备', '房屋', '机器'],
    'receivable': ['应收', '应收账款', '其他应收款'],
    'payable': ['应付', '应付账款', '其他应付款'],
    'bank': ['银行', '存款', '现金', '货币资金'],
    'department': ['部门', '科室', '机构'],
    'approver': ['审批', '审核', '批准', '复核'],
}


def detect_financial_columns(df: pd.DataFrame) -> dict[str, list[str]]:
    """
    增强版列识别：检测财务报表相关的列类型。
    Returns dict with keys for each column type.
    """
    result: dict[str, list[str]] = {k: [] for k in COLUMN_KEYWORDS}
    result['numeric'] = []
    result['string'] = []

    for col in df.columns:
        col_lower = str(col).lower().strip()
        matched = False
        for key in COLUMN_KEYWORDS:
            en_keywords = COLUMN_KEYWORDS[key]
            zh_keywords = CHINESE_KEYWORDS.get(key, [])
            all_kw = en_keywords + zh_keywords
            if any(kw in col_lower for kw in all_kw):
                result[key].append(col)
                matched = True
        if not matched:
            if pd.api.types.is_numeric_dtype(df[col]):
                result['numeric'].append(col)
            else:
                result['string'].append(col)

    if not result['amount'] and result['numeric']:
        result['amount'] = [result['numeric'][0]]

    return result


# ============================================================
# 财务比率计算引擎
# ============================================================

INDUSTRY_BENCHMARKS = {
    'current_ratio': {'low': 1.0, 'high': 3.0, 'optimal': 2.0, 'name': '流动比率'},
    'quick_ratio': {'low': 0.5, 'high': 2.0, 'optimal': 1.0, 'name': '速动比率'},
    'debt_ratio': {'low': 0.2, 'high': 0.7, 'optimal': 0.4, 'name': '资产负债率'},
    'gross_margin': {'low': 0.1, 'high': 0.6, 'optimal': 0.3, 'name': '毛利率'},
    'net_margin': {'low': 0.02, 'high': 0.25, 'optimal': 0.1, 'name': '净利率'},
    'roe': {'low': 0.03, 'high': 0.25, 'optimal': 0.12, 'name': '净资产收益率'},
    'roa': {'low': 0.01, 'high': 0.15, 'optimal': 0.06, 'name': '总资产收益率'},
    'asset_turnover': {'low': 0.3, 'high': 2.0, 'optimal': 0.8, 'name': '资产周转率'},
    'inventory_turnover': {'low': 2, 'high': 12, 'optimal': 6, 'name': '存货周转率'},
    'receivable_turnover': {'low': 3, 'high': 15, 'optimal': 8, 'name': '应收账款周转率'},
    'debt_to_equity': {'low': 0.3, 'high': 2.5, 'optimal': 1.0, 'name': '产权比率'},
    'interest_coverage': {'low': 1.5, 'high': 10, 'optimal': 4, 'name': '利息保障倍数'},
}


def calculate_financial_ratios(
    df: pd.DataFrame,
    ratio_names: list[str] | None = None,
    benchmarks: dict | None = None,
) -> dict:
    """
    从 DataFrame 计算财务比率，并与行业基准对比标记异常。
    """
    benchmarks = benchmarks or INDUSTRY_BENCHMARKS
    columns = detect_financial_columns(df)

    amount_cols = columns.get('amount', [])
    if not amount_cols:
        amount_cols = columns.get('numeric', [])

    numeric_df = pd.DataFrame()
    if amount_cols:
        numeric_df = df[amount_cols].apply(pd.to_numeric, errors='coerce')

    ratios = []
    anomalies = []

    def _sum_keyword_cols(keyword: str) -> float:
        cols = columns.get(keyword, [])
        if not cols:
            return 0.0
        vals = pd.to_numeric(df[cols].values.flatten(), errors='coerce')
        return float(vals.dropna().sum())

    revenue = _sum_keyword_cols('revenue')
    if revenue == 0 and not numeric_df.empty:
        revenue = float(numeric_df.iloc[:, 0].sum())

    cost_val = _sum_keyword_cols('cost')
    expense_val = _sum_keyword_cols('expense')
    profit_val = _sum_keyword_cols('profit')
    asset_val = _sum_keyword_cols('asset')
    liability_val = _sum_keyword_cols('liability')
    equity_val = _sum_keyword_cols('equity')

    # 毛利率
    if revenue > 0 and cost_val > 0:
        gm = round((revenue - cost_val) / revenue, 4)
        ratios.append({'name': '毛利率', 'key': 'gross_margin', 'value': gm})
        if gm < benchmarks['gross_margin']['low']:
            anomalies.append({'ratio': 'gross_margin', 'name': '毛利率', 'value': gm,
                'risk': 'high', 'direction': 'below',
                'description': '毛利率为%.2f，低于行业下限%.0f%%，盈利能力不足' % (gm, benchmarks['gross_margin']['low']*100)})

    # 净利率
    if revenue > 0 and profit_val > 0:
        nm = round(profit_val / revenue, 4)
        ratios.append({'name': '净利率', 'key': 'net_margin', 'value': nm})
        if nm < benchmarks['net_margin']['low']:
            anomalies.append({'ratio': 'net_margin', 'name': '净利率', 'value': nm,
                'risk': 'high', 'direction': 'below',
                'description': '净利率为%.2f%%，显著偏低' % (nm*100)})

    # 资产负债率
    if asset_val > 0 and liability_val > 0:
        dr = round(liability_val / asset_val, 4)
        ratios.append({'name': '资产负债率', 'key': 'debt_ratio', 'value': dr})
        if dr > benchmarks['debt_ratio']['high']:
            anomalies.append({'ratio': 'debt_ratio', 'name': '资产负债率', 'value': dr,
                'risk': 'high', 'direction': 'above',
                'description': '资产负债率为%.1f%%，超过行业上限%.0f%%，偿债风险高' % (dr*100, benchmarks['debt_ratio']['high']*100)})

    # 流动比率
    if asset_val > 0 and liability_val > 0:
        cr = round(asset_val / liability_val, 4) if liability_val > 0 else 0
        ratios.append({'name': '流动比率', 'key': 'current_ratio', 'value': cr})
        if cr < benchmarks['current_ratio']['low']:
            anomalies.append({'ratio': 'current_ratio', 'name': '流动比率', 'value': cr,
                'risk': 'high', 'direction': 'below',
                'description': '流动比率为%.2f，低于行业下限%.0f，流动性风险' % (cr, benchmarks['current_ratio']['low'])})

    # ROE
    if profit_val > 0 and equity_val > 0:
        roe = round(profit_val / equity_val, 4)
        ratios.append({'name': '净资产收益率(ROE)', 'key': 'roe', 'value': roe})
        if roe < benchmarks['roe']['low']:
            anomalies.append({'ratio': 'roe', 'name': 'ROE', 'value': roe,
                'risk': 'medium', 'direction': 'below',
                'description': 'ROE为%.2f%%，低于行业下限%.0f%%' % (roe*100, benchmarks['roe']['low']*100)})

    # ROA
    if profit_val > 0 and asset_val > 0:
        roa = round(profit_val / asset_val, 4)
        ratios.append({'name': '总资产收益率(ROA)', 'key': 'roa', 'value': roa})

    # 产权比率
    if liability_val > 0 and equity_val > 0:
        de = round(liability_val / equity_val, 4)
        ratios.append({'name': '产权比率', 'key': 'debt_to_equity', 'value': de})
        if de > benchmarks['debt_to_equity']['high']:
            anomalies.append({'ratio': 'debt_to_equity', 'name': '产权比率', 'value': de,
                'risk': 'medium', 'direction': 'above',
                'description': '产权比率为%.2f，财务杠杆偏高' % de})

    # 汇总
    risk = 'low'
    high_count = sum(1 for a in anomalies if a['risk'] == 'high')
    if high_count > 0:
        risk = 'high'
    elif len(anomalies) >= 2:
        risk = 'medium'

    desc_parts = ['共计算%d项财务比率' % len(ratios)]
    if anomalies:
        desc_parts.append('发现%d项异常' % len(anomalies))
        if high_count > 0:
            desc_parts.append('%d项高风险' % high_count)

    return {
        'ratios': ratios,
        'anomalies': anomalies,
        'summary': {
            'total_ratios': len(ratios),
            'total_anomalies': len(anomalies),
            'high_risk_count': high_count,
            'medium_risk_count': sum(1 for a in anomalies if a['risk'] == 'medium'),
        },
        'risk': risk,
        'description': '，'.join(desc_parts),
    }


# ============================================================
# 聚类离群检测
# ============================================================

def cluster_outliers(
    data: np.ndarray,
    n_clusters: int = 3,
    std_threshold: float = 2.0,
) -> dict:
    """
    基于 K-Means 聚类的离群点检测。
    """
    try:
        from scipy.cluster.vq import kmeans2
    except ImportError:
        return {
            'labels': [], 'centroids': [], 'outlier_indices': [],
            'outlier_count': 0, 'distances': [], 'error': 'scipy not available',
        }

    if len(data) < n_clusters * 3:
        return {
            'labels': [], 'centroids': [], 'outlier_indices': [],
            'outlier_count': 0, 'distances': [],
            'error': 'data too small (need %d, got %d)' % (n_clusters * 3, len(data)),
        }

    data_clean = data.copy()
    if data_clean.ndim == 1:
        data_clean = data_clean.reshape(-1, 1)

    mean = data_clean.mean(axis=0)
    std = data_clean.std(axis=0)
    std[std == 0] = 1.0
    data_norm = (data_clean - mean) / std

    try:
        centroids, labels = kmeans2(data_norm.astype(np.float64), n_clusters, minit='points', missing='warn')
    except Exception:
        try:
            centroids, labels = kmeans2(data_norm.astype(np.float64), n_clusters, minit='random')
        except Exception as e:
            return {
                'labels': [], 'centroids': [], 'outlier_indices': [],
                'outlier_count': 0, 'distances': [], 'error': 'cluster failed: ' + str(e),
            }

    distances = np.zeros(len(data_norm))
    for i in range(len(data_norm)):
        distances[i] = np.sqrt(np.sum((data_norm[i] - centroids[labels[i]]) ** 2))

    outlier_indices = []
    for c in range(n_clusters):
        cluster_mask = labels == c
        cluster_distances = distances[cluster_mask]
        if len(cluster_distances) < 3:
            continue
        c_mean = cluster_distances.mean()
        c_std = cluster_distances.std() or 1.0
        cluster_outliers = np.where(cluster_mask)[0][cluster_distances > c_mean + std_threshold * c_std]
        outlier_indices.extend(cluster_outliers.tolist())

    outlier_indices = sorted(set(outlier_indices))

    return {
        'labels': labels.tolist(),
        'centroids': centroids.tolist(),
        'outlier_indices': outlier_indices,
        'outlier_count': len(outlier_indices),
        'distances': distances.tolist(),
        'n_clusters': n_clusters,
    }


# ============================================================
# 时间序列分解
# ============================================================

def time_series_decompose(series: np.ndarray) -> dict:
    """
    简易时间序列分解：趋势 + 季节 + 残差。
    """
    series = np.asarray(series, dtype=np.float64)
    n = len(series)

    result = {
        'trend': [], 'seasonal': [], 'residual': [],
        'trend_direction': 'flat', 'volatility': 0.0, 'anomaly_indices': [],
    }

    if n < 4:
        return result

    window = min(7, max(3, n // 3))
    if window % 2 == 0:
        window += 1
    half = window // 2

    trend = np.full(n, np.nan)
    for i in range(half, n - half):
        trend[i] = np.mean(series[i - half:i + half + 1])
    trend[:half] = trend[half]
    trend[-half:] = trend[-half - 1]

    detrended = series - trend

    seasonal = np.zeros(n)
    period = min(12, max(3, n // 3))
    for i in range(period):
        indices = list(range(i, n, period))
        if indices:
            seasonal[indices] = np.mean(detrended[indices])

    residual = detrended - seasonal

    if n >= 6:
        mid = n // 2
        first_half = np.nanmean(trend[:mid])
        second_half = np.nanmean(trend[mid:])
        pct_change = (second_half - first_half) / (abs(first_half) or 1)
        if pct_change > 0.05:
            result['trend_direction'] = 'up'
        elif pct_change < -0.05:
            result['trend_direction'] = 'down'

    result['volatility'] = float(np.nanstd(residual) / (np.nanmean(np.abs(series)) or 1))

    res_std = np.nanstd(residual) or 1.0
    result['anomaly_indices'] = np.where(np.abs(residual) > 2.5 * res_std)[0].tolist()

    result['trend'] = np.nan_to_num(trend).tolist()
    result['seasonal'] = seasonal.tolist()
    result['residual'] = np.nan_to_num(residual).tolist()

    return result


# ============================================================
# 客户集中度分析
# ============================================================

def analyze_concentration(values: np.ndarray, labels: list[str] | None = None, top_n: int = 10) -> dict:
    """
    Herfindahl-Hirschman Index (HHI) 集中度分析。
    """
    values = np.asarray(values, dtype=np.float64)
    total = values.sum()
    if total == 0:
        return {'hhi': 0, 'concentration': 'low', 'top_n': [], 'top_n_pct': 0}

    shares = values / total
    hhi = float(np.sum(shares ** 2) * 10000)

    if hhi > 2500:
        concentration = 'high'
    elif hhi > 1500:
        concentration = 'moderate'
    else:
        concentration = 'low'

    sorted_idx = np.argsort(values)[::-1]
    top_indices = sorted_idx[:min(top_n, len(values))]
    top_pct = float(values[top_indices].sum() / total)

    return {
        'hhi': hhi,
        'concentration': concentration,
        'top_n': [
            {'index': int(i), 'label': labels[i] if labels else str(i),
             'value': float(values[i]), 'pct': round(float(shares[i]) * 100, 2)}
            for i in top_indices
        ],
        'top_n_pct': round(top_pct * 100, 2),
    }
