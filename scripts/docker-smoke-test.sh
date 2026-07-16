#!/bin/sh
# Docker 环境冒烟测试脚本
set -eu

BASE_URL="${BASE_URL:-http://audit-app:5000}"

echo "========================================"
echo " 财务审计系统 Docker 环境测试"
echo " 目标: $BASE_URL"
echo "========================================"

echo "[1/4] 首页可达性..."
curl -sf "$BASE_URL/" > /dev/null
echo "  OK"

echo "[2/5] 历史记录 API..."
curl -sf "$BASE_URL/api/history" | grep -q '"success"'
echo "  OK"

echo "[3/5] CSV 文件上传与审计分析..."
RESP=$(curl -sf -X POST -F "files=@/samples/demo.csv" "$BASE_URL/api/upload")
echo "$RESP" | grep -q '"success": true'
echo "$RESP" | grep -q '"audit_summary"'
echo "$RESP" | grep -q '"history_id"'
echo "  OK"

echo "[4/5] 历史记录加载..."
HID=$(echo "$RESP" | sed -n 's/.*"history_id": *\([0-9][0-9]*\).*/\1/p' | head -1)
test -n "$HID"
curl -sf -X POST "$BASE_URL/api/history/$HID/load" | grep -q '"success": true'
echo "  OK (id=$HID)"

echo "[5/5] 仪表盘数据 API..."
curl -sf "$BASE_URL/api/dashboard" | grep -q '"success": true'
echo "  OK"

echo "========================================"
echo " 全部测试通过"
echo "========================================"
