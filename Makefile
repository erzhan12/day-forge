.PHONY: run lint test migrate seed superuser docker docker-build

run:
	uv run python backend/manage.py runserver 8006

lint:
	uv run ruff check backend/

lint-fix:
	uv run ruff check backend/ --fix

test:
	uv run pytest backend/tests/ -v

migrate:
	uv run python backend/manage.py makemigrations
	uv run python backend/manage.py migrate

seed:
	uv run python backend/manage.py seed_templates

superuser:
	uv run python backend/manage.py createsuperuser

docker:
	docker compose up

docker-build:
	docker compose build
