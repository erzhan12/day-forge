.DEFAULT_GOAL := help

.PHONY: help install dev run frontend-dev frontend-install frontend-build \
        lint lint-fix format typecheck test test-backend test-frontend check \
        migrate makemigrations seed superuser shell \
        docker docker-build docker-down clean

help: ## List available targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: frontend-install ## Install backend and frontend dependencies
	uv sync

dev: ## Print the two commands needed to run the full dev stack
	@echo "Run each in its own terminal:"
	@echo "  make run            # Django on :8006"
	@echo "  make frontend-dev   # Vite on :5173"

# ─── Backend ──────────────────────────────────────────────────────────────

run: ## Start Django dev server on :8006
	uv run python backend/manage.py runserver 8006

shell: ## Open Django shell
	uv run python backend/manage.py shell

migrate: ## Create and apply migrations
	uv run python backend/manage.py makemigrations
	uv run python backend/manage.py migrate

makemigrations: ## Create migrations only (no apply)
	uv run python backend/manage.py makemigrations

seed: ## Seed default templates
	uv run python backend/manage.py seed_templates

superuser: ## Create a Django superuser
	uv run python backend/manage.py createsuperuser

# ─── Frontend ─────────────────────────────────────────────────────────────

frontend-install: ## Install npm dependencies
	cd frontend && npm install

frontend-dev: ## Start Vite dev server on :5173
	cd frontend && npm run dev

frontend-build: ## Build frontend for production
	cd frontend && npm run build

# ─── Quality ──────────────────────────────────────────────────────────────

lint: ## Run ruff on backend
	uv run ruff check backend/

lint-fix: ## Run ruff with --fix on backend
	uv run ruff check backend/ --fix

format: ## Format backend code with ruff
	uv run ruff format backend/

typecheck: ## Run vue-tsc on frontend
	cd frontend && npx vue-tsc --noEmit

test: test-backend test-frontend ## Run backend and frontend tests

test-backend: ## Run pytest
	uv run pytest backend/tests/ -v

test-frontend: ## Run frontend tests
	cd frontend && npm test

check: lint typecheck test ## Lint + typecheck + test (run before pushing)

# ─── Docker ───────────────────────────────────────────────────────────────

docker: ## Start docker compose stack
	docker compose up

docker-build: ## Build docker images
	docker compose build

docker-down: ## Stop and remove containers
	docker compose down

# ─── Housekeeping ─────────────────────────────────────────────────────────

clean: ## Remove Python cache and build artifacts
	find . -type d -name __pycache__ -not -path "./.venv/*" -exec rm -rf {} +
	find . -type f -name "*.pyc" -not -path "./.venv/*" -delete
	rm -rf frontend/dist frontend/node_modules/.vite
