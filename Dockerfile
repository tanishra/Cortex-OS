FROM python:3.12-slim

# Chromium runtime deps — browser-use drives Chromium over CDP.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk-bridge2.0-0 libxkbcommon0 libgbm1 libasound2 \
    fonts-liberation ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY README.md ./
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --frozen --no-dev

# Pre-bake Chromium into the image (~/.cache/puppeteer).
RUN uv run browser-use install chromium

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
EXPOSE 8901
CMD ["uvicorn", "cortex.main:app", "--host", "0.0.0.0", "--port", "8901"]
