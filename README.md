# Day Forge

AI-powered daily schedule assistant. Plan your day with templates, refine it with an AI command bar and chat, then review what you actually got done.

- **Backend:** Django 5.x, Python 3.14, SQLite, managed with [`uv`](https://github.com/astral-sh/uv)
- **Frontend:** Vue 3 + TypeScript + Inertia.js, served via Vite
- **AI:** OpenAI-compatible chat-completions (configurable model/base URL)

> ⚠️ **Production scale blocker:** the AI endpoints are `async def`, but the deployment is still WSGI/sync gunicorn — every async view runs through asgiref's thread-pool executor, so each in-flight LLM call still occupies one worker thread. Do not front this branch with concurrent production AI load until Phase 7 (ASGI runner + middleware audit) ships. See [CLAUDE.md](CLAUDE.md) § Production Deployment.

## Prerequisites

- Python 3.14 (pinned in `.python-version`)
- [`uv`](https://docs.astral.sh/uv/) for Python dependency management
- Node.js 20+ and npm for the frontend
- (Optional) Docker + Docker Compose

## Quick Start (Local)

Day Forge needs **two terminals** in development — Django serves the API on `:8006`, Vite serves the frontend with HMR on `:5173` and proxies API calls to Django.

```bash
# One-time setup
uv sync
uv run python backend/manage.py migrate
uv run python backend/manage.py createsuperuser
uv run python backend/manage.py seed_templates
cd frontend && npm install && cd ..
```

```bash
# Terminal 1 — Django backend
uv run python backend/manage.py runserver 8006
```

```bash
# Terminal 2 — Vite dev server
cd frontend && npm run dev
```

Then visit **http://localhost:5173/** and log in.

- Admin (templates, rules, schedules): http://localhost:8006/admin/
- API reference: [docs/api.md](docs/api.md)

## Quick Start (Docker)

```bash
docker compose build
docker compose run web uv run python manage.py migrate
docker compose run web uv run python manage.py createsuperuser
docker compose run web uv run python manage.py seed_templates
docker compose up
```

> This root Docker stack is **dev-only** (`runserver`, `DEBUG=1`). The
> production stack (uvicorn ASGI, multi-stage image, Redis) lives in
> `deployment/` — see **Deploy** below.

## Deploy

Production target: `dayforge.habitreward.org` on the shared habitreward
droplet, behind the central Caddy, via a gated GitHub Actions pipeline
(test → build → push GHCR → SSH deploy → health-check). One-time manual
setup (DNS, GitHub secrets, droplet firewall, Caddy block) and the full
runbook live in [`deployment/README.md`](deployment/README.md). Design
rationale: [`docs/features/0016_deploy_PLAN.md`](docs/features/0016_deploy_PLAN.md).

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
| `LLM_MODEL` | Model used by command + chat | `gpt-4o-mini` |
| `LLM_DRAFT_MODEL` | Model used by `generate-draft` | `gpt-4o` |
| `LLM_REQUEST_TIMEOUT` | Hard timeout for LLM HTTP calls (seconds) | `15` |
| `LLM_RATE_LIMIT_PER_HOUR` | Per-user limit on `/command/` | `100` |
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
uv run python backend/manage.py makemigrations
uv run python backend/manage.py migrate
uv run python backend/manage.py seed_templates

# Frontend
cd frontend && npm run dev          # Vite dev server (HMR)
cd frontend && npm run build        # Production build

# Lint / type-check
uv run ruff check backend/
uv run ruff check backend/ --fix
cd frontend && npx vue-tsc --noEmit
```

## Testing

```bash
# Backend (pytest)
uv run pytest backend/tests/ -v
uv run pytest backend/tests/test_file.py -v

# Frontend (vitest)
cd frontend && npm test
```

End-to-end Playwright scripts live in [frontend/scripts/playwright/](frontend/scripts/playwright/):

- `ai-chat-*.mjs` — multi-turn chat flows
- `ai-command-*.mjs` / `ai-draft-*.mjs` — command + draft endpoints

These hit the real LLM provider, require `LLM_API_KEY`, and **must be run serially** — they share rate-limit counters and concurrent runs will race them. The exception is `ai-draft-409-on-non-empty.mjs`, which short-circuits server-side and makes no LLM call.

## Architecture

```
backend/
  day_forge/          Django project (settings, URLs, ASGI/WSGI)
  schedules/          Schedule + TimeBlock models (core app)
  templates_mgr/      Templates, Rules, UserPreferences, seed command
  ai/                 AIInteraction model + service layer (command, draft, chat)
  analytics/          DailyReview model + streak/completion stats
  tests/              pytest test suite
frontend/
  src/pages/          Inertia page components (Login, Schedule, Settings, Analytics)
  src/components/     Reusable Vue components
  src/composables/    Vue composables (useSchedule, useChat, useThemeFromProps)
  src/utils/          theme.ts, themes.ts, etc.
db/                   SQLite database (gitignored)
docs/
  api.md              JSON API reference
  features/           Feature planning documents
```

## Key Documents

- [CLAUDE.md](CLAUDE.md) — Repo-level guidance for Claude Code (includes production-deployment caveats)
- [RULES.md](RULES.md) — Living knowledge base of patterns, pitfalls, conventions
- [PHASES.md](PHASES.md) — 7-phase implementation roadmap
- [day_forge_prd.md](day_forge_prd.md) — Product requirements
- [docs/api.md](docs/api.md) — JSON API reference
- [docs/features/](docs/features/) — Per-feature plans (created by the planner agent)
- [tasks/todo.md](tasks/todo.md) — Current work items
- [tasks/lessons.md](tasks/lessons.md) — Corrections and patterns learned

## Privacy Notes

- User commands and chat turns are logged to `AIInteraction` for audit (PRD §6.5). Avoid entering passwords or API keys in prompts.
- The **chat endpoint re-sends the full prior client-supplied transcript to the LLM provider on every turn** — a strictly larger egress surface than one-shot command. Use the Clear-thread button (or reload the page) before discussing anything sensitive. Thread state is in-memory per tab; there is no server-side persistence.
- Prior client turns are flattened into a single user-role message under an "Untrusted prior transcript" header — never forwarded as privileged `assistant` messages — so a tampered client cannot inject assistant pre-commitments. Regression-tested in `backend/tests/test_ai_service_chat.py`.
