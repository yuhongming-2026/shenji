#!/bin/sh
set -e

mkdir -p /app/data /app/uploads
chown -R appuser:appuser /app/data /app/uploads
chmod -R u+rwX /app/data /app/uploads

exec su -s /bin/sh appuser -c "exec $*"
