APP_DIR=app

.PHONY: help
help: ## Show this help message
	@echo "Available commands:"
	@echo ""
	@echo "Development:"
	@echo "  make install          - Install dependencies using uv"
	@echo "  make run              - Run development server with uvicorn"
	@echo "  make migrate          - Run database migrations"
	@echo "  make makemigrations   - Create new migrations"
	@echo "  make tailwind-start   - Start Tailwind CSS in watch mode"
	@echo "  make tailwind-build   - Build Tailwind CSS for production"
	@echo "  make manage <cmd>     - Run Django management command"
	@echo ""
	@echo "Docker:"
	@echo "  make docker-build     - Build Docker image"
	@echo "  make docker-run       - Start application with docker compose"
	@echo "  make docker-stop      - Stop docker compose containers"
	@echo "  make docker-logs      - View container logs"
	@echo "  make docker-shell     - Open shell in running container"
	@echo "  make docker-rebuild   - Rebuild and restart containers"

.PHONY: install
install:
	@echo "🚀 Creating virtual environment using uv"
	@uv sync
#	@uv run pre-commit install

#.PHONY: check
#check: ## Run code quality tools.
#	@echo "🚀 Checking lock file consistency with 'pyproject.toml'"
#	@uv lock --locked
#	@echo "🚀 Linting code: Running pre-commit"
#	@uv run pre-commit run -a
#	@echo "🚀 Static type checking: Running mypy"
#	@uv run mypy
#	@echo "🚀 Checking for obsolete dependencies: Running deptry"
#	@uv run deptry .

.PHONY: venv
env venv: # Create a virtual environment if it doesn't exist
	@test -d .venv || uv venv
	@. .venv/bin/activate

.PHONY: run
run:
	@cd $(APP_DIR) && \
	uv run ./manage.py collectstatic --noinput && \
	uv run uvicorn lextracker.asgi:application --reload --timeout-graceful-shutdown 3

manage:
	@cd $(APP_DIR) && uv run ./manage.py $(filter-out $@,$(MAKECMDGOALS))

makemigrations:
	@cd $(APP_DIR) && uv run ./manage.py makemigrations

migrate:
	@cd $(APP_DIR) && uv run ./manage.py migrate

tailwind-start:
	@cd $(APP_DIR) && uv run ./manage.py tailwind start

tailwind-build:
	@cd $(APP_DIR) && uv run ./manage.py tailwind build

# Docker targets
.PHONY: docker-build
docker-build:
	@echo "🐳 Building Docker image..."
	@docker build -f docker/Dockerfile -t lextracker:latest \
		--build-arg VERSION=$$(git describe --tags --always 2>/dev/null || echo "dev") \
		--build-arg REVISION=$$(git rev-parse HEAD 2>/dev/null || echo "unknown") \
		--build-arg BUILDTIME=$$(date -u +'%Y-%m-%dT%H:%M:%SZ') \
		.

.PHONY: docker-run
docker-run:
	@echo "🐳 Running Docker container..."
	@docker compose up -d

.PHONY: docker-stop
docker-stop:
	@echo "🐳 Stopping Docker container..."
	@docker compose down

.PHONY: docker-logs
docker-logs:
	@docker compose logs -f

.PHONY: docker-shell
docker-shell:
	@docker exec -it lextracker /bin/bash

.PHONY: docker-rebuild
docker-rebuild:
	@echo "🐳 Rebuilding and restarting Docker container..."
	@docker compose up -d --build

# Workaround to pass arguments to manage command
# https://stackoverflow.com/a/6273809
%:
	@:
