# One image everywhere: this is what runs on a laptop and what runs on Render.
FROM python:3.12-slim

# Fail fast and log straight through, so a broken boot shows up in the platform log
# instead of sitting in a buffer.
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

WORKDIR /app

# Dependencies first: the layer is cached until pyproject.toml itself changes, so an
# ordinary code change rebuilds in seconds. README.md is copied because the project
# metadata references it.
COPY pyproject.toml README.md ./
COPY app/__init__.py app/__init__.py
RUN pip install --no-cache-dir .

COPY app app

# Run as a non-root user. Nothing in the image needs to write to it.
RUN useradd --create-home --uid 10001 appuser && chown -R appuser:appuser /app
USER appuser

# Documentation only -- Render supplies $PORT and ignores EXPOSE.
EXPOSE 8000

# $PORT is set by the platform; 8000 is the local default. The shell form is deliberate:
# the variable has to be expanded at start time, not baked in at build time.
# Phase 3 prepends the idempotent seed to this command.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
