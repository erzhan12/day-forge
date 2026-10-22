# Day Forge

Day Forge is a daily schedule assistant with templates, manual editing, AI chat and drafts, external calendar and task integrations, and daily reviews.

- **Backend:** Django 5.x, Python 3.14, SQLite, managed with [`uv`](https://github.com/astral-sh/uv)
- **Frontend:** Vue 3 + TypeScript + Inertia.js, served via Vite
- **AI:** OpenAI-compatible chat-completions (configurable model/base URL)

The production image starts `day_forge.asgi:application` with uvicorn. The WSGI/sync gunicorn warning in older feature plans applies to other runners, not the deployment in `deployment/`.

## Prerequisites

- Python 3.14 (pinned in `.python-version`)
- [`uv`](https://docs.astral.sh/uv/) for Python dependency management
- Node.js 22 and npm for the frontend (the CI version)
- (Optional) Docker + Docker Compose

## Quick Start (Local)

Day Forge needs two terminals in development. Django serves the API on port 8006; Vite serves the frontend on port 5173 and proxies API calls to Django.

```bash
# One-time setup
make install
make migrate
make superuser
make seed SEED_USER=your_username
```

```bash
# Terminal 1: Django backend
make run
```

```bash
# Terminal 2: Vite dev server
make frontend-dev
```

Then visit **http://localhost:5173/** and log in.

- Admin (templates, rules, schedules): http://localhost:8006/admin/
- API reference: [docs/api.md](docs/api.md)

## Quick Start (Docker)

```bash
docker compose build
docker compose run web uv run python manage.py migrate
docker compose run web uv run python manage.py createsuperuser
docker compose run web uv run python manage.py seed_templates --user your_username
docker compose up
```

The root Docker stack runs the development server with `DEBUG=1`. The production stack is in `deployment/`.

## Deploy

The deployment configuration targets `dayforge.habitreward.org` on the shared habitreward droplet behind Caddy. The Deploy workflow calls the same validation workflow used by pull requests, then builds and pushes a container image, deploys it over pinned SSH, and probes the HTTPS login page. The [deployment runbook](deployment/README.md) covers host setup, secrets, rollback, and backups. [Feature 0016](docs/features/0016_deploy_PLAN.md) records the original deployment design.

Production assets use content-hashed filenames and a release ID baked into the image. Deploy passes the Git SHA as the frontend build argument. Manual image builds must provide `--build-arg RELEASE_VERSION=<commit-sha>`. A standalone `DEBUG=0` run needs `make frontend-build` first; use `RELEASE_VERSION=<commit-sha> make frontend-build` to identify backend-only changes as a new release. See [the release verification report](docs/FRONTEND_RELEASE_VERIFICATION.md) for old-tab and rollback behavior.

## Configuration

Day Forge reads configuration from environment variables. The most common ones:

| Variable | Purpose | Default |
| --- | --- | --- |
| `DJANGO_SECRET_KEY` | Django secret key (required in production) | insecure dev fallback |
| `DEBUG` | `1` for dev, `0` for production | `1` |
| `ALLOWED_HOSTS` | Comma-separated hostnames (production only) | — |
| `CSRF_TRUSTED_ORIGINS` | Comma-separated origins incl. scheme (production only) | — |
| `REDIS_URL` | Cache / rate-limit backend (`RedisCache`). **Required when `LLM_API_KEY` is set** (`ai.E001`); LocMem fallback otherwise. | — |
| `LLM_API_KEY` | OpenAI-compatible API key. Empty ⇒ AI endpoints return 503 and the UI shows degraded mode. Manual editing still works. | — |
| `LLM_BASE_URL` | OpenAI-compatible base URL | `https://api.openai.com/v1` |
| `LLM_MODEL` | Model used by chat | `gpt-4o-mini` |
| `LLM_DRAFT_MODEL` | Model used by `generate-draft` | `gpt-4o` |
| `LLM_REQUEST_TIMEOUT` | Hard timeout for LLM HTTP calls (seconds) | `15` |
| `LLM_DRAFT_RATE_LIMIT_PER_HOUR` | Per-user limit on `/generate-draft/` | `10` |
| `LLM_CHAT_RATE_LIMIT_PER_HOUR` | Per-user limit on `/chat/` | `60` |
| `ANALYTICS_STREAK_THRESHOLD` | Daily completion ratio needed for streak credit | `0.8` |

The full list (history days, chat caps, schema caps, capture-prompt path, etc.) lives in [.claude/rules/project.md](.claude/rules/project.md).

> **Set `REDIS_URL` when AI is enabled.** The AI rate-limit counters live in `CACHES['default']`; Redis (Django's built-in `RedisCache`) makes them atomic and shared across workers via Redis `INCR`. The Django system check `ai.E001` blocks startup on an ineffective cache backend (`LocMemCache` / `FileBasedCache` / `DummyCache`) whenever `LLM_API_KEY` is set, **independent of `DEBUG`**. `REDIS_URL` is **required for AI-enabled deploys** and recommended otherwise (shared rate limits + CalDAV event-cache perf); when unset, Day Forge falls back to per-process `LocMemCache`, which only boots cleanly with AI disabled. For production, point `REDIS_URL` at an authenticated, TLS-enabled instance (`rediss://default:PASSWORD@host:6380/0`) and keep credentials out of version control.

## Development

```bash
# Backend
uv run python backend/manage.py runserver 8006              # Dev server
uv run python backend/manage.py runserver 8006 --noreload   # No autoreload (debuggers, manual smoke)
make makemigrations               # Only when models change
make migrate                      # Apply existing migrations
make seed SEED_USER=your_username

# Frontend
cd frontend && npm run dev          # Vite dev server (HMR)
cd frontend && npm run build        # Production build

# Lint / type-check
uv run ruff check backend/
uv run ruff check backend/ --fix
cd frontend && npm run type-check
```

## Testing

```bash
# Backend (pytest)
uv run pytest backend/tests/ -q
uv run pytest backend/tests/test_file.py -v

# Frontend (vitest)
cd frontend && npm test
```

Backend fixtures use a fast password hasher configured only in `backend/tests/conftest.py`. API tests use `force_login`; login and password-seeding tests request `production_password_hashers` to exercise real password verification. A separate test loads production settings in a fresh Python process to check that the fast hasher cannot leak into the application configuration.

Pull requests run `.github/workflows/ci.yml`. Deployment calls the same workflow before building or publishing an image. It checks backend lint and tests, frontend types and tests, the production build, production dependency vulnerabilities, and deployment SSH host-key pinning. PR checks have read-only repository access and do not require deployment secrets. Configure required checks in GitHub separately after the workflow has run.

To run the application checks locally from the repository root:

```bash
make check
make frontend-build
npm --prefix frontend audit --omit=dev --audit-level=high
```

`make check` runs backend lint and tests plus frontend type checking and tests. The separate build and audit commands above cover the remaining application checks from CI. The workflow also checks SSH host-key pinning in `.github/workflows/deploy.yml`.

End-to-end Playwright scripts are documented in [frontend/scripts/playwright/README.md](frontend/scripts/playwright/README.md). Some scripts call the real LLM or external providers and create data. Read the script guide before running `make e2e`.

## Architecture

```
backend/
  day_forge/          Django project (settings, URLs, ASGI/WSGI)
  schedules/          Schedule and block APIs, mutation planning and persistence
  templates_mgr/      Templates, rules, preferences, seed command
  ai/                 Chat and draft services, AIInteraction audit records
  analytics/          Current statistics and reviewed snapshots
  common/             Shared integration and HTTP infrastructure
  *_sync/             Calendar and task integrations
  tests/              pytest test suite
frontend/
  src/pages/          Inertia page components (Login, Schedule, Settings, Analytics)
  src/components/     Reusable Vue components
  src/composables/    Schedule page owner, revision state, integrations, AI
  src/utils/          theme.ts, themes.ts, etc.
db/                   SQLite database (gitignored)
docs/
  api.md              JSON API reference
  features/           Feature plans and reviews; see features/README.md
```

## Key Documents

- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md): current code map and data flow.
- [RULES.md](RULES.md): current invariants and conventions.
- [docs/api.md](docs/api.md): JSON API reference.
- [tasks/todo.md](tasks/todo.md) and [docs/REFACTORING_PLAN.md](docs/REFACTORING_PLAN.md): tracked work and refactor status.
- [tasks/lessons.md](tasks/lessons.md): bugs and corrections to review before coding.
- [docs/features/README.md](docs/features/README.md): how to read historical feature plans and reviews.
- [PHASES.md](PHASES.md) and [day_forge_prd.md](day_forge_prd.md): original roadmap and product requirements.

## Privacy Notes

- User commands and chat turns are logged to `AIInteraction` for audit (PRD §6.5). Avoid entering passwords or API keys in prompts.
- Fresh chat commands send the prior client transcript as untrusted provider context. Bound clarifications send the latest turn and a server-owned pending summary instead. Clear the thread before discussing anything sensitive. The UI keeps its thread in memory; the server retains audit records, durable receipts and pending-intent data. See [the pending-intent contract](docs/AI_PENDING_INTENT.md).
- Prior client turns are flattened into a single user-role message under an "Untrusted prior transcript" header. They are not forwarded as privileged `assistant` messages. `backend/tests/test_ai_service_chat.py` covers this boundary.
