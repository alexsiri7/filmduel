#!/bin/sh
set -e

# Retry alembic with exponential backoff to handle transient DB connectivity
# failures (e.g. Railway starting the app container before the DB is ready).
# 5 attempts, 4 waits of (5+10+20+40)s = 75s max — well within healthcheckTimeout=900.
RETRIES=5
WAIT=5
i=1
while [ "$i" -le "$RETRIES" ]; do
    echo "alembic upgrade head: attempt $i/$RETRIES"
    alembic upgrade head && break  # success → break; failure suppressed by set -e (compound list)
    if [ "$i" -eq "$RETRIES" ]; then
        echo "alembic upgrade head failed after $RETRIES attempts — aborting"
        exit 1
    fi
    echo "alembic upgrade head failed; retrying in ${WAIT}s..."
    sleep "$WAIT"
    WAIT=$((WAIT * 2))
    i=$((i + 1))
done

exec uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8080}" \
  --proxy-headers \
  --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}"  # see FORWARDED_ALLOW_IPS in .env.example
