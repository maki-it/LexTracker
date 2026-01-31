# Docker Setup for LexTracker

This directory contains the Docker configuration for running LexTracker in a containerized environment.

## Quick Start

### Using Docker Compose (Recommended)

1. **Set environment variables** (create a `.env` file in the project root):
```bash
APP_SECRET_KEY=your-secret-key-here
APP_DOMAIN=http://localhost:8000
APP_ALLOWED_HOSTS=localhost,127.0.0.1
TZ=Europe/Berlin
```

2. **Build and run**:
```bash
docker-compose up -d
```

3. **Access the application**:
Open your browser at http://localhost:8000

4. **View logs**:
```bash
docker-compose logs -f
```

5. **Stop the application**:
```bash
docker-compose down
```

### Using Docker directly

1. **Build the image**:
```bash
docker build -f docker/Dockerfile -t lextracker:latest .
```

2. **Run the container**:
```bash
docker run -d \
  --name lextracker \
  -p 8000:8000 \
  -e APP_SECRET_KEY=your-secret-key \
  -e APP_DOMAIN=http://localhost:8000 \
  -e APP_ALLOWED_HOSTS=localhost,127.0.0.1 \
  -v $(pwd)/data/db.sqlite3:/app/app/db.sqlite3 \
  lextracker:latest
```

## Dockerfile Architecture

The Dockerfile uses a multi-stage build approach:

1. **Base Stage**: Sets up Python 3.13 with common environment variables
2. **Frontend Builder Stage**: Installs Node.js and builds Tailwind CSS assets
3. **Python Dependencies Stage**: Uses `uv` to install Python dependencies
4. **Runtime Stage**: Combines everything into a minimal production image

### Key Features

- **Multi-stage build** for optimal image size
- **Non-root user** (appuser) for security
- **Health checks** for container orchestration
- **Static asset compilation** during build
- **Database migrations** run automatically on startup
- **Automatic superuser creation** from environment variables
- **Graceful shutdown** handling

## Environment Variables

| Variable | Description | Default               | Required |
|----------|-------------|-----------------------|----------|
| `APP_SECRET_KEY` | Django secret key | -                     | Yes |
| `APP_DOMAIN` | Application domain URL | http://localhost:8000 | Yes |
| `APP_ENVIRONMENT` | Environment mode (development/production) | production            | No |
| `APP_LOGLEVEL` | Log level (debug/info/warning/error) | info                  | No |
| `TZ` | Timezone | UTC                   | No |
| `LEXOFFICE_API_TOKEN` | Lexoffice API authentication token | -                     | Yes |
| `DJANGO_SUPERUSER_USERNAME` | Admin username (auto-create on startup) | -                     | No |
| `DJANGO_SUPERUSER_PASSWORD` | Admin password (auto-create on startup) | -                     | No |
| `DJANGO_SUPERUSER_EMAIL` | Admin email (auto-create on startup) | -                     | No |
| `TZ` | Timezone | UTC                   |

## Volume Mounts

- `/app/app/db.sqlite3` - SQLite database file
- `/app/app/staticfiles` - Collected static files (optional)

## Exposed Ports

- `8000` - HTTP server (uvicorn)

## Entrypoint Script

The `docker-entrypoint.sh` script automatically:
1. Runs Django database migrations
2. Collects static files
3. Creates a superuser (if `DJANGO_SUPERUSER_*` variables are set)
4. Starts the uvicorn server

### Automatic Superuser Creation

To automatically create a superuser when the container starts, set these environment variables in your `.env` file:

```bash
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=your-secure-password
DJANGO_SUPERUSER_EMAIL=admin@example.com
```

The superuser will only be created if it doesn't already exist, so it's safe to keep these variables set even after the first run.

**Note:** For production deployments, consider using Docker secrets or a secrets management system instead of plain environment variables for sensitive data.

You can override the default command to run other Django management commands:

```bash
# Manually create a superuser (if not using auto-creation)
docker run -it --rm lextracker:latest python manage.py createsuperuser

# Run shell
docker run -it --rm lextracker:latest python manage.py shell

# Run custom command
docker run -it --rm lextracker:latest python manage.py <command>
```

## Building for Production

For production builds, consider:

1. **Using build arguments**:
```bash
docker build -f docker/Dockerfile \
  --build-arg VERSION=1.0.0 \
  --build-arg REVISION=$(git rev-parse HEAD) \
  --build-arg BUILDTIME=$(date -u +'%Y-%m-%dT%H:%M:%SZ') \
  -t lextracker:1.0.0 \
  .
```

2. **Using a proper database** (PostgreSQL instead of SQLite):
   - Update `DATABASES` in Django settings
   - Add PostgreSQL service to docker-compose.yml
   - Add `psycopg[binary]` to dependencies

3. **Using environment-specific configurations**:
   - Mount secrets from Docker secrets or environment
   - Use a reverse proxy (nginx) for serving static files
   - Configure proper logging and monitoring

## Troubleshooting

### Container fails to start

Check the logs:
```bash
docker logs lextracker
```

### Permission issues with volumes

Ensure the mounted directories are writable:
```bash
mkdir -p data
chmod 755 data
```

### Static files not loading

Rebuild the container to regenerate static files:
```bash
docker compose up -d --build
```

### Database migrations fail

Run migrations manually:
```bash
docker exec lextracker python manage.py migrate
```

## Development

For development, it's recommended to use the local development environment instead of Docker:

```bash
make install  # Install dependencies
make run      # Run development server
```

However, if you want to test the Docker build locally:

```bash
docker build -f docker/Dockerfile -t lextracker:dev .
docker run -p 8000:8000 -e APP_ENVIRONMENT=development lextracker:dev
```
