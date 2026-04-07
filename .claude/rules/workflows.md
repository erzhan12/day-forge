# Development Workflows

## Run
```bash
uv run python backend/manage.py runserver 8006      # Django dev server on :8006
```

## Lint
```bash
uv run ruff check backend/                         # Check
uv run ruff check backend/ --fix                   # Auto-fix
```

## Test
```bash
uv run pytest backend/tests/ -v                    # All tests
uv run pytest backend/tests/test_file.py -v        # Specific file
```

## Database
```bash
uv run python backend/manage.py makemigrations     # Create migrations
uv run python backend/manage.py migrate            # Apply migrations
uv run python backend/manage.py seed_templates     # Seed default data
uv run python backend/manage.py createsuperuser    # Create admin user
```

## Docker
```bash
docker compose up                                  # Start dev server
docker compose run web uv run python manage.py migrate   # Run migrations in container
```
