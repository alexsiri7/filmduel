# Stage 1: Build frontend
FROM node:26-alpine@sha256:e88a35be04478413b7c71c455cd9865de9b9360e1f43456be5951032d7ac1a66 AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build && test -f dist/index.html

# Stage 2: Python backend + built frontend
FROM python:3.12-slim@sha256:2c941e860699f878900b0edc2403613c234d4b32eda3cc9fa7036991a2a63c4a
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
