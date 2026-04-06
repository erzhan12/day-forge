# Day Forge

AI-powered daily schedule assistant.

## Quick Start (Local)

```bash
uv sync
uv run python backend/manage.py migrate
uv run python backend/manage.py createsuperuser
uv run python backend/manage.py seed_templates
uv run python backend/manage.py runserver
```

Visit http://localhost:8000/admin/ to manage schedules, templates, and rules.

## Quick Start (Docker)

```bash
docker compose build
docker compose run web uv run python manage.py migrate
docker compose run web uv run python manage.py createsuperuser
docker compose run web uv run python manage.py seed_templates
docker compose up
```
