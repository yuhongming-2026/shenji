# 扩展开发指南

在此目录开发 **Skill**、**MCP**、**小程序**、**工作流**、**Agent**，无需修改核心代码。

## 目录结构

```
extensions/
  skills/          # 可调用技能（Python handler）
  mcp/             # MCP 服务配置（HTTP JSON-RPC）
  miniprograms/    # 办公小程序 manifest
  workflows/       # 自动化工作流（YAML）
  agents/          # Agent 预设
```

## 1. 开发 Skill

1. 创建 `extensions/skills/my_skill/skill.json`
2. 可选：创建 `handler.py` 并实现 `run(args, context)`

```json
{
  "id": "my_skill",
  "name": "我的技能",
  "description": "技能说明",
  "parameters": { "type": "object", "properties": {} },
  "handler": "extensions/skills/my_skill/handler.py:run"
}
```

## 2. 接入 MCP

在 `extensions/mcp/` 添加 JSON，配置 `url` 指向 MCP HTTP 端点：

```json
{
  "id": "my_mcp",
  "name": "我的 MCP",
  "url": "http://localhost:3001/mcp",
  "tools": []
}
```

## 3. 小程序

`extensions/miniprograms/*.json` — 定义入口页、图标、推荐提示词。

## 4. 工作流

`extensions/workflows/*.yaml`：

```yaml
id: my_flow
name: 我的工作流
steps:
  - type: skill
    skill: audit_helper
  - type: agent
    prompt: 根据上一步结果写总结
```

## 5. Agent 预设

`extensions/agents/*.json` — 配置默认模型、系统提示、可用工具。

## 6. 模型配置

编辑 `config/models.yaml` 添加任意 OpenAI 兼容模型，设置环境变量 API Key。

## 7. 热重载

调用 API：`POST /api/agent/extensions/reload`

或在 Agent 工作台点击「重新扫描扩展」。
