FROM python:3.12-slim

# Chromium runtime deps — browser-use drives Chromium over CDP.
RUN apt-get update && apt-get install -y --no-install-recommends \
    libnss3 libatk-bridge2.0-0 libxkbcommon0 libgbm1 libasound2 \
    fonts-liberation ca-certificates curl \
 && rm -rf /var/lib/apt/lists/*

# Non-root runtime user — owns the app dir, profile/artifact dirs, and
# the chromium cache it downloads.
RUN groupadd -r cortex && useradd -r -g cortex -m cortex

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /usr/local/bin/
WORKDIR /app

COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
COPY README.md ./
COPY alembic ./alembic
COPY alembic.ini ./

# Named docker volumes initialize ownership from these dirs — they must
# exist and be cortex-owned before mount.
RUN mkdir -p /app/profiles /app/artifacts \
 && uv sync --frozen --no-dev \
 && chown -R cortex:cortex /app

# Pre-bake Chromium — the installer escalates for system deps, so it must
# run as root; the binary cache is then moved into cortex's home.
RUN uv run browser-use install chromium \
 && cp -r /root/.cache /home/cortex/.cache \
 && chown -R cortex:cortex /home/cortex/.cache

USER cortex

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1
EXPOSE 8901
CMD ["uvicorn", "cortex.main:app", "--host", "0.0.0.0", "--port", "8901"]
