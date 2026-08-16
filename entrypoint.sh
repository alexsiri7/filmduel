#!/bin/sh
set -e

# Start uvicorn immediately so Railway's health check (/health returns 200
# without querying the DB) passes while alembic migrations run concurrently.
# If alembic fails all retries, uvicorn is killed and the container exits 1,
# triggering Railway's ON_FAILURE restart policy.
uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8080}" \
  --proxy-headers \
  --forwarded-allow-ips="${FORWARDED_ALLOW_IPS:-127.0.0.1}" &  # see FORWARDED_ALLOW_IPS in .env.example
UVICORN_PID=$!

# Forward SIGTERM/SIGINT to uvicorn so it can drain in-flight requests
# gracefully on Railway redeploy (shell is PID 1, not uvicorn).
trap 'kill "$UVICORN_PID"' TERM INT

# Verify uvicorn actually started before proceeding with migrations.
sleep 1
if ! kill -0 "$UVICORN_PID" 2>/dev/null; then
    echo "uvicorn failed to start — aborting"
    exit 1
fi

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
