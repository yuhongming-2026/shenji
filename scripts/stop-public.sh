#!/bin/bash
set -euo pipefail

for port in 6006 6008 5000; do
  pid_file="/tmp/audit-app-${port}.pid"
  if [ -f "$pid_file" ]; then
    pid=$(cat "$pid_file")
    if kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      echo "已停止端口 ${port} 上的服务 (PID ${pid})"
    fi
    rm -f "$pid_file"
  fi
  pkill -f "gunicorn.*0.0.0.0:${port}" 2>/dev/null || true
  pkill -f "python3 app.py" 2>/dev/null || true
done

if command -v fuser >/dev/null 2>&1; then
  for port in 6006 6008 5000; do
    fuser -k "${port}/tcp" 2>/dev/null || true
  done
fi

echo "完成"
