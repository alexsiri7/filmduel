#!/bin/sh
set -e

# Fail fast with a clear message if required env vars are absent.
for _var in DATABASE_URL SECRET_KEY; do
    eval "_val=\"\$$_var\""   # quote value to prevent word-splitting on metacharacters; safe: _var is a fixed list of known identifiers
    if [ -z "$_val" ]; then
        echo "ERROR: required env var $_var is not set — aborting"
        exit 1
    fi
done
unset _val _var

# Validate SECRET_KEY strength before entering Python (fast-fail with actionable message).
_sk_len="${#SECRET_KEY}"
if [ "$_sk_len" -lt 32 ]; then
    echo "ERROR: SECRET_KEY is too short ($_sk_len chars, minimum 32 required) — set a strong random secret in Railway > Variables tab"
    exit 1
fi
unset _sk_len

# Validate TOKEN_ENC_KEY is present when OAuth providers are configured.
if [ -n "$TRAKT_CLIENT_ID" ] || [ -n "$SIMKL_CLIENT_ID" ]; then
    if [ -z "$TOKEN_ENC_KEY" ]; then
        echo "ERROR: TOKEN_ENC_KEY must be set when TRAKT_CLIENT_ID or SIMKL_CLIENT_ID is configured — set a 32+ char random secret in Railway > Variables tab"
        exit 1
    fi
fi

# Emit key lengths to aid log-based diagnosis (values never printed).
echo "Env check: DATABASE_URL=${#DATABASE_URL}chars SECRET_KEY=${#SECRET_KEY}chars TOKEN_ENC_KEY=${#TOKEN_ENC_KEY}chars"

# Verify Python can import the app before backgrounding uvicorn.
# A failed import (missing wheel, wrong ABI, bad env var) would otherwise
# silently crash the background process and leave health checks failing.
echo "Verifying Python imports..."
python -c "from backend.main import app" 2>&1 || {
    echo "ERROR: failed to import backend.main — aborting (see traceback above)"
    exit 1
}
echo "Python imports: OK"

# Resolve trusted proxy IPs for --forwarded-allow-ips.
# Railway containers are not directly internet-accessible (all external traffic
# flows through Railway's proxy), so trusting '*' is safe on that platform.
# On other deployments the operator should set FORWARDED_ALLOW_IPS explicitly.
if [ -z "$FORWARDED_ALLOW_IPS" ]; then
    if [ -n "$RAILWAY_ENVIRONMENT" ]; then
        echo "WARNING: FORWARDED_ALLOW_IPS not set — detected Railway environment, auto-setting to '*' so X-Forwarded-For is trusted and rate limiting keys on real client IPs"
        FORWARDED_ALLOW_IPS="*"
    else
        echo "WARNING: FORWARDED_ALLOW_IPS not set — defaulting to 127.0.0.1 (loopback only). If running behind a reverse proxy, set FORWARDED_ALLOW_IPS to your proxy CIDR or rate limiting will key on proxy IP instead of client IP"
        FORWARDED_ALLOW_IPS="127.0.0.1"
    fi
fi

# Start uvicorn in background so Railway's health check passes during migrations.
uvicorn backend.main:app \
  --host 0.0.0.0 \
  --port "${PORT:-8080}" \
  --proxy-headers \
  --forwarded-allow-ips="$FORWARDED_ALLOW_IPS" &
UVICORN_PID=$!

trap 'kill "$UVICORN_PID" 2>/dev/null; wait "$UVICORN_PID" 2>/dev/null || true' TERM INT

# Wait for uvicorn to actually serve /health (up to 60 s).
# This is more reliable than kill -0, which only checks process existence.
_port="${PORT:-8080}"
_ready=0
for _i in $(seq 1 30); do
    if python -c "
import urllib.request, json, sys
try:
    r = urllib.request.urlopen('http://localhost:${_port}/health', timeout=2)
    d = json.loads(r.read())
    sys.exit(0 if d.get('status') == 'ok' else 1)
except Exception:
    sys.exit(1)
" 2>/dev/null; then
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
