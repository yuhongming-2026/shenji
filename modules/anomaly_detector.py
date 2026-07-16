"""
统计异常检测器 - Z-Score 和 IQR 离群值检测。
"""
from __future__ import annotations

import pandas as pd
import numpy as np


def _zscore(series: np.ndarray) -> np.ndarray:
    """计算 Z-Score：(x - mean) / std"""
    mean = np.mean(series)
    std = np.std(series)
    if std == 0:
        return np.zeros(len(series))
    return (series - mean) / std


def detect_by_zscore(df: pd.DataFrame, amount_col: str = None, threshold: float = 3.0) -> dict:
    """
    Z-Score 异常检测
    Z-score = (x - mean) / std
    |Z| > threshold 视为异常
    """
    if amount_col is None:
        num_cols = df.select_dtypes(include=[np.number]).columns
        if len(num_cols) == 0:
            return {'method': 'zscore', 'error': '无数值列'}
        amount_col = num_cols[0]

    amounts = pd.to_numeric(df[amount_col], errors='coerce')
    valid = amounts.dropna()
    valid_nonzero = valid[valid != 0]

    if len(valid_nonzero) < 10:
        return {'method': 'zscore', 'error': '数据量不足（需要≥10条非零记录）'}

    z_scores = np.abs(_zscore(valid_nonzero))
    anomalies = valid_nonzero[z_scores > threshold]
    anomaly_indices = anomalies.index.tolist()

    return {
        'method': 'zscore',
        'name': 'Z-Score异常检测',
        'column': amount_col,
        'threshold': threshold,
        'total_records': len(valid_nonzero),
        'anomaly_count': len(anomalies),
        'anomaly_pct': round(len(anomalies) / len(valid_nonzero) * 100, 2),
        'mean': round(float(valid_nonzero.mean()), 2),
        'std': round(float(valid_nonzero.std()), 2),
        'anomaly_indices': anomaly_indices[:100],  # 最多返回100个索引
        'anomaly_values': [round(float(x), 2) for x in anomalies.head(100).tolist()],
        'anomaly_details': [
            {'index': int(i), 'value': round(float(v), 2), 'zscore': round(float(z_scores.loc[i]), 2)}
            for i, v in anomalies.head(50).items()
        ],
    }


def detect_by_iqr(df: pd.DataFrame, amount_col: str = None, multiplier: float = 1.5) -> dict:
    """
    IQR 四分位距异常检测
    下界 = Q1 - multiplier * IQR
    上界 = Q3 + multiplier * IQR
    """
    if amount_col is None:
        num_cols = df.select_dtypes(include=[np.number]).columns
        if len(num_cols) == 0:
            return {'method': 'iqr', 'error': '无数值列'}
        amount_col = num_cols[0]

    amounts = pd.to_numeric(df[amount_col], errors='coerce')
    valid = amounts.dropna()

    if len(valid) < 10:
        return {'method': 'iqr', 'error': '数据量不足（需要≥10条记录）'}

    q1 = valid.quantile(0.25)
    q3 = valid.quantile(0.75)
    iqr = q3 - q1

    if iqr == 0:
        return {'method': 'iqr', 'error': 'IQR为0，数据无变异性'}

    lower_bound = q1 - multiplier * iqr
    upper_bound = q3 + multiplier * iqr

    anomalies = valid[(valid < lower_bound) | (valid > upper_bound)]
    below = valid[valid < lower_bound]
    above = valid[valid > upper_bound]

    return {
        'method': 'iqr',
        'name': 'IQR异常检测',
        'column': amount_col,
        'multiplier': multiplier,
        'q1': round(float(q1), 2),
        'q3': round(float(q3), 2),
        'iqr': round(float(iqr), 2),
        'lower_bound': round(float(lower_bound), 2),
        'upper_bound': round(float(upper_bound), 2),
        'total_records': len(valid),
        'anomaly_count': len(anomalies),
        'anomaly_pct': round(len(anomalies) / len(valid) * 100, 2),
        'below_lower': len(below),
        'above_upper': len(above),
        'anomaly_details': [
            {'index': int(i), 'value': round(float(v), 2), 'type': 'low' if v < lower_bound else 'high'}
            for i, v in anomalies.head(50).items()
        ],
    }


def detect_by_group_zscore(df: pd.DataFrame, amount_col: str = None,
                           group_col: str = None, threshold: float = 2.5) -> list[dict]:
    """
    分组Z-Score检测：按类别/部门分组后在组内检测异常
    更精细地发现同一类别中的异常值
    """
    if amount_col is None:
        num_cols = df.select_dtypes(include=[np.number]).columns
        if len(num_cols) == 0:
            return [{'method': 'group_zscore', 'error': '无数值列'}]
        amount_col = num_cols[0]

    if group_col is None:
        cat_cols = df.select_dtypes(include=['object']).columns
        if len(cat_cols) == 0:
            return [{'method': 'group_zscore', 'error': '无分类列'}]
        group_col = cat_cols[0]

    df = df.copy()
    df['_amt'] = pd.to_numeric(df[amount_col], errors='coerce')

    results = []
    for group_name, group_df in df.groupby(group_col):
        valid = group_df['_amt'].dropna()
        if len(valid) < 5:
            continue

        z_scores = np.abs(scipy_stats.zscore(valid))
        anom = valid[z_scores > threshold]

        if len(anom) > 0:
            results.append({
                'group_name': str(group_name),
                'group_size': len(group_df),
                'anomaly_count': len(anom),
                'anomaly_pct': round(len(anom) / len(valid) * 100, 2),
                'mean': round(float(valid.mean()), 2),
                'std': round(float(valid.std()), 2),
                'anomaly_values': [round(float(x), 2) for x in anom.head(10).tolist()],
            })

    # 按异常数量降序排列
    results.sort(key=lambda x: x['anomaly_count'], reverse=True)

    return {
        'method': 'group_zscore',
        'name': '分组Z-Score检测',
        'column': amount_col,
        'group_column': group_col,
        'threshold': threshold,
        'groups_with_anomalies': len(results),
        'total_anomalies': sum(r['anomaly_count'] for r in results),
        'group_details': results[:30],  # 最多30个组
    }


def run_all_detectors(df: pd.DataFrame) -> dict:
    """运行全部异常检测器"""
    results = {}

    # Z-Score
    try:
        results['zscore'] = detect_by_zscore(df)
    except Exception as e:
        results['zscore'] = {'method': 'zscore', 'error': str(e)}

    # IQR
    try:
        results['iqr'] = detect_by_iqr(df)
    except Exception as e:
        results['iqr'] = {'method': 'iqr', 'error': str(e)}

    # 分组Z-Score
    try:
        results['group_zscore'] = detect_by_group_zscore(df)
    except Exception as e:
        results['group_zscore'] = {'method': 'group_zscore', 'error': str(e)}

    total_anomalies = (
        results.get('zscore', {}).get('anomaly_count', 0) +
        results.get('iqr', {}).get('anomaly_count', 0)
    )

    return {
        'detectors': results,
        'summary': {
            'total_anomalies_found': total_anomalies,
            'methods_used': len([v for v in results.values() if 'error' not in v]),
        },
    }
