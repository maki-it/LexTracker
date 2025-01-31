#!/bin/bash

set -e

# trap "echo Exiting...; exit 0" EXIT TERM
trap "exit" SIGINT
trap "exit" SIGTERM

if [[ "$*" == "python main.py" ]]; then

    # Apply any pending database migrations
    alembic upgrade head

    exec "$@"
else
    exec "$@"
fi
