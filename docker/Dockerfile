# syntax=docker/dockerfile:1

FROM python:3.14-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /srv

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

COPY app ./app

# Build the stylesheet with the standalone Tailwind CLI and collect all static files.
# The secret is a throwaway value, only needed so the settings load.
RUN APP_ENVIRONMENT=production APP_SECRET_KEY=build-only APP_DATA_DIR=/tmp/data \
    sh -c "cd app && /srv/.venv/bin/python manage.py tailwind build \
      && /srv/.venv/bin/python manage.py collectstatic --noinput" \
    && rm -rf app/.django_tailwind_cli


FROM python:3.14-slim AS runtime

ARG VERSION=dev
LABEL org.opencontainers.image.title="LexTracker" \
      org.opencontainers.image.description="Zeiterfassung und Projektsteuerung mit Anbindung an Lexware Office" \
      org.opencontainers.image.source="https://github.com/maki-it/LexTracker" \
      org.opencontainers.image.version="${VERSION}"

RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data && chown app:app /data

ENV PATH="/srv/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENVIRONMENT=production \
    APP_DATA_DIR=/data \
    APP_WORKERS=1

WORKDIR /srv/app

COPY --from=build /srv/.venv /srv/.venv
COPY --from=build /srv/staticfiles /srv/staticfiles
COPY --from=build /srv/app /srv/app
COPY --chmod=755 docker/entrypoint.sh /entrypoint.sh

USER app
VOLUME ["/data"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=15s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/health/', timeout=4).status != 200)"]

ENTRYPOINT ["/entrypoint.sh"]
CMD ["serve"]
