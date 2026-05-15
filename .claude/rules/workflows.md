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

## Manual Testing (browser smoke)
End-to-end browser smoke testing requires the **full dev stack** running
(Django on :8006 and Vite on :5173 — see § Run). Visit
http://localhost:5173/, log in (`createsuperuser` first if no account),
and exercise the feature in the actual browser.

The 6 chat-flow Playwright scripts at `frontend/scripts/playwright/
ai-chat-*.mjs` cover `POST /api/ai/schedules/<date>/chat/` but make real
LLM calls — they need `LLM_API_KEY` set and burn provider tokens.

The 4 follow-up scripts at `frontend/scripts/playwright/ai-command-*.mjs`
and `ai-draft-*.mjs` cover `POST /api/ai/schedules/<date>/command/` and
`POST /api/ai/schedules/<date>/generate-draft/` end-to-end (real LLM
calls; the `ai-draft-409-on-non-empty.mjs` script short-circuits
server-side and makes no LLM call). They also require `LLM_API_KEY`.
After any schedule-mutation refactor, run the relevant scripts instead
of doing a manual browser smoke pass.

For the no-autoreload variant of the Django server (useful when stepping
through with a debugger or doing manual smoke testing where you don't
want code edits to restart the backend mid-session):
```bash
uv run python backend/manage.py runserver 8006 --noreload
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
