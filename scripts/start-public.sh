#!/bin/bash
# 通过 AutoDL 自定义服务端口暴露公网（推荐 6006 或 6008）
set -euo pipefail
cd "$(dirname "$0")/.."

# AutoDL 实例默认映射 6006、6008 到公网 HTTPS 地址
if [ -n "${PUBLIC_PORT:-}" ]; then
  PORT="$PUBLIC_PORT"
elif [ -n "${AutoDLService6006URL:-}" ]; then
  PORT="${PORT:-6006}"
elif [ -n "${AutoDLService6008URL:-}" ]; then
  PORT="${PORT:-6008}"
else
  PORT="${PORT:-6006}"
fi
export PORT

PID_FILE="/tmp/audit-app-${PORT}.pid"
LOG_FILE="/tmp/audit-app-${PORT}.log"

if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
  echo "服务已在运行 (PID $(cat "$PID_FILE"), 端口 ${PORT})"
else
  if command -v fuser >/dev/null 2>&1; then
    fuser -k "${PORT}/tcp" 2>/dev/null || true
  fi
  nohup gunicorn \
    --bind "0.0.0.0:${PORT}" \
    --workers 1 \
    --worker-class gthread \
    --threads 16 \
    --keep-alive 5 \
    --timeout 300 \
    app:app >"$LOG_FILE" 2>&1 &
  echo $! >"$PID_FILE"
  sleep 3
fi

for i in 1 2 3 4 5; do
  if curl -sf "http://127.0.0.1:${PORT}/" >/dev/null; then
    break
  fi
  sleep 2
done

if ! curl -sf "http://127.0.0.1:${PORT}/" >/dev/null; then
  echo "启动失败，查看日志: $LOG_FILE"
  tail -20 "$LOG_FILE" || true
  exit 1
fi

echo "========================================"
echo " 财务大数据审计系统 - 公网已就绪"
echo "========================================"
echo " 本机: http://127.0.0.1:${PORT}"

if [ "$PORT" = "6006" ] && [ -n "${AutoDLService6006URL:-}" ]; then
  echo " 公网: ${AutoDLService6006URL}"
elif [ "$PORT" = "6008" ] && [ -n "${AutoDLService6008URL:-}" ]; then
  echo " 公网: ${AutoDLService6008URL}"
else
  echo " 公网: 请在 AutoDL 控制台「自定义服务」查看端口 ${PORT} 的映射地址"
fi

echo " 日志: $LOG_FILE"
echo " 停止: bash scripts/stop-public.sh"
echo "========================================"
