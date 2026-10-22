MANAGE = uv run app/manage.py

.PHONY: help install run scheduler css css-watch migrate makemigrations superuser test lint format docker-up docker-down docker-logs

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

superuser: ## Create an admin account
	$(MANAGE) createsuperuser

test: ## Run the test suite
	uv run pytest

lint: ## Check code style
	uv run ruff check .
	uv run ruff format --check .

format: ## Fix code style
	uv run ruff check --fix .
	uv run ruff format .

docker-up: ## Build and start the container
	docker compose up -d --build

docker-down: ## Stop the container
	docker compose down

docker-logs: ## Follow the container logs
	docker compose logs -f
