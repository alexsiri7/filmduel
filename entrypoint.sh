#!/bin/sh
set -e

# Fail fast with a clear message if required env vars are absent.
for _var in DATABASE_URL SECRET_KEY; do
    eval _val=\$$_var
    if [ -z "$_val" ]; then
        echo "ERROR: required env var $_var is not set — aborting"
        exit 1
    fi
done

# Verify Python can import the app before backgrounding uvicorn.
# A failed import (missing wheel, wrong ABI, bad env var) would otherwise
# silently crash the background process and leave health checks failing.
echo "Verifying Python imports..."
python -c "from backend.main import app" 2>&1 || {
    echo "ERROR: failed to import backend.main — aborting (see traceback above)"
    exit 1
}
echo "Python imports: OK"

# Start uvicorn in background so Railway's health check passes during migrations.
uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8080}" \
  --proxy-headers \
  --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}" &
UVICORN_PID=$!

trap 'kill "$UVICORN_PID" 2>/dev/null; wait "$UVICORN_PID" 2>/dev/null || true' TERM INT

# Wait for uvicorn to actually serve /health (up to 60 s).
# This is more reliable than kill -0, which only checks process existence.
_port="${PORT:-8080}"
_ready=0
for _i in $(seq 1 30); do
    if curl -sf --max-time 2 "http://localhost:${_port}/health" 2>/dev/null \
        | grep -q '"status":"ok"'; then
        _ready=1
        break
    fi
    if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
        echo "uvicorn crashed during startup — aborting"
        exit 1
    fi
    sleep 2
done
if [ "$_ready" -eq 0 ]; then
    echo "uvicorn failed to become ready within 60 s — aborting"
    kill "$UVICORN_PID" 2>/dev/null || true
    exit 1
fi
echo "uvicorn ready"

# Retry alembic with exponential backoff (capped) to handle transient DB
# connectivity failures (Railway starts the app container before the DB addon
# is ready). 15 retries with a 60s cap gives ~675s sleep + ~450s connection
# timeouts ≈ 20 min total — safely within any retry window since uvicorn is
# already serving health checks.
RETRIES=15
MAX_WAIT=60
WAIT=5
for i in $(seq 1 $RETRIES); do
    echo "alembic upgrade head: attempt $i/$RETRIES"
    if alembic upgrade head; then
        break
    fi
    if [ "$i" -eq "$RETRIES" ]; then
        echo "alembic upgrade head failed after $RETRIES attempts — aborting"
        kill "$UVICORN_PID" 2>/dev/null || true
        wait "$UVICORN_PID" || true
        exit 1
    fi
    echo "alembic upgrade head failed; retrying in ${WAIT}s..."
    sleep "$WAIT"
    WAIT=$(( WAIT * 2 > MAX_WAIT ? MAX_WAIT : WAIT * 2 ))
done

echo "alembic upgrade head succeeded — migrations complete"

# Wait for uvicorn to exit (blocks until the process stops or is signalled)
wait "$UVICORN_PID"
UVICORN_EXIT=$?
if [ "$UVICORN_EXIT" -ne 0 ]; then
    echo "uvicorn exited with code $UVICORN_EXIT"
fi
exit "$UVICORN_EXIT"
