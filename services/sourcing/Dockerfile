# =============================================================================
# AHP Sourcing Engine — Multi-stage Dockerfile
# =============================================================================
# Stages:
#   1. base        — OS-level deps + Python packages
#   2. development — hot-reload via uvicorn --reload
#   3. production  — optimised, no reload
# =============================================================================

# ---------------------------------------------------------------------------
# Stage 1: Base — install Python dependencies
# ---------------------------------------------------------------------------
FROM python:3.12-slim AS base

# Prevent Python from writing .pyc files and enable unbuffered stdout/stderr
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1

WORKDIR /app

# Install system dependencies required by asyncpg and other native extensions
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        gcc \
        libpq-dev \
    && rm -rf /var/lib/apt/lists/*

# Copy only dependency metadata first for better Docker layer caching
COPY pyproject.toml ./

# Install project dependencies via pip (PEP 621)
RUN pip install --no-cache-dir --upgrade pip \
    && pip install --no-cache-dir .

# ---------------------------------------------------------------------------
# Stage 2: Development — hot-reload enabled
# ---------------------------------------------------------------------------
FROM base AS development

# Install dev dependencies as well
RUN pip install --no-cache-dir ".[dev]"

# Copy application source (overridden by volume mount in docker-compose)
COPY . .

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--reload"]

# ---------------------------------------------------------------------------
# Stage 3: Production — optimised, no reload
# ---------------------------------------------------------------------------
FROM base AS production

COPY . .

EXPOSE 8001

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8001", "--workers", "4"]
