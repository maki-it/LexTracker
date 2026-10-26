#!/bin/sh
# Prepares the database before the web server starts, then hands over to the given command.
# Runs only for uvicorn, so the scheduler and one-off commands (e.g. manage.py shell) start right away.
set -eu

if [ "${1:-}" = "uvicorn" ]; then
    python manage.py migrate --noinput
    python manage.py ensure_superuser
fi

exec "$@"
