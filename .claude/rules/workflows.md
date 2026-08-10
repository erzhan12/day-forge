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

The 18 Playwright scripts at `frontend/scripts/playwright/*.mjs` cover AI chat,
draft, analytics, timeline, templates, themes, and Todoist flows.
See that directory's `README.md` for prerequisites and the per-script provider
call table. Several AI scenarios make real LLM calls and burn provider tokens;
the `ai-draft-409-on-non-empty.mjs` endpoint short-circuits before the LLM.
After a schedule-mutation refactor, run the relevant scripts instead of doing
an ad hoc browser smoke pass.

Run the scripts **serially**, not in parallel — they share
the `playwright` user's chat / draft rate-limit
counters, and concurrent runs would race the counter and produce a
false failure in `ai-draft-409-on-non-empty.mjs`'s "no consumption"
assertion.

From the repository root, use `make e2e` for all scenarios or
`make e2e-chat` and `make e2e-draft` for focused groups.
Pass `--cleanup` to an individual Node script only when its seeded schedules
should be deleted after the run; cleanup defaults off for post-mortem debugging.

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
