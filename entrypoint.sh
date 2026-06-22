#!/bin/sh
set -e
alembic upgrade head
exec uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8080}" \
  --proxy-headers \
  --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"  # see FORWARDED_ALLOW_IPS in .env.example
