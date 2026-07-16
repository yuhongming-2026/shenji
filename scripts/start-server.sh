#!/bin/bash
# 启动财务审计系统（绑定 0.0.0.0，可供外网访问）
set -euo pipefail
cd "$(dirname "$0")/.."

PORT="${PORT:-5000}"
export PORT

echo "========================================"
echo " 财务大数据审计系统"
echo " 监听: 0.0.0.0:${PORT}"
echo " 本机访问: http://127.0.0.1:${PORT}"
echo ""
echo " AutoDL 外网分享:"
echo "  在控制台「自定义服务」中添加端口 ${PORT}"
echo "========================================"

exec python3 app.py
