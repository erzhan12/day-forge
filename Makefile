.DEFAULT_GOAL := help

.PHONY: help install dev run run-manual frontend-dev frontend-install frontend-build \
        lint lint-fix format typecheck test test-backend test-frontend check \
        e2e e2e-chat e2e-draft \
        migrate makemigrations seed superuser shell \
        docker docker-build docker-down clean

help: ## List available targets
	@awk 'BEGIN {FS = ":.*?## "} /^[a-zA-Z0-9_-]+:.*?## / {printf "  \033[36m%-20s\033[0m %s\n", $$1, $$2}' $(MAKEFILE_LIST)

install: frontend-install ## Install backend and frontend dependencies
	uv sync

dev: ## Print the two commands needed to run the full dev stack
	@echo "Run each in its own terminal:"
	@echo "  make run            # Django on :8006"
	@echo "  make frontend-dev   # Vite on :5173"

# ─── Backend ──────────────────────────────────────────────────────────────

run: ## Start Django dev server on :8006
	uv run python backend/manage.py runserver 8006

run-manual: ## Start Django dev server on :8006 without auto-reload
	uv run python backend/manage.py runserver 8006 --noreload

shell: ## Open Django shell
	uv run python backend/manage.py shell

migrate: ## Apply existing migrations
	uv run python backend/manage.py migrate

makemigrations: ## Create migrations only (no apply)
	uv run python backend/manage.py makemigrations

seed: export SEED_USER := $(SEED_USER)
seed: ## Seed templates for a user: make seed SEED_USER=username
	@test -n "$$SEED_USER" || { echo "Usage: make seed SEED_USER=username" >&2; exit 2; }
	uv run python backend/manage.py seed_templates --user "$$SEED_USER"

superuser: ## Create a Django superuser
	uv run python backend/manage.py createsuperuser

# ─── Frontend ─────────────────────────────────────────────────────────────

frontend-install: ## Install npm dependencies from the lockfile
	cd frontend && npm ci --no-audit --no-fund

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

typecheck: ## Run the frontend type-check script
	cd frontend && npm run type-check

test: test-backend test-frontend ## Run backend and frontend tests

test-backend: ## Run pytest
	uv run pytest backend/tests/ -q

test-frontend: ## Run frontend tests
	cd frontend && npm test

check: lint test-backend typecheck test-frontend ## Backend lint/tests and frontend type-check/tests

# These smoke scripts run serially because they share the playwright user's
# AI rate-limit counters. Some make real provider calls and consume tokens.
e2e: ## Run all Playwright e2e smoke scripts serially (needs dev stack)
	cd frontend && set -e; for script in scripts/playwright/*.mjs; do \
		case "$$script" in *-utils.mjs) continue ;; esac; \
		node "$$script"; \
	done
# Convention: shared helper modules under scripts/playwright/ must be named
# *-utils.mjs (e.g. test-utils.mjs) so this glob skips them instead of trying
# to run them as smoke scripts. See scripts/playwright/README.md.

e2e-chat: ## Run Playwright chat smoke scripts serially (real LLM calls; needs LLM_API_KEY)
	cd frontend && set -e; for script in scripts/playwright/ai-chat-*.mjs; do node "$$script"; done

# draft-prompt-history-suffix.mjs and regenerate-422-fallback.mjs are listed
# explicitly: they exercise draft flows but their names don't match the
# ai-draft-* glob. A new draft scenario with a non-matching name must be added
# here too, or it silently drops out of `make e2e-draft`.
e2e-draft: ## Run Playwright draft smoke scripts serially (real LLM calls; needs LLM_API_KEY)
	cd frontend && set -e; for script in scripts/playwright/ai-draft-*.mjs \
		scripts/playwright/draft-prompt-history-suffix.mjs \
		scripts/playwright/regenerate-422-fallback.mjs; do node "$$script"; done

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
