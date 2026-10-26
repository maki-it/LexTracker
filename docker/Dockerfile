# syntax=docker/dockerfile:1

FROM python:3.15-slim AS build

COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_PYTHON_DOWNLOADS=never

WORKDIR /srv

COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# gettext compiles the translations (.po to .mo). It stays in this stage, the runtime image does not need it.
RUN --mount=type=cache,target=/var/cache/apt,sharing=locked \
    --mount=type=cache,target=/var/lib/apt,sharing=locked \
    rm -f /etc/apt/apt.conf.d/docker-clean \
    && apt-get update \
    && apt-get install -y --no-install-recommends gettext

COPY app ./app

# Compile the translations, build the stylesheet with the standalone Tailwind CLI and collect all static files.
# The CLI binary lands in a cache mount, so it is downloaded once per Tailwind version
# instead of on every code change, and never ends up in the image.
# The secret is a throwaway value, only needed so the settings load.
RUN --mount=type=cache,target=/srv/app/.django_tailwind_cli \
    APP_ENVIRONMENT=production APP_SECRET_KEY=build-only APP_DATA_DIR=/tmp/data \
    sh -c "cd app && /srv/.venv/bin/python manage.py compilemessages \
      && /srv/.venv/bin/python manage.py tailwind build \
      && /srv/.venv/bin/python manage.py collectstatic --noinput"


FROM python:3.15-slim AS runtime

RUN useradd --uid 1000 --create-home --shell /usr/sbin/nologin app \
    && mkdir -p /data /backups && chown app:app /data /backups

ENV PATH="/srv/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    APP_ENVIRONMENT=production \
    APP_DATA_DIR=/data \
    APP_BACKUP_DIR=/backups \
    UVICORN_WORKERS=1 \
    FORWARDED_ALLOW_IPS=127.0.0.1

WORKDIR /srv/app

# --link keeps these layers independent of the ones above, so a new base image or a code
# change does not force the other layers to be rebuilt or re-pushed.
COPY --link --from=build /srv/.venv /srv/.venv
COPY --link --from=build /srv/staticfiles /srv/staticfiles
COPY --link --from=build /srv/app /srv/app

# Declared late so a new version only changes the metadata, not any cached layer above.
ARG VERSION=dev
LABEL org.opencontainers.image.title="LexTracker" \
      org.opencontainers.image.description="Zeiterfassung und Projektsteuerung mit Anbindung an Lexware Office" \
      org.opencontainers.image.source="https://github.com/maki-it/LexTracker" \
      org.opencontainers.image.version="${VERSION}"

COPY --chmod=755 docker/entrypoint.sh /usr/local/bin/entrypoint.sh

USER app
VOLUME ["/data", "/backups"]
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=5s --start-period=60s --retries=3 \
    CMD ["python", "-c", "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/health/', timeout=4).status != 200)"]

# The entrypoint runs the migrations and creates the admin account before uvicorn starts (see
# docker/entrypoint.sh). The start period above leaves room for it. Worker count and trusted
# proxy IPs come from UVICORN_WORKERS and FORWARDED_ALLOW_IPS.
ENTRYPOINT ["/usr/local/bin/entrypoint.sh"]
CMD ["uvicorn", "config.asgi:application", "--host", "0.0.0.0", "--port", "8000", \
     "--proxy-headers", "--lifespan", "off", "--no-server-header"]
