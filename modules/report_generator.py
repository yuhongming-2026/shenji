"""
审计报告生成器 - 汇总发现、风险评分、Excel导出
"""
from __future__ import annotations

import io
from datetime import datetime
import pandas as pd


RISK_SCORE_MAP = {'high': 3, 'medium': 2, 'low': 1, 'unknown': 0}
RISK_LABELS = {3: '高风险', 2: '中风险', 1: '低风险', 0: '未知'}


def calculate_overall_score(audit_results: list[dict], anomaly_results: dict) -> dict:
    """综合风险评估"""
    total_score = 0
    max_score = 0
    risk_items = []

    for r in audit_results:
        item_risk = RISK_SCORE_MAP.get(r.get('risk', 'unknown'), 0)
        total_score += item_risk
        max_score += 3
        if item_risk >= 2:
            risk_items.append({
                'rule': r.get('rule', ''),
                'name': r.get('name', ''),
                'risk': r.get('risk', 'unknown'),
                'description': r.get('description', ''),
            })

    # 异常检测评分
    anom_summary = anomaly_results.get('summary', {})
    total_anomalies = anom_summary.get('total_anomalies_found', 0)
    if total_anomalies > 50:
        total_score += 3
        risk_items.append({'rule': 'anomaly', 'name': '统计异常检测', 'risk': 'high', 'description': f'发现 {total_anomalies} 个统计异常值'})
    elif total_anomalies > 10:
        total_score += 2
        risk_items.append({'rule': 'anomaly', 'name': '统计异常检测', 'risk': 'medium', 'description': f'发现 {total_anomalies} 个统计异常值'})
    elif total_anomalies > 0:
        total_score += 1

    max_score += 3

    # 风险率
    risk_pct = round(total_score / max_score * 100, 1) if max_score > 0 else 0

    if risk_pct >= 60:
        overall = 'high'
    elif risk_pct >= 30:
        overall = 'medium'
    else:
        overall = 'low'

    return {
        'overall_risk': overall,
        'overall_label': RISK_LABELS.get(RISK_SCORE_MAP[overall], '未知'),
        'risk_score': total_score,
        'max_score': max_score,
        'risk_percentage': risk_pct,
        'risk_items': risk_items,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def generate_html_report(audit_results: list[dict], anomaly_results: dict,
                         data_summary: dict, score: dict) -> str:
    """生成HTML审计报告"""
    suspicious_count = sum(1 for r in audit_results if r.get('suspicious'))

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>财务审计报告</title>
<style>
  body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; max-width: 900px; margin: 0 auto; padding: 20px; color: #333; }}
  h1 {{ text-align: center; color: #1a56db; border-bottom: 3px solid #1a56db; padding-bottom: 10px; }}
  h2 {{ color: #1e40af; margin-top: 30px; border-left: 4px solid #1a56db; padding-left: 10px; }}
  .meta {{ text-align: center; color: #666; margin-bottom: 20px; }}
  .risk-badge {{ display: inline-block; padding: 4px 12px; border-radius: 12px; font-weight: bold; font-size: 14px; }}
  .risk-high {{ background: #fde8e8; color: #c81e1e; }}
  .risk-medium {{ background: #fef3c7; color: #b45309; }}
  .risk-low {{ background: #e6f4ea; color: #166534; }}
  .summary-cards {{ display: flex; gap: 15px; margin: 20px 0; flex-wrap: wrap; }}
  .card {{ flex: 1; min-width: 150px; padding: 15px; border-radius: 8px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,.1); }}
  .card-value {{ font-size: 28px; font-weight: bold; }}
  .card-label {{ color: #666; font-size: 14px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
  th {{ background: #f8fafc; font-weight: 600; }}
  tr:hover {{ background: #f1f5f9; }}
  .footer {{ text-align: center; margin-top: 40px; color: #999; font-size: 12px; border-top: 1px solid #eee; padding-top: 15px; }}
</style>
</head>
<body>
<h1>📊 财务审计报告</h1>
<p class="meta">报告生成时间：{score['generated_at']} | 数据文件：{data_summary.get('filename', 'N/A')}</p>

<div class="summary-cards">
  <div class="card" style="background:#f0f7ff">
    <div class="card-value">{data_summary.get('total_rows', 0):,}</div>
    <div class="card-label">数据总行数</div>
  </div>
  <div class="card" style="background:#f0fdf4">
    <div class="card-value">{suspicious_count}</div>
    <div class="card-label">可疑发现</div>
  </div>
  <div class="card" style="background:#fff7ed">
    <div class="card-value"><span class="risk-badge risk-{score['overall_risk']}">{score['overall_label']}</span></div>
    <div class="card-label">综合风险评级</div>
  </div>
  <div class="card" style="background:#fef2f2">
    <div class="card-value">{score['risk_percentage']}%</div>
    <div class="card-label">风险评分</div>
  </div>
</div>

<h2>一、综合风险评估</h2>
<p>风险得分：{score['risk_score']} / {score['max_score']}（{score['risk_percentage']}%），综合评级：<span class="risk-badge risk-{score['overall_risk']}">{score['overall_label']}</span></p>

<h2>二、审计规则检测结果</h2>
<table>
<tr><th>#</th><th>审计规则</th><th>风险等级</th><th>检测结果</th><th>状态</th></tr>
'''
    for i, r in enumerate(audit_results, 1):
        risk = r.get('risk', 'unknown')
        desc = r.get('description', r.get('error', r.get('warning', '-')))
        status = '⚠️ 可疑' if r.get('suspicious') else '✅ 正常'
        html += f'<tr><td>{i}</td><td><strong>{r.get("name", "")}</strong></td><td><span class="risk-badge risk-{risk}">{RISK_LABELS.get(RISK_SCORE_MAP.get(risk, 0), risk)}</span></td><td>{desc}</td><td>{status}</td></tr>\n'

    html += '''
</table>

<h2>三、统计异常检测</h2>
<table>
<tr><th>检测方法</th><th>检测记录数</th><th>异常数量</th><th>异常占比</th></tr>
'''
    detectors = anomaly_results.get('detectors', {})
    for key, d in detectors.items():
        if 'error' in d:
            html += f'<tr><td>{d.get("name", key)}</td><td colspan="3">错误：{d["error"]}</td></tr>'
        else:
            html += f'<tr><td>{d.get("name", key)}</td><td>{d.get("total_records", 0):,}</td><td>{d.get("anomaly_count", 0)}</td><td>{d.get("anomaly_pct", 0)}%</td></tr>'

    html += f'''
</table>

<div class="footer">
  <p>本报告由财务大数据审计系统自动生成 | {score['generated_at']}</p>
  <p>仅供内部审计参考，不构成最终审计意见</p>
</div>
</body>
</html>'''
    return html


def export_to_excel(audit_results: list[dict], anomaly_results: dict,
                    score: dict) -> io.BytesIO:
    """导出Excel格式审计报告"""
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Sheet 1: 风险评估
        risk_df = pd.DataFrame([{
            '综合风险': score['overall_label'],
            '风险得分': score['risk_score'],
            '满分': score['max_score'],
            '风险百分比': f"{score['risk_percentage']}%",
            '生成时间': score['generated_at'],
        }])
        risk_df.to_excel(writer, sheet_name='综合风险', index=False)

        # Sheet 2: 审计规则结果
        rules_data = []
        for r in audit_results:
            rules_data.append({
                '规则名称': r.get('name', ''),
                '风险等级': RISK_LABELS.get(RISK_SCORE_MAP.get(r.get('risk', 'unknown'), 0), '未知'),
                '是否可疑': '是' if r.get('suspicious') else '否',
                '检测结果': r.get('description', r.get('error', '')),
            })
        pd.DataFrame(rules_data).to_excel(writer, sheet_name='审计规则检测', index=False)

        # Sheet 3: 异常检测
        anom_data = []
        for key, d in anomaly_results.get('detectors', {}).items():
            anom_data.append({
                '检测方法': d.get('name', key),
                '检测列': d.get('column', ''),
                '总记录数': d.get('total_records', 0),
                '异常数量': d.get('anomaly_count', 0),
                '异常占比(%)': d.get('anomaly_pct', 0),
            })
        pd.DataFrame(anom_data).to_excel(writer, sheet_name='异常检测', index=False)

    output.seek(0)
    return output


# ============================================================
# V2: 扩展版（纳入三阶段审计结果）
# ============================================================

def calculate_overall_score_v2(
    audit_results: list[dict],
    anomaly_results: dict,
    phase1_results: dict | None = None,
    phase2_results: dict | None = None,
    phase3_results: dict | None = None,
) -> dict:
    """纳入三阶段审计结果的综合评分"""
    base = calculate_overall_score(audit_results, anomaly_results)

    total_score = base['risk_score']
    max_score = base['max_score']
    risk_items = list(base['risk_items'])

    # Phase 1: 风险评估（每个高风险+3，中风险+2）
    if phase1_results:
        p1 = phase1_results.get('summary', {})
        total_score += p1.get('high_risk', 0) * 3
        total_score += p1.get('medium_risk', 0) * 2
        max_score += p1.get('total_procedures', 3) * 3

        for key, proc in phase1_results.get('procedures', {}).items():
            if proc.get('suspicious'):
                risk_items.append({
                    'rule': proc.get('rule', key),
                    'name': f"[风险评估] {proc.get('name', key)}",
                    'risk': proc.get('risk', 'low'),
                    'description': proc.get('description', ''),
                })

    # Phase 2: 控制测试
    if phase2_results:
        p2 = phase2_results.get('summary', {})
        total_score += p2.get('high_risk', 0) * 3
        total_score += p2.get('medium_risk', 0) * 2
        max_score += p2.get('total_procedures', 2) * 3

        for key, proc in phase2_results.get('procedures', {}).items():
            if proc.get('suspicious'):
                risk_items.append({
                    'rule': proc.get('rule', key),
                    'name': f"[控制测试] {proc.get('name', key)}",
                    'risk': proc.get('risk', 'low'),
                    'description': proc.get('description', ''),
                })

    # Phase 3: 实质性程序（权重更大）
    if phase3_results:
        p3 = phase3_results.get('summary', {})
        total_score += p3.get('high_risk', 0) * 4
        total_score += p3.get('medium_risk', 0) * 2
        max_score += p3.get('total_procedures', 12) * 4

        for key, proc in phase3_results.get('procedures', {}).items():
            if proc.get('suspicious'):
                risk_items.append({
                    'rule': proc.get('rule', key),
                    'name': f"[实质性程序] {proc.get('name', key)}",
                    'risk': proc.get('risk', 'low'),
                    'description': proc.get('description', ''),
                })

    risk_pct = round(total_score / max_score * 100, 1) if max_score > 0 else 0

    if risk_pct >= 60:
        overall = 'high'
    elif risk_pct >= 30:
        overall = 'medium'
    else:
        overall = 'low'

    return {
        'overall_risk': overall,
        'overall_label': RISK_LABELS.get(RISK_SCORE_MAP[overall], '未知'),
        'risk_score': total_score,
        'max_score': max_score,
        'risk_percentage': risk_pct,
        'risk_items': risk_items,
        'generated_at': datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
    }


def generate_html_report_v2(
    audit_results: list[dict],
    anomaly_results: dict,
    data_summary: dict,
    score: dict,
    phase1_results: dict | None = None,
    phase2_results: dict | None = None,
    phase3_results: dict | None = None,
) -> str:
    """生成扩展版 HTML 审计报告，包含三阶段审计结果"""
    suspicious_count = sum(1 for r in audit_results if r.get('suspicious'))

    html = f'''<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="UTF-8">
<title>财务审计报告（完整版）</title>
<style>
  body {{ font-family: 'Microsoft YaHei', Arial, sans-serif; max-width: 960px; margin: 0 auto; padding: 20px; color: #333; }}
  h1 {{ text-align: center; color: #1a56db; border-bottom: 3px solid #1a56db; padding-bottom: 10px; }}
  h2 {{ color: #1e40af; margin-top: 30px; border-left: 4px solid #1a56db; padding-left: 10px; }}
  h3 {{ color: #374151; margin-top: 20px; }}
  .meta {{ text-align: center; color: #666; margin-bottom: 20px; }}
  .risk-badge {{ display: inline-block; padding: 4px 12px; border-radius: 12px; font-weight: bold; font-size: 14px; }}
  .risk-high {{ background: #fde8e8; color: #c81e1e; }}
  .risk-medium {{ background: #fef3c7; color: #b45309; }}
  .risk-low {{ background: #e6f4ea; color: #166534; }}
  .summary-cards {{ display: flex; gap: 15px; margin: 20px 0; flex-wrap: wrap; }}
  .card {{ flex: 1; min-width: 150px; padding: 15px; border-radius: 8px; text-align: center; box-shadow: 0 2px 4px rgba(0,0,0,.1); }}
  .card-value {{ font-size: 28px; font-weight: bold; }}
  .card-label {{ color: #666; font-size: 14px; }}
  table {{ width: 100%; border-collapse: collapse; margin: 15px 0; }}
  th, td {{ border: 1px solid #ddd; padding: 8px 12px; text-align: left; }}
  th {{ background: #f8fafc; font-weight: 600; }}
  tr:hover {{ background: #f1f5f9; }}
  .finding {{ border-left: 4px solid #dc2626; background: #fef2f2; padding: 10px 15px; margin: 10px 0; border-radius: 4px; }}
  .finding.medium {{ border-left-color: #d97706; background: #fff7ed; }}
  .finding.low {{ border-left-color: #059669; background: #f0fdf4; }}
  .pass {{ color: #059669; }} .fail {{ color: #dc2626; }}
  .footer {{ text-align: center; margin-top: 40px; color: #999; font-size: 12px; border-top: 1px solid #eee; padding-top: 15px; }}
</style>
</head>
<body>
<h1>📊 财务审计报告（完整版）</h1>
<p class="meta">报告生成时间：{score['generated_at']} | 数据文件：{data_summary.get('filename', 'N/A')}</p>

<div class="summary-cards">
  <div class="card" style="background:#f0f7ff">
    <div class="card-value">{data_summary.get('total_rows', 0):,}</div>
    <div class="card-label">数据总行数</div>
  </div>
  <div class="card" style="background:#f0fdf4">
    <div class="card-value">{suspicious_count}</div>
    <div class="card-label">可疑发现</div>
  </div>
  <div class="card" style="background:#fff7ed">
    <div class="card-value"><span class="risk-badge risk-{score['overall_risk']}">{score['overall_label']}</span></div>
    <div class="card-label">综合风险评级</div>
  </div>
  <div class="card" style="background:#fef2f2">
    <div class="card-value">{score['risk_percentage']}%</div>
    <div class="card-label">风险评分</div>
  </div>
</div>

<h2>一、综合风险评估</h2>
<p>风险得分：{score['risk_score']} / {score['max_score']}（{score['risk_percentage']}%），综合评级：<span class="risk-badge risk-{score['overall_risk']}">{score['overall_label']}</span></p>
'''

    # 审计规则
    html += '<h2>二、审计规则检测结果</h2><table>'
    html += '<tr><th>#</th><th>审计规则</th><th>风险等级</th><th>检测结果</th><th>状态</th></tr>'
    for i, r in enumerate(audit_results, 1):
        risk = r.get('risk', 'unknown')
        desc = r.get('description', r.get('error', '-'))
        status = '⚠️ 可疑' if r.get('suspicious') else '✅ 正常'
        html += f'<tr><td>{i}</td><td><strong>{r.get("name", "")}</strong></td><td><span class="risk-badge risk-{risk}">{RISK_LABELS.get(RISK_SCORE_MAP.get(risk, 0), risk)}</span></td><td>{desc}</td><td>{status}</td></tr>'
    html += '</table>'

    # 异常检测
    html += '<h2>三、统计异常检测</h2><table>'
    html += '<tr><th>检测方法</th><th>检测记录数</th><th>异常数量</th><th>异常占比</th></tr>'
    for key, d in anomaly_results.get('detectors', {}).items():
        if 'error' in d:
            html += f'<tr><td>{d.get("name", key)}</td><td colspan="3">错误：{d["error"]}</td></tr>'
        else:
            html += f'<tr><td>{d.get("name", key)}</td><td>{d.get("total_records", 0):,}</td><td>{d.get("anomaly_count", 0)}</td><td>{d.get("anomaly_pct", 0)}%</td></tr>'
    html += '</table>'

    # Phase 1
    if phase1_results:
        html += '<h2>四、风险评估阶段</h2>'
        p1s = phase1_results.get('summary', {})
        html += f'<p>共{p1s.get("total_procedures",0)}项评估，高风险{p1s.get("high_risk",0)}项，中风险{p1s.get("medium_risk",0)}项</p>'
        for key, proc in phase1_results.get('procedures', {}).items():
            findings = proc.get('anomalies', []) or proc.get('findings', []) or proc.get('outliers', [])
            risk = proc.get('risk', 'low')
            html += f'<h3>{proc.get("name", key)} <span class="risk-badge risk-{risk}">{RISK_LABELS.get(RISK_SCORE_MAP.get(risk, 0), risk)}</span></h3>'
            html += f'<p>{proc.get("description", "")}</p>'
            for f in findings[:10]:
                html += f'<div class="finding {f.get("risk", "low")}">{f.get("description", str(f))}</div>'

    # Phase 2
    if phase2_results:
        html += '<h2>五、控制测试阶段</h2>'
        p2s = phase2_results.get('summary', {})
        html += f'<p>共{p2s.get("total_procedures",0)}项测试，高风险{p2s.get("high_risk",0)}项，中风险{p2s.get("medium_risk",0)}项</p>'
        for key, proc in phase2_results.get('procedures', {}).items():
            risk = proc.get('risk', 'low')
            html += f'<h3>{proc.get("name", key)} <span class="risk-badge risk-{risk}">{RISK_LABELS.get(RISK_SCORE_MAP.get(risk, 0), risk)}</span></h3>'
            html += f'<p>{proc.get("description", "")}</p>'
            for t in proc.get('tests', [])[:10]:
                cls = 'pass' if t.get('passed') else 'fail'
                icon = '✅' if t.get('passed') else '❌'
                html += f'<div class="finding low"><span class="{cls}">{icon}</span> {t.get("test", "")}: {t.get("detail", "")}</div>'
            for f in proc.get('findings', [])[:5]:
                html += f'<div class="finding {f.get("risk", "low")}">{f.get("description", str(f))}</div>'

    # Phase 3
    if phase3_results:
        html += '<h2>六、实质性程序</h2>'
        p3s = phase3_results.get('summary', {})
        html += f'<p>共{p3s.get("total_procedures",0)}项程序，高风险{p3s.get("high_risk",0)}项，中风险{p3s.get("medium_risk",0)}项，发现{p3s.get("total_findings",0)}个问题</p>'
        for key, proc in phase3_results.get('procedures', {}).items():
            risk = proc.get('risk', 'low')
            html += f'<h3>{proc.get("name", key)} <span class="risk-badge risk-{risk}">{RISK_LABELS.get(RISK_SCORE_MAP.get(risk, 0), risk)}</span></h3>'
            html += f'<p>{proc.get("description", "")}</p>'
            for f in proc.get('findings', [])[:5]:
                html += f'<div class="finding {f.get("risk", "low")}">{f.get("description", str(f))}</div>'

    html += f'''
<div class="footer">
  <p>本报告由财务大数据审计系统自动生成 | {score['generated_at']}</p>
  <p>仅供内部审计参考，不构成最终审计意见</p>
</div>
</body>
</html>'''
    return html


def export_to_excel_v2(
    audit_results: list[dict],
    anomaly_results: dict,
    score: dict,
    phase1_results: dict | None = None,
    phase2_results: dict | None = None,
    phase3_results: dict | None = None,
) -> io.BytesIO:
    """导出扩展版 Excel 审计报告"""
    output = io.BytesIO()

    with pd.ExcelWriter(output, engine='openpyxl') as writer:
        # Sheet 1: 综合风险
        pd.DataFrame([{
            '综合风险': score['overall_label'],
            '风险得分': score['risk_score'],
            '满分': score['max_score'],
            '风险百分比': f"{score['risk_percentage']}%",
            '生成时间': score['generated_at'],
        }]).to_excel(writer, sheet_name='综合风险', index=False)

        # Sheet 2: 审计规则
        pd.DataFrame([{
            '规则名称': r.get('name', ''),
            '风险等级': RISK_LABELS.get(RISK_SCORE_MAP.get(r.get('risk', 'unknown'), 0), '未知'),
            '是否可疑': '是' if r.get('suspicious') else '否',
            '检测结果': r.get('description', r.get('error', '')),
        } for r in audit_results]).to_excel(writer, sheet_name='审计规则检测', index=False)

        # Sheet 3: 异常检测
        pd.DataFrame([{
            '检测方法': d.get('name', key),
            '总记录数': d.get('total_records', 0),
            '异常数量': d.get('anomaly_count', 0),
            '异常占比(%)': d.get('anomaly_pct', 0),
        } for key, d in anomaly_results.get('detectors', {}).items()]).to_excel(writer, sheet_name='异常检测', index=False)

        # Sheet 4-6: 三阶段
        for phase_name, phase_data in [('风险评估', phase1_results), ('控制测试', phase2_results), ('实质性程序', phase3_results)]:
            if phase_data:
                rows = []
                for key, proc in phase_data.get('procedures', {}).items():
                    rows.append({
                        '程序名称': proc.get('name', key),
                        '风险等级': RISK_LABELS.get(RISK_SCORE_MAP.get(proc.get('risk', 'low'), 0), '未知'),
                        '是否可疑': '是' if proc.get('suspicious') else '否',
                        '发现数': len(proc.get('findings', [])),
                        '描述': proc.get('description', ''),
                    })
                if rows:
                    pd.DataFrame(rows).to_excel(writer, sheet_name=phase_name, index=False)

    output.seek(0)
    return output
