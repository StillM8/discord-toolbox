FROM python:3.12-slim

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_PROJECT_ENVIRONMENT=/app/.venv

WORKDIR /app

RUN apt-get update \
    && apt-get install --no-install-recommends -y \
        ca-certificates \
        ffmpeg \
        fonts-noto-core \
        fonts-noto-color-emoji \
        libmagic1 \
        tesseract-ocr \
        tesseract-ocr-eng \
        tesseract-ocr-urd \
        tesseract-ocr-ara \
        tzdata \
    && rm -rf /var/lib/apt/lists/* \
    && pip install --no-cache-dir uv

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --extra openai --extra local-media --no-install-project

COPY alembic.ini PLAN.md AGENTS.md ./
COPY migrations ./migrations
COPY src ./src

RUN uv sync --frozen --no-dev --extra openai --extra local-media

RUN mkdir -p /data/assets /data/codex

VOLUME ["/data", "/data/assets", "/data/codex"]

CMD ["/app/.venv/bin/python", "-m", "toolbox.app.bootstrap"]
