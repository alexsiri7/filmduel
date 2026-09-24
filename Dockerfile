# Stage 1: Build frontend
# Node major must match node-version in .github/workflows/ci.yml (guarded by backend/tests/test_runtime_versions.py).
FROM node:26-alpine@sha256:dbaa92e5758cbbcf85d65d5403fdb530fe3442cbe8c6dbfb7ef23365450d5070 AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build && test -f dist/index.html

# Stage 2: Python backend + built frontend
# Python major.minor must match python-version in .github/workflows/ci.yml and --python-version in backend/requirements*.txt (guarded by backend/tests/test_runtime_versions.py).
FROM python:3.14-slim@sha256:caaf356f40667c496d405780745b9ac25771c189a51dfcc42430d531ea09f8a2
WORKDIR /app

COPY backend/requirements.txt ./
RUN pip install --no-cache-dir --require-hashes -r requirements.txt

RUN useradd --create-home --shell /usr/sbin/nologin appuser  # Debian path; Alpine uses /sbin/nologin

COPY alembic.ini ./
COPY backend/ ./backend/
COPY --from=frontend-build /app/frontend/dist ./frontend/dist
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER appuser

EXPOSE ${PORT:-8080}
ENTRYPOINT ["/entrypoint.sh"]
