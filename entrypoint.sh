#!/bin/sh
set -e
alembic upgrade head
exec uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8080}" \
  --proxy-headers \
  --forwarded-allow-ips='*'  # Trusts Railway's reverse proxy; assumes container is not directly internet-reachable
