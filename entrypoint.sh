#!/bin/sh
set -e

# Retry alembic with exponential backoff (capped) to handle transient DB
# connectivity failures (Railway starts the app container before the DB addon
# is ready). Previous 5-retry window (~155s) was insufficient when the DB
# takes longer to become available; increase to 15 retries with a 60s cap,
# giving up to ~675s (5+10+20+40+60×10 ≈ 11 min) — well within healthcheckTimeout=900.
RETRIES=15
MAX_WAIT=60
WAIT=5
for i in $(seq 1 $RETRIES); do
    echo "alembic upgrade head: attempt $i/$RETRIES"
    alembic upgrade head && break
    if [ "$i" -eq "$RETRIES" ]; then
        echo "alembic upgrade head failed after $RETRIES attempts — aborting"
        exit 1
    fi
    echo "alembic upgrade head failed; retrying in ${WAIT}s..."
    sleep "$WAIT"
    WAIT=$(( WAIT * 2 > MAX_WAIT ? MAX_WAIT : WAIT * 2 ))
done

exec uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8080}" \
  --proxy-headers \
  --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"  # see FORWARDED_ALLOW_IPS in .env.example
