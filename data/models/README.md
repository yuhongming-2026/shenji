# AI 配置目录（模型通过云端 API 接入，不存放本地权重）

## 需要的文件
- `inference_policy.json` — 导航/财务关键词快速旁路策略

## 配置 API
在项目根目录 `.env` 或「模型管理」页面填写：

```bash
BAILIAN_API_KEY=sk-xxx
# DEEPSEEK_API_KEY=
# OPENAI_API_KEY=
```

详见 `config/models.yaml`。
