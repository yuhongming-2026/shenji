#!/bin/bash
# Ubuntu/Debian Docker 安装脚本
set -euo pipefail

if command -v docker >/dev/null 2>&1; then
  echo "Docker 已安装: $(docker --version)"
  exit 0
fi

echo "正在安装 Docker..."
apt-get update -qq
apt-get install -y docker.io docker-compose-v2

mkdir -p /etc/docker
if [ ! -f /etc/docker/daemon.json ]; then
  cat > /etc/docker/daemon.json << 'EOF'
{
  "registry-mirrors": [
    "https://docker.m.daocloud.io",
    "https://hub-mirror.c.163.com"
  ]
}
EOF
fi

if command -v systemctl >/dev/null 2>&1; then
  systemctl enable --now docker
else
  dockerd >/var/log/dockerd.log 2>&1 &
  sleep 3
fi

docker --version
docker compose version
echo "Docker 安装完成"
