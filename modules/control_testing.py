"""
控制测试阶段 - IT控制测试、业务流程自动化测试（RPA模拟）
"""
from __future__ import annotations

import numpy as np
import pandas as pd
from datetime import datetime, timedelta

from modules.audit_data_helpers import detect_financial_columns


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
        'department': cols['department'][0] if cols['department'] else None,
        'approver': cols['approver'][0] if cols['approver'] else None,
    }


def _safe_numeric(series: pd.Series) -> pd.Series:
    return pd.to_numeric(series, errors='coerce')


# ============================================================
# 1. IT 控制测试
# ============================================================

def test_it_controls(df: pd.DataFrame) -> dict:
    """
    自动测试系统权限、数据备份、日志记录等 IT 控制的有效性。

    基于数据特征推断 IT 控制状态：
    - 数据完整性：检查缺失值、重复记录
    - 权限分离：检查是否有不同部门/用户的操作记录
    - 日志完整性：检查日期连续性、操作轨迹
    - 备份有效性：检查数据文件完整性

    Returns:
        {
            'rule': 'it_controls',
            'name': 'IT控制测试',
            'suspicious': bool,
            'risk': 'high'|'medium'|'low',
            'tests': [...],
            'passed': int,
            'failed': int,
            'findings': [...],
        }
    """
    cols = _detect_columns(df)
    tests = []
    findings = []

    # --- 测试1: 数据完整性 ---
    total = len(df)
    missing_pct = df.isnull().mean().mean() * 100 if total > 0 else 0
    dup_count = int(df.duplicated().sum()) if total > 0 else 0
    dup_pct = dup_count / max(total, 1) * 100

    integrity_passed = missing_pct < 10 and dup_pct < 3
    tests.append({
        'test': '数据完整性',
        'passed': integrity_passed,
        'detail': f'缺失率{missing_pct:.1f}%，重复率{dup_pct:.1f}%',
        'threshold': '缺失率<10% 且 重复率<3%',
    })
    if not integrity_passed:
        findings.append({
            'test': '数据完整性', 'risk': 'high' if missing_pct > 20 else 'medium',
            'description': f'数据完整性问题：缺失率{missing_pct:.1f}%，重复记录{dup_count}条',
            'remediation': '建议：1)完善数据录入流程 2)建立数据审核机制 3)定期清理重复数据',
        })

    # --- 测试2: 权限分离 ---
    dept_passed = True
    approver_passed = True

    if cols['department']:
        depts = df[cols['department']].dropna().nunique()
        dept_passed = depts >= 2  # 至少有部门划分
        tests.append({
            'test': '权限分离-部门',
            'passed': dept_passed,
            'detail': f'检测到{depts}个部门',
            'threshold': '至少2个部门',
        })
        if not dept_passed:
            findings.append({
                'test': '权限分离', 'risk': 'medium',
                'description': f'仅{depts}个部门，可能存在权限未分离风险',
                'remediation': '建议：按职责设置不同部门权限',
            })

    if cols['approver']:
        approvers = df[cols['approver']].dropna().nunique()
        approver_passed = approvers >= 2
        tests.append({
            'test': '权限分离-审批',
            'passed': approver_passed,
            'detail': f'检测到{approvers}个审批人',
            'threshold': '至少2个审批人',
        })
        if not approver_passed:
            findings.append({
                'test': '审批权限', 'risk': 'high',
                'description': f'仅{approvers}个审批人，可能存在审批权限集中风险',
                'remediation': '建议：设置多级审批机制，分离经办与审批',
            })

    # --- 测试3: 日志/日期连续性 ---
    log_passed = True
    if cols['date']:
        try:
            dates = pd.to_datetime(df[cols['date']], errors='coerce').dropna().sort_values()
            if len(dates) >= 2:
                date_range = (dates.max() - dates.min()).days
                expected_density = len(dates) / max(date_range, 1)
                # 日期跨度大但记录少 → 可能存在日志缺失
                if date_range > 30 and expected_density < 0.5:
                    log_passed = False
                    findings.append({
                        'test': '日志完整性', 'risk': 'medium',
                        'description': f'日期跨度{date_range}天，日均记录仅{expected_density:.2f}条，可能存在日志缺失',
                        'remediation': '建议：检查系统日志配置，确保所有操作被完整记录',
                    })
        except Exception:
            pass
    tests.append({
        'test': '日志完整性',
        'passed': log_passed,
        'detail': f"日期列{'正常' if log_passed else '存在异常间隙'}",
        'threshold': '日期连续，日均记录密度合理',
    })

    # --- 测试4: 数据备份指标 ---
    # 检查是否有最近的数据（模拟备份检查）
    backup_passed = True
    if cols['date']:
        try:
            dates = pd.to_datetime(df[cols['date']], errors='coerce').dropna()
            if len(dates) > 0:
                latest = dates.max()
                days_since = (datetime.now() - latest).days
                # 如果最新数据距今超过7天，可能存在备份不及时
                if days_since > 7:
                    backup_passed = False
                    findings.append({
                        'test': '数据备份', 'risk': 'medium',
                        'description': f'最新数据日期为{latest.strftime("%Y-%m-%d")}，距今{days_since}天，备份可能不及时',
                        'remediation': '建议：建立每日自动备份机制，定期验证备份可恢复性',
                    })
        except Exception:
            pass
    tests.append({
        'test': '数据时效性',
        'passed': backup_passed,
        'detail': '数据在合理时效范围内' if backup_passed else '数据可能未及时更新/备份',
        'threshold': '最新数据在7天内',
    })

    # --- 综合 ---
    passed = sum(1 for t in tests if t['passed'])
    failed = len(tests) - passed
    risk = 'high' if failed >= 3 else ('medium' if failed >= 1 else 'low')

    return {
        'rule': 'it_controls',
        'name': 'IT控制测试',
        'suspicious': failed > 0,
        'risk': risk,
        'tests': tests,
        'passed': passed,
        'failed': failed,
        'total_tests': len(tests),
        'findings': findings,
        'description': f"IT控制测试：{passed}/{len(tests)}项通过，发现{failed}项控制缺陷" if failed else f"IT控制测试：全部{passed}项通过",
    }


# ============================================================
# 2. 业务流程自动化测试（RPA模拟穿行测试）
# ============================================================

def test_business_automation(df: pd.DataFrame) -> dict:
    """
    RPA 模拟业务流程测试：
    模拟 采购→审批→付款→入账 流程的穿行测试，
    检查每个环节的控制执行情况。

    基于数据推断：
    - 采购到付款周期
    - 审批完整性
    - 金额匹配
    - 异常流程

    Returns:
        {
            'rule': 'biz_automation',
            'name': '业务流程自动化测试',
            'suspicious': bool,
            'risk': 'high'|'medium'|'low',
            'workflow_steps': [...],
            'bottlenecks': [...],
            'findings': [...],
        }
    """
    cols = _detect_columns(df)
    amount_col = cols['amount']
    date_col = cols['date']
    voucher_col = cols['voucher']
    category_col = cols['category']

    workflow_steps = []
    bottlenecks = []
    findings = []
    total = len(df)

    if total == 0:
        return {
            'rule': 'biz_automation', 'name': '业务流程自动化测试',
            'suspicious': False, 'risk': 'low',
            'workflow_steps': [], 'bottlenecks': [], 'findings': [],
            'description': '无数据可供测试',
        }

    # --- 步骤1: 单据完整性 ---
    voucher_complete = True
    if voucher_col:
        missing_vouchers = df[voucher_col].isna().sum()
        voucher_complete = missing_vouchers == 0
        workflow_steps.append({
            'step': '单据编号完整性',
            'passed': voucher_complete,
            'detail': f'凭证缺失率{missing_vouchers/max(total,1)*100:.1f}%',
        })
        if not voucher_complete:
            bottlenecks.append({
                'step': '单据录入', 'issue': f'{missing_vouchers}条记录无凭证号',
                'risk': 'high', 'impact': '无法追溯业务单据',
            })

    # --- 步骤2: 金额合理性 ---
    amount_ok = True
    if amount_col:
        amounts = _safe_numeric(df[amount_col])
        negative_pct = (amounts < 0).sum() / max(total, 1) * 100
        zero_pct = (amounts == 0).sum() / max(total, 1) * 100
        amount_ok = negative_pct < 20 and zero_pct < 10
        workflow_steps.append({
            'step': '金额合理性',
            'passed': amount_ok,
            'detail': f'负数率{negative_pct:.1f}%，零值率{zero_pct:.1f}%',
        })
        if not amount_ok:
            bottlenecks.append({
                'step': '金额确认', 'issue': f'负数率{negative_pct:.1f}%，零值率{zero_pct:.1f}%',
                'risk': 'high', 'impact': '存在异常冲销或未确认交易',
            })

    # --- 步骤3: 日期顺序 ---
    date_ordered = True
    if date_col:
        try:
            dates = pd.to_datetime(df[date_col], errors='coerce')
            date_diffs = dates.dropna().diff().dropna()
            # 检查是否有大量负时间差（日期倒序）
            backward = (date_diffs.dt.total_seconds() < 0).sum()
            date_ordered = backward / max(len(date_diffs), 1) < 0.1
            workflow_steps.append({
                'step': '日期顺序检查',
                'passed': date_ordered,
                'detail': f'日期倒序{backward}条（共{len(date_diffs)}条）',
            })
            if not date_ordered:
                bottlenecks.append({
                    'step': '时序检查', 'issue': f'{backward}条记录日期倒序',
                    'risk': 'medium', 'impact': '可能存在后补单据或日期录入错误',
                })
        except Exception:
            workflow_steps.append({
                'step': '日期顺序检查', 'passed': True,
                'detail': '日期列无法解析，跳过检查',
            })

    # --- 步骤4: 分类一致性 ---
    category_ok = True
    if category_col:
        categories = df[category_col].dropna().nunique()
        if categories == 0:
            category_ok = False
        # 检查是否有异常高频分类
        top_cat_pct = df[category_col].value_counts().iloc[0] / max(total, 1) if categories > 0 else 0
        category_ok = categories > 1 and top_cat_pct < 0.8
        workflow_steps.append({
            'step': '分类合理性',
            'passed': category_ok,
            'detail': f'{categories}个分类，最大类占比{top_cat_pct*100:.1f}%',
        })
        if not category_ok:
            bottlenecks.append({
                'step': '分类控制', 'issue': f'分类过于集中（最大类{top_cat_pct*100:.0f}%）',
                'risk': 'medium', 'impact': '可能存在交易分类错误或业务单一风险',
            })

    # --- 步骤5: 审批链检查 ---
    approval_ok = True
    if cols['approver']:
        approver_counts = df[cols['approver']].value_counts()
        # 单一审批人处理过多 → 审批独立性不足
        if len(approver_counts) > 0 and approver_counts.iloc[0] / max(total, 1) > 0.7:
            approval_ok = False
        workflow_steps.append({
            'step': '审批独立性',
            'passed': approval_ok,
            'detail': f'{len(approver_counts)}个审批人',
        })
        if not approval_ok:
            bottlenecks.append({
                'step': '审批链', 'issue': f'审批集中度过高（{approver_counts.index[0]}处理{approver_counts.iloc[0]}条）',
                'risk': 'high', 'impact': '审批独立性不足，存在合谋风险',
            })

    # --- 综合 ---
    passed_steps = sum(1 for s in workflow_steps if s['passed'])
    total_steps = max(len(workflow_steps), 1)
    pass_rate = passed_steps / total_steps * 100

    risk = 'high' if pass_rate < 40 else ('medium' if pass_rate < 80 else 'low')

    # 汇总发现
    for b in bottlenecks:
        findings.append({
            'type': '流程瓶颈',
            'step': b['step'],
            'issue': b['issue'],
            'risk': b['risk'],
            'impact': b['impact'],
            'description': f"[{b['step']}] {b['issue']} — {b['impact']}",
        })

    return {
        'rule': 'biz_automation',
        'name': '业务流程自动化测试',
        'suspicious': passed_steps < total_steps,
        'risk': risk,
        'workflow_steps': workflow_steps,
        'total_steps': total_steps,
        'passed_steps': passed_steps,
        'pass_rate': round(pass_rate, 1),
        'bottlenecks': bottlenecks,
        'findings': findings,
        'description': f"业务流程穿行测试：{passed_steps}/{total_steps}步骤通过（{pass_rate:.0f}%），发现{len(bottlenecks)}个瓶颈",
    }


# ============================================================
# 批量执行
# ============================================================

def run_control_tests(df: pd.DataFrame) -> dict:
    """
    批量执行所有控制测试。

    Returns:
        {
            'procedures': {
                'it_controls': {...},
                'biz_automation': {...},
            },
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

    # IT 控制测试
    try:
        results['it_controls'] = test_it_controls(df)
    except Exception as e:
        results['it_controls'] = {
            'rule': 'it_controls', 'name': 'IT控制测试',
            'suspicious': False, 'risk': 'low',
            'tests': [], 'findings': [], 'error': str(e),
            'description': f'执行异常: {e}',
        }

    # 业务流程测试
    try:
        results['biz_automation'] = test_business_automation(df)
    except Exception as e:
        results['biz_automation'] = {
            'rule': 'biz_automation', 'name': '业务流程自动化测试',
            'suspicious': False, 'risk': 'low',
            'workflow_steps': [], 'findings': [], 'error': str(e),
            'description': f'执行异常: {e}',
        }

    procedures = list(results.values())
    suspicious = [p for p in procedures if p.get('suspicious')]
    risks = [p.get('risk', 'low') for p in procedures]
    high_count = risks.count('high')
    medium_count = risks.count('medium')
    low_count = risks.count('low')

    total_findings = sum(
        len(p.get('findings', [])) for p in procedures
    )

    if high_count > 0:
        overall_risk = 'high'
    elif medium_count >= 2:
        overall_risk = 'medium'
    else:
        overall_risk = 'low'

    return {
        'procedures': results,
        'summary': {
            'total_procedures': 2,
            'suspicious_count': len(suspicious),
            'high_risk': high_count,
            'medium_risk': medium_count,
            'low_risk': low_count,
            'overall_risk': overall_risk,
            'total_findings': total_findings,
        },
    }
