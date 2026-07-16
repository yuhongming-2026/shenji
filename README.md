# 财务大数据审计系统

基于 Flask 的财务大数据智能审计平台，支持数据上传、审计规则检测、异常发现与报告导出。

## 功能特性

- **📤 数据上传** — 支持 CSV / Excel 格式，自动识别金额、日期、分类、凭证等关键列
- **📊 数据仪表盘** — 数据概览、统计摘要、可视化图表
- **🔍 7 项审计规则** — 内置审计规则引擎，覆盖重复凭证、金额阈值、日期异常、分类分布、高频交易、凭证连号、余额异常等
- **⚠️ 异常检测** — Z-Score + IQR 离群值检测，自动标记异常数据点
- **📋 报告导出** — 支持 HTML 在线报告和 Excel 导出
- **📈 综合评分** — 对数据质量与风险进行整体评估

## 技术栈

| 类别 | 技术 |
|------|------|
| Web 框架 | Flask 3.x |
| 数据处理 | Pandas、NumPy、SciPy |
| 前端 | HTML5、CSS3、JavaScript (原生) |
| 文件支持 | openpyxl、xlrd |

## 快速开始

### 环境要求

- Python 3.8+
- pip

### 安装

```bash
git clone https://gitee.com/mm-1/mm.git
cd mm
pip install -r requirements.txt
```

### 运行

```bash
python app.py
```

浏览器访问 `http://127.0.0.1:5000`

### 使用流程

1. 打开首页，上传财务数据文件（CSV 或 Excel）
2. 进入仪表盘查看数据总览
3. 在分析页面运行审计规则和异常检测
4. 查看并导出审计报告

## 项目结构

```
├── app.py                  # Flask 主应用入口
├── modules/
│   ├── data_processor.py   # 数据上传与预处理
│   ├── audit_rules.py      # 7 项审计规则引擎
│   ├── anomaly_detector.py # 异常检测（Z-Score / IQR）
│   └── report_generator.py # 报告生成与导出
├── templates/              # Jinja2 前端模板
│   ├── base.html           # 基础布局
│   ├── index.html          # 首页（上传）
│   ├── dashboard.html      # 数据仪表盘
│   ├── preview.html        # 数据预览
│   ├── analysis.html       # 审计分析
│   └── report.html         # 审计报告
├── static/                 # 静态资源
│   ├── css/style.css
│   └── js/main.js
├── uploads/                # 上传文件存储
├── requirements.txt        # Python 依赖
└── 示例财务数据.csv         # 示例数据
```

## 审计规则说明

| # | 规则 | 说明 |
|---|------|------|
| 1 | 重复凭证 | 检测凭证号重复的记录 |
| 2 | 大额交易 | 金额超过设定阈值的交易 |
| 3 | 异常日期 | 非工作日或未来日期的交易 |
| 4 | 分类异常 | 交易类别分布异常 |
| 5 | 高频交易 | 短时间内大量交易 |
| 6 | 凭证断号 | 凭证号不连续 |
| 7 | 余额异常 | 余额出现负值或突变 |

## License

MIT
