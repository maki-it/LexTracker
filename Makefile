MANAGE = uv run app/manage.py

.PHONY: help install run scheduler css css-watch migrate makemigrations messages superuser test lint format backup loadtest loadtest-ui docker-dev docker-dev-down docker-up docker-down docker-logs docker-backup

help: ## Show available commands
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*## "}; {printf "  %-16s %s\n", $$1, $$2}'

install: ## Install dependencies and create .env if missing
	uv sync
	@test -f .env || cp .env.example .env

run: ## Start the dev server (uvicorn, auto-reload)
	cd app && uv run uvicorn config.asgi:application --reload --port 8000

scheduler: ## Run recurring jobs such as the automatic customer import
	$(MANAGE) run_scheduler

css: ## Build the Tailwind stylesheet once
	$(MANAGE) tailwind build

css-watch: ## Rebuild the Tailwind stylesheet on template changes
	$(MANAGE) tailwind watch

migrate: ## Apply database migrations
	$(MANAGE) migrate

makemigrations: ## Create migrations for model changes
	$(MANAGE) makemigrations

messages: ## Update the English translation (app/locale) and compile it
	cd app && uv run manage.py makemessages -l en --no-location --no-obsolete -i static -e html,txt,py
	cd app && uv run manage.py compilemessages

superuser: ## Create an admin account
	$(MANAGE) createsuperuser

backup: ## Copy the database into the backup folder
	$(MANAGE) backup_database

test: ## Run the test suite
	uv run pytest

lint: ## Check code style
	uv run ruff check .
	uv run ruff format --check .

format: ## Fix code style
	uv run ruff check --fix .
	uv run ruff format .

loadtest: ## Run the load test against http://localhost:8000 (see loadtest/README.md)
	loadtest/run.sh

loadtest-ui: ## Start the load test web UI on http://127.0.0.1:8089 (see loadtest/README.md)
	uv run --with locust locust -f loadtest/locustfile.py --web-host 127.0.0.1 -H http://localhost:8000

docker-dev: ## Run in Docker with code sync and reload (dev.compose.yaml)
	docker compose -f dev.compose.yaml watch

docker-dev-down: ## Stop the Docker dev environment
	docker compose -f dev.compose.yaml down

docker-up: ## Pull the published image and start the container
	docker compose pull
	docker compose up -d

docker-down: ## Stop the container
	docker compose down

docker-logs: ## Follow the container logs
	docker compose logs -f

docker-backup: ## Make a database backup in the running container
	docker compose exec scheduler python manage.py backup_database
