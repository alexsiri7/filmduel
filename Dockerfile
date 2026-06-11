# Stage 1: Build frontend
FROM node:26-alpine@sha256:3ad34ca6292aec4a91d8ddeb9229e29d9c2f689efd0dd242860889ac71842eba AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build && test -f dist/index.html

# Stage 2: Python backend + built frontend
FROM python:3.12-slim@sha256:401f6e1a67dad31a1bd78e9ad22d0ee0a3b52154e6bd30e90be696bb6a3d7461
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
