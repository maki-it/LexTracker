#!/bin/bash

set -e

# Trap signals for graceful shutdown
trap "echo 'Received SIGINT, exiting...'; exit 0" SIGINT
trap "echo 'Received SIGTERM, exiting...'; exit 0" SIGTERM

echo "Starting LexTracker..."

# Check if we're running the main application
if [[ "$1" == "uvicorn" ]]; then
    echo "Running database migrations..."
    python manage.py migrate --noinput

    echo "Collecting static files..."
    python manage.py collectstatic --noinput --clear

    # Create superuser from environment variables if specified
    if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ] && [ -n "$DJANGO_SUPERUSER_EMAIL" ]; then
        echo "Creating superuser..."
        python manage.py shell << END
from django.contrib.auth import get_user_model
User = get_user_model()
if not User.objects.filter(username='$DJANGO_SUPERUSER_USERNAME').exists():
    User.objects.create_superuser('$DJANGO_SUPERUSER_USERNAME', '$DJANGO_SUPERUSER_EMAIL', '$DJANGO_SUPERUSER_PASSWORD')
    print('Superuser created successfully!')
else:
    print('Superuser already exists.')
END
    fi

    echo "Starting uvicorn server..."
    exec "$@"
else
    # For any other command, just execute it
    exec "$@"
fi
