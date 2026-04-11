# Development Workflows

## Run (two terminals needed)
```bash
uv run python backend/manage.py runserver 8006      # Terminal 1: Django on :8006
cd frontend && npm run dev                          # Terminal 2: Vite on :5173
```
Visit http://localhost:5173/ — Vite proxies to Django, serves frontend with HMR.

## Lint
```bash
uv run ruff check backend/                         # Python lint
uv run ruff check backend/ --fix                   # Auto-fix
cd frontend && npx vue-tsc --noEmit                # TypeScript type check
```

## Frontend
```bash
cd frontend && npm install                         # Install deps
cd frontend && npm run dev                         # Vite dev server
cd frontend && npm run build                       # Production build
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
