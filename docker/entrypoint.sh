#!/bin/sh
set -e

if [ "$1" = "serve" ]; then
    python manage.py migrate --noinput

    # Optional first admin account, created only if it does not exist yet.
    if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
        python manage.py createsuperuser --noinput --email "${DJANGO_SUPERUSER_EMAIL:-}" 2>/dev/null \
            && echo "Admin account '$DJANGO_SUPERUSER_USERNAME' created." \
            || echo "Admin account '$DJANGO_SUPERUSER_USERNAME' already exists."
    fi

    exec uvicorn config.asgi:application \
        --host 0.0.0.0 --port 8000 \
        --workers "$APP_WORKERS" \
        --proxy-headers --forwarded-allow-ips="${APP_FORWARDED_ALLOW_IPS:-127.0.0.1}" \
        --lifespan off --no-server-header
fi

# Anything else, e.g. `docker compose exec app python manage.py shell`.
exec "$@"
