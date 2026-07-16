# Docker 部署指南

## 1. 解压项目

```bash
tar -xzf financial-audit-system-docker.tar.gz -C financial-audit-system
cd financial-audit-system
```

## 2. 配置环境变量（可选）

```bash
cp .env.example .env
# 编辑 .env，填入 DEEPSEEK_API_KEY（AI 助手可选）
```

## 3. 构建并启动

```bash
bash scripts/build-image.sh
docker compose up -d
```

浏览器访问：**http://localhost:5000**

## 4. 环境测试

```bash
docker compose -f docker-compose.yml -f docker-compose.test.yml up --build --abort-on-container-exit
```

看到「全部测试通过」即表示环境正常。

## 5. 常用命令

```bash
docker compose logs -f          # 查看日志
docker compose down             # 停止服务
docker compose down -v          # 停止并删除数据卷（清空历史记录）
```

## 环境说明

详见 `config/env.yaml`
