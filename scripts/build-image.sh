#!/bin/bash
# 构建财务审计系统 Docker 镜像
set -euo pipefail

cd "$(dirname "$0")/.."
IMAGE_NAME="${IMAGE_NAME:-financial-audit-system:latest}"

echo "=========================================="
echo " 构建镜像: $IMAGE_NAME"
echo "=========================================="

if ! docker info >/dev/null 2>&1; then
  echo "错误: Docker 守护进程未运行"
  echo "请先执行: sudo systemctl start docker"
  echo "或运行: bash scripts/install-docker.sh"
  exit 1
fi

echo "[1/2] docker compose build ..."
docker compose build

echo "[2/2] 确认镜像 ..."
docker images "$IMAGE_NAME"

echo ""
echo "构建完成！启动命令:"
echo "  docker compose up -d"
echo "  访问 http://localhost:5000"
echo ""
echo "环境测试:"
echo "  docker compose -f docker-compose.yml -f docker-compose.test.yml up --build --abort-on-container-exit"
