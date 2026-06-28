# ─────────────────────────────────────────────────────────────────────
# PROMPTVAULT DOCKERFILE
#
# SKILL: Multi-stage awareness, layer caching, production best practices
#
# Base image: python:3.11-slim
#   - "slim" = minimal Debian image with Python
#   - Much smaller than python:3.11 (full)
#   - 125MB vs 900MB — matters for deployment speed and storage
#
# We use a single-stage build here (appropriate for a portfolio project).
# In production you would use multi-stage builds to separate
# build dependencies from runtime dependencies.
# ─────────────────────────────────────────────────────────────────────
FROM python:3.11-slim

# ─────────────────────────────────────────────────────────────────────
# ENVIRONMENT VARIABLES
#
# PYTHONDONTWRITEBYTECODE=1
#   Prevents Python from writing .pyc files to disk inside the container.
#   We don't need them — they just waste space.
#
# PYTHONUNBUFFERED=1
#   Prevents Python from buffering stdout/stderr.
#   Without this, your logs appear with a delay or not at all
#   in Docker's logging system. Always set this in containers.
# ─────────────────────────────────────────────────────────────────────
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1

# ─────────────────────────────────────────────────────────────────────
# SYSTEM DEPENDENCIES
#
# libpq-dev  → PostgreSQL client library (needed by psycopg2)
# gcc        → C compiler (needed by some Python packages)
# --no-install-recommends → don't install optional packages (smaller image)
# rm -rf /var/lib/apt/lists/* → clean apt cache after install (smaller image)
# ─────────────────────────────────────────────────────────────────────
RUN apt-get update \
    && apt-get install -y --no-install-recommends \
        libpq-dev \
        gcc \
    && rm -rf /var/lib/apt/lists/*

# ─────────────────────────────────────────────────────────────────────
# WORKING DIRECTORY
# All subsequent commands run from this directory inside the container.
# ─────────────────────────────────────────────────────────────────────
WORKDIR /app

# ─────────────────────────────────────────────────────────────────────
# DEPENDENCY INSTALLATION
#
# CRITICAL LAYER CACHING TRICK:
# We copy requirements.txt FIRST, install dependencies, THEN copy code.
#
# Why: Docker caches each layer. If we copied all code first,
# then installed dependencies, EVERY code change would invalidate
# the pip install layer and force a full reinstall (3-5 minutes).
#
# By copying requirements.txt first:
# - If only your code changed → pip layer is cached, rebuild is fast
# - If requirements.txt changed → pip layer rebuilds (expected)
#
# This is the most important Dockerfile optimization and shows
# you understand how Docker layer caching works.
# ─────────────────────────────────────────────────────────────────────
COPY requirements.docker.txt .
RUN pip install --no-cache-dir -r requirements.docker.txt

# ─────────────────────────────────────────────────────────────────────
# APPLICATION CODE
# Copy everything else AFTER dependencies are installed.
# ─────────────────────────────────────────────────────────────────────
COPY . .

# ─────────────────────────────────────────────────────────────────────
# PORT EXPOSURE
# Tells Docker that this container listens on port 8000.
# This is documentation — actual port mapping is in docker-compose.yml.
# ─────────────────────────────────────────────────────────────────────
EXPOSE 8000

# ─────────────────────────────────────────────────────────────────────
# DEFAULT COMMAND
# What runs when this container starts.
# Can be overridden in docker-compose.yml (we do this for Celery worker).
#
# --host 0.0.0.0 → listen on all interfaces (required in containers)
# --port 8000    → the port inside the container
# --workers 1    → single worker for development
# No --reload    → reload is for development only, not containers
# ─────────────────────────────────────────────────────────────────────
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]