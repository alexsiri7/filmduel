# Stage 1: Build frontend
FROM node:26-alpine@sha256:aadf416b2cdce311a8811ba3f0608a61b77dbf997500e2eafe781b51f6a0b019 AS frontend-build
WORKDIR /app/frontend
COPY frontend/package.json frontend/package-lock.json* ./
RUN npm ci
COPY frontend/ ./
RUN npm run build && test -f dist/index.html

# Stage 2: Python backend + built frontend
FROM python:3.14-slim@sha256:cad9a2c871761c413caa6fdd6441c783451e740a48aaeba60ae62a8b53525ef6
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
