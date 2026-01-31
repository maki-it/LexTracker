# Multi-stage build for LexTracker Django application
FROM python:3.13-slim as base

# Set environment variables
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    UV_SYSTEM_PYTHON=1

WORKDIR /app

####################
# Build stage - Install Node.js and build frontend assets
####################
FROM base AS frontend-builder

# Install Node.js
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    curl \
    ca-certificates && \
    curl -fsSL https://deb.nodesource.com/setup_20.x | bash - && \
    apt-get install -y nodejs && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy frontend source files
COPY app/frontend/static_src/package*.json /app/frontend/static_src/
COPY app/frontend/static_src/ /app/frontend/static_src/

# Install npm dependencies and build Tailwind CSS
WORKDIR /app/frontend/static_src
RUN npm ci && \
    npm run build

####################
# Python dependencies stage
####################
FROM base AS python-deps

# Install uv and git (needed for git dependencies)
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

RUN apt-get update && \
    apt-get install -y --no-install-recommends git && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Copy dependency files
COPY pyproject.toml uv.lock ./

# Install Python dependencies
RUN uv sync --frozen --no-dev --no-install-project

####################
# Final runtime stage
####################
FROM base AS runtime

ARG VERSION=dev
ARG BUILDTIME=""
ARG REVISION=""

LABEL org.opencontainers.image.title="LexTracker" \
      org.opencontainers.image.description="Project time tracker for Lexoffice / Lexware Office" \
      org.opencontainers.image.version="${VERSION}"

# Install runtime dependencies
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
    libpq5 \
    && apt-get clean && \
    rm -rf /var/lib/apt/lists/*

# Create non-root user
RUN useradd -m -u 1000 appuser && \
    chown -R appuser:appuser /app

# Copy Python virtual environment from python-deps stage
COPY --from=python-deps --chown=appuser:appuser /app/.venv /app/.venv

# Copy built frontend assets from frontend-builder stage
COPY --from=frontend-builder --chown=appuser:appuser /app/frontend/static/css/dist /app/app/frontend/static/css/dist

# Copy application code
COPY --chown=appuser:appuser app/ /app/app/
COPY --chown=appuser:appuser docker/docker-entrypoint.sh /app/

# Create data and staticfiles directories with proper permissions
RUN mkdir -p /app/app/data /app/app/staticfiles && \
    chown -R appuser:appuser /app/app/data /app/app/staticfiles && \
    chmod +x /app/docker-entrypoint.sh

# Set environment variables
ENV PATH="/app/.venv/bin:$PATH" \
    APP_ENVIRONMENT=production \
    APP_LOGLEVEL=info \
    DJANGO_SETTINGS_MODULE=lextracker.settings

WORKDIR /app/app

USER appuser

EXPOSE 8000

ENTRYPOINT ["/app/docker-entrypoint.sh"]
CMD ["uvicorn", "lextracker.asgi:application", "--host", "0.0.0.0", "--port", "8000"]

HEALTHCHECK --interval=30s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import socket; s=socket.socket(); s.settimeout(3); s.connect(('127.0.0.1', 8000)); s.close()" || exit 1

STOPSIGNAL SIGTERM
