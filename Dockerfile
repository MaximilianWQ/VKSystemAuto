# --- сборка фронтенда -------------------------------------------------------
FROM node:22-slim AS web

WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci --no-audit --no-fund 2>/dev/null || npm install --no-audit --no-fund

COPY web/ ./
RUN npm run build

# --- рантайм ----------------------------------------------------------------
FROM python:3.12-slim

# tzdata нужна для zoneinfo: без неё ZoneInfo("Europe/Moscow") падает,
# и рабочие часы считаются неверно.
RUN apt-get update && apt-get install -y --no-install-recommends tzdata \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev

COPY app ./app
COPY --from=web /web/dist ./web/dist

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

# Railway передаёт порт через $PORT, захардкоженный порт работать не будет.
CMD ["sh", "-c", "uvicorn app.main:build_from_env --factory --host 0.0.0.0 --port ${PORT:-8000}"]
