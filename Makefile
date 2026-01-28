APP_DIR=app

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
	./manage.py collectstatic --noinput && \
	uvicorn lextracker.asgi:application --reload

manage:
	@cd $(APP_DIR) && ./manage.py $(filter-out $@,$(MAKECMDGOALS))

makemigrations:
	@cd $(APP_DIR) && ./manage.py makemigrations

migrate:
	@cd $(APP_DIR) && ./manage.py migrate

tailwind-start:
	@cd $(APP_DIR) && ./manage.py tailwind start

tailwind-build:
	@cd $(APP_DIR) && ./manage.py tailwind build

# Workaround to pass arguments to manage command
# https://stackoverflow.com/a/6273809
%:
	@:
