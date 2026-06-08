# Production Deployment Implementation Plan (feature 0016)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deploy day-forge to the existing `habitreward.org` DigitalOcean droplet as `dayforge.habitreward.org`, behind the shared central Caddy, using a gated GitHub Actions pipeline — matching the house pattern from `habit_reward` and `fitness-challenge`.

**Architecture:** A multi-stage Docker image (Node builds the Vue/Inertia frontend → Python runtime serves it via WhiteNoise under uvicorn ASGI). A `docker-compose` stack (web + redis) runs on the droplet, published on host port `8006`. The **central Caddy already running in habit_reward's compose** terminates TLS for `dayforge.habitreward.org` and reverse-proxies to `host.docker.internal:8006` — day-forge runs **no Caddy of its own**. GitHub Actions tests → builds → pushes to GHCR → SSH-deploys → health-checks.

**Tech Stack:** Django 5 + Inertia + Vue 3 (Vite), Python 3.14, `uv`, uvicorn (ASGI), WhiteNoise (static), Redis 7 (cache + atomic rate-limit counters), SQLite (bind-mounted), Caddy (shared, external), GHCR, GitHub Actions, OpenRouter (LLM).

## Decisions (from interview)

| Decision | Choice |
|---|---|
| Host | Reuse habitreward droplet; subdomain `dayforge.habitreward.org` → central Caddy → `host.docker.internal:8006` |
| App server | **uvicorn ASGI** (`day_forge.asgi:application`), `--workers 1` |
| AI | **Enabled** → Redis container **required** (`ai.E001`) |
| DB | **SQLite** bind-mount at `/app/db/day_forge.db` |
| CI/CD | **Full gated pipeline**: test → build → push GHCR → SSH deploy → health-check; triggers `push: main` + `workflow_dispatch` |
| First boot | `migrate` + `collectstatic` always; **auto-create superuser** from `DJANGO_SUPERUSER_*`; **no** auto `seed_templates` |
| LLM provider | **OpenRouter** (`LLM_BASE_URL` + model names supplied as secrets) |
| Backups | Manual for now (copy `db/day_forge.db`) |

## Why `--workers 1`

The ASGI concurrency win (Phase 7) comes from **one event loop serving N concurrent `await`s**, not from multiple processes. A single uvicorn worker already frees the loop during each LLM call. `--workers 1` *also* sidesteps SQLite multi-process write-lock contention. This matches habit_reward's `--workers 1`.

## Middleware async audit (Phase 7 / `0009_async_ai_views_PLAN.md` §D5)

`MIDDLEWARE` order: `SecurityMiddleware`, **`WhiteNoiseMiddleware` (sync-only)**, `SessionMiddleware`, **`InertiaMiddleware` (sync-only)**, `CommonMiddleware`, `CsrfViewMiddleware`, `AuthenticationMiddleware`, `MessageMiddleware`, `XFrameOptionsMiddleware`.

**Conclusion: ship as-is.** Under ASGI, Django wraps each sync middleware in its own `sync_to_async` thread-pool bridge; the chain still executes correctly. The sync middlewares add a per-request bridge hop but do **not** block the event loop during the LLM `await` inside the (async) view. No code changes required for correctness. This is a perf footnote, not a blocker — documented here so a future reader doesn't re-litigate it.

**Container health checks:** With `DEBUG=0`, internal probes to `http://localhost:8006/...` **must** send `X-Forwarded-Proto: https` (or `SECURE_SSL_REDIRECT` 301s them) **and** `Host: dayforge.habitreward.org` (or Django returns 400 — `ALLOWED_HOSTS` does not include `localhost`). See Tasks 5, 6. Pre-flight uses `ALLOWED_HOSTS=localhost` so only the proto header is needed there.

---

## File Structure

**Create:**
- `.dockerignore` — keep build context small (exclude `db/`, `node_modules`, `.venv`, `staticfiles`, `.git`)
- `deployment/scripts/entrypoint.sh` — migrate + collectstatic + superuser → exec uvicorn (**Task 4 — before Dockerfile**)
- `deployment/docker/Dockerfile` — multi-stage prod image (frontend build + python runtime)
- `deployment/docker/docker-compose.yml` — prod stack (web + redis) for the droplet
- `deployment/caddy/dayforge.caddy` — Caddy block to paste into habit_reward's central `Caddyfile` (reference copy lives in this repo)
- `deployment/README.md` — one-time manual ops checklist (DNS, GitHub secrets, droplet firewall, Caddyfile edit + reload)
- `.github/workflows/deploy.yml` — gated test→build→deploy→health-check pipeline

**Modify:**
- `backend/day_forge/settings.py` — add `SECURE_PROXY_SSL_HEADER` (and `USE_X_FORWARDED_HOST`) under the `if not DEBUG` block
- `pyproject.toml` — add `uvicorn[standard]` to `[project.dependencies]`
- `.env.example` — add `DJANGO_SUPERUSER_*`; clarify prod `REDIS_URL`
- `backend/tests/test_settings_validation.py` — assert proxy-SSL header present
- `RULES.md`, `CLAUDE.md`, `README.md` — deploy docs

**Leave untouched (dev stack):** root `Dockerfile` + root `docker-compose.yml` stay as the **dev** stack (`runserver`, `DEBUG=1`, bind-mounts). Production is a separate `deployment/` stack so `make docker` / local dev is unaffected.

---

### Task 1: Trust Caddy's TLS termination (fix the redirect loop)

**Files:**
- Modify: `backend/day_forge/settings.py` (the `if not DEBUG:` block, currently lines 113-118)
- Test: `backend/tests/test_settings_validation.py`

Behind Caddy, TLS terminates at the proxy and the app receives plain HTTP. With `SECURE_SSL_REDIRECT = True` (already set when `DEBUG=False`) and **no** `SECURE_PROXY_SSL_HEADER`, every request looks insecure to Django → it 301-redirects to `https://` → Caddy proxies plain HTTP again → **infinite redirect loop**. Adding the header tells Django to trust `X-Forwarded-Proto: https` from Caddy.

- [ ] **Step 1: Write the failing test**

Add to `backend/tests/test_settings_validation.py` (reuse module-level `_exec_settings` from feature 0015 — do **not** `importlib.reload` `day_forge.settings`):

```python
def test_secure_proxy_ssl_header_set_in_production(monkeypatch):
    """Behind Caddy, Django must trust X-Forwarded-Proto or SECURE_SSL_REDIRECT loops."""
    ns = _exec_settings(
        monkeypatch,
        DEBUG="0",
        DJANGO_SECRET_KEY="x" * 50,
        REDIS_URL="",  # pin so a host .env cannot leak in
    )
    assert ns["SECURE_PROXY_SSL_HEADER"] == ("HTTP_X_FORWARDED_PROTO", "https")
    assert ns["SECURE_SSL_REDIRECT"] is True  # guard: the setting this protects
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest backend/tests/test_settings_validation.py -k secure_proxy -v`
Expected: FAIL — `KeyError: 'SECURE_PROXY_SSL_HEADER'` (`_exec_settings()` returns a dict; the key is absent before Step 3)

- [ ] **Step 3: Add the setting**

In `backend/day_forge/settings.py`, inside the existing `if not DEBUG:` block (after `SECURE_HSTS_INCLUDE_SUBDOMAINS = True`), add:

```python
    # TLS terminates at the shared Caddy reverse proxy, which forwards plain
    # HTTP with `X-Forwarded-Proto: https`. Without this, SECURE_SSL_REDIRECT
    # (set just above) sees every proxied request as insecure and 301-loops.
    SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")
    USE_X_FORWARDED_HOST = True
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest backend/tests/test_settings_validation.py -k secure_proxy -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/day_forge/settings.py backend/tests/test_settings_validation.py
git commit -m "feat(0016): trust Caddy X-Forwarded-Proto to avoid SSL redirect loop"
```

---

### Task 2: Add uvicorn to dependencies

**Files:**
- Modify: `pyproject.toml` (`[project.dependencies]`)

`pyproject.toml` has no production server. The image runs `uvicorn day_forge.asgi:application`.

- [ ] **Step 1: Add the dependency**

In `pyproject.toml`, add to `[project.dependencies]` (keep the list alphabetically consistent with neighbours):

```toml
    "uvicorn[standard]>=0.34.0",
```

- [ ] **Step 2: Lock + verify it resolves**

Run: `uv lock && uv sync`
Expected: `uv.lock` updates; `uv run python -c "import uvicorn; print(uvicorn.__version__)"` prints a version.

- [ ] **Step 3: Verify the ASGI app imports under uvicorn's loader**

Run: `cd backend && DJANGO_SETTINGS_MODULE=day_forge.settings uv run python -c "from day_forge.asgi import application; print(type(application))"`
Expected: prints an ASGI application type (no traceback).

- [ ] **Step 4: Commit**

```bash
git add pyproject.toml uv.lock
git commit -m "feat(0016): add uvicorn[standard] for production ASGI server"
```

---

### Task 3: Add `.dockerignore`

**Files:**
- Create: `.dockerignore`

- [ ] **Step 1: Create the file**

`.dockerignore`:

```gitignore
.git
.github
**/.venv
**/node_modules
**/__pycache__
**/*.pyc
db/
staticfiles/
frontend/dist/
.env
*.sqlite3
.pytest_cache
.ruff_cache
docs/
tasks/
frontend/scripts/playwright/
```

> `db/` and `frontend/dist/` are excluded so the build context never ships local SQLite data or a stale local Vite build — the image builds `dist` fresh in the Node stage.

- [ ] **Step 2: Commit**

```bash
git add .dockerignore
git commit -m "feat(0016): add .dockerignore for lean build context"
```

---

### Task 4: Entrypoint script

**Files:**
- Create: `deployment/scripts/entrypoint.sh`

> **Order:** Complete this task **before** Task 5. The Dockerfile `COPY`s `deployment/scripts/entrypoint.sh`; `docker build` fails if the file does not exist yet.

Runs from `/app/backend` (Dockerfile `WORKDIR`). Always migrate + collectstatic; create superuser idempotently from env; then `exec` the CMD (uvicorn) so it becomes PID 1 and receives signals.

- [ ] **Step 1: Create the script**

`deployment/scripts/entrypoint.sh`:

```sh
#!/usr/bin/env sh
set -e

echo "[entrypoint] applying migrations"
python manage.py migrate --noinput

echo "[entrypoint] collecting static files"
python manage.py collectstatic --noinput

# Idempotent superuser creation from DJANGO_SUPERUSER_* (skipped if unset).
if [ -n "$DJANGO_SUPERUSER_USERNAME" ] && [ -n "$DJANGO_SUPERUSER_PASSWORD" ]; then
    echo "[entrypoint] ensuring superuser '$DJANGO_SUPERUSER_USERNAME' exists"
    python manage.py shell <<'PY'
import os
from django.contrib.auth import get_user_model

User = get_user_model()
username = os.environ["DJANGO_SUPERUSER_USERNAME"]
email = os.environ.get("DJANGO_SUPERUSER_EMAIL", "")
password = os.environ["DJANGO_SUPERUSER_PASSWORD"]
if not User.objects.filter(username=username).exists():
    User.objects.create_superuser(username=username, email=email, password=password)
    print(f"[entrypoint] created superuser {username}")
else:
    print(f"[entrypoint] superuser {username} already exists; leaving as-is")
PY
fi

echo "[entrypoint] starting: $*"
exec "$@"
```

- [ ] **Step 2: Mark executable + smoke-test the shell syntax**

Run: `chmod +x deployment/scripts/entrypoint.sh && sh -n deployment/scripts/entrypoint.sh`
Expected: no output (syntax OK).

- [ ] **Step 3: Commit**

```bash
git add deployment/scripts/entrypoint.sh
git commit -m "feat(0016): container entrypoint (migrate, collectstatic, superuser)"
```

---

### Task 5: Production multi-stage Dockerfile

**Files:**
- Create: `deployment/docker/Dockerfile`

**Depends on Task 4** — `COPY deployment/scripts/entrypoint.sh` requires the script to exist in the build context.

Three stages: (1) Node builds the frontend → `/app/frontend/dist`; (2) `uv` installs Python deps; (3) slim runtime assembles app + deps, runs as non-root, starts uvicorn. Paths must match `settings.py`: `STATICFILES_DIRS=[PROJECT_ROOT/frontend/dist]`, `STATIC_ROOT=PROJECT_ROOT/staticfiles`, `DATABASES.NAME=PROJECT_ROOT/db/day_forge.db`, where `PROJECT_ROOT=/app`.

- [ ] **Step 1: Create the Dockerfile**

`deployment/docker/Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1

# --- Stage 1: build the Vue/Inertia frontend -------------------------------
FROM node:22-slim AS frontend
WORKDIR /build
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
# Vite outputs to ./dist (outDir in vite.config.ts) with base "/static/" in prod.
RUN NODE_ENV=production npm run build

# --- Stage 2: resolve Python deps with uv ----------------------------------
FROM python:3.14-slim AS deps
COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Install into a project-local .venv so we can copy it wholesale into runtime.
RUN uv sync --frozen --no-dev

# --- Stage 3: runtime ------------------------------------------------------
FROM python:3.14-slim AS runtime
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PATH="/app/.venv/bin:$PATH"
RUN apt-get update && apt-get install -y --no-install-recommends curl \
    && rm -rf /var/lib/apt/lists/* \
    && groupadd --gid 1000 app \
    && useradd --uid 1000 --gid app --create-home app

WORKDIR /app
# Python virtualenv from the deps stage
COPY --from=deps /app/.venv /app/.venv
# Backend source
COPY backend/ /app/backend/
# Built frontend assets (settings.py expects PROJECT_ROOT/frontend/dist)
COPY --from=frontend /build/dist /app/frontend/dist
# Entrypoint (created in Task 4)
COPY deployment/scripts/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh \
    && mkdir -p /app/db /app/staticfiles \
    && chown -R app:app /app

USER app
WORKDIR /app/backend
EXPOSE 8006

HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -fsS --max-time 5 -H "X-Forwarded-Proto: https" -H "Host: dayforge.habitreward.org" http://localhost:8006/accounts/login/ || exit 1

ENTRYPOINT ["/app/entrypoint.sh"]
CMD ["uvicorn", "day_forge.asgi:application", "--host", "0.0.0.0", "--port", "8006", "--workers", "1"]
```

> `uv sync --no-dev` excludes the `pytest`/`ruff` dev group. Confirm the dev deps live in a group `uv` treats as non-default (i.e. `[dependency-groups] dev = [...]` or `[tool.uv]`); if they're under `[project.optional-dependencies]` instead, drop `--no-dev` (they won't be installed without `--extra`). Verify in Step 2.

- [ ] **Step 2: Build the image locally**

Run from repo root: `docker build -f deployment/docker/Dockerfile -t day-forge:local .`
Expected: build completes; all three stages succeed; final image tagged `day-forge:local`.

- [ ] **Step 3: Verify static + entry layout inside the image**

Run: `docker run --rm day-forge:local sh -c "ls /app/frontend/dist/assets && ls /app/entrypoint.sh && which uvicorn"`
Expected: lists `app.css` + `app.js`, the entrypoint path, and `/app/.venv/bin/uvicorn`.

- [ ] **Step 4: Commit**

```bash
git add deployment/docker/Dockerfile
git commit -m "feat(0016): production multi-stage Dockerfile (frontend build + uvicorn)"
```

---

### Task 6: Production docker-compose (web + redis)

**Files:**
- Create: `deployment/docker/docker-compose.yml`

This stack runs on the droplet. The image comes from GHCR (built by CI). `REDIS_URL` points at the compose-internal `redis` service. Web publishes `8006` to the host so the **central Caddy** (a separate compose in habit_reward, using `host.docker.internal:host-gateway`) can reach it.

- [ ] **Step 1: Create the compose file**

`deployment/docker/docker-compose.yml`:

```yaml
services:
  web:
    # No default image tag — CI always writes DOCKER_IMAGE to .env on deploy;
    # manual `docker compose up` without .env fails fast instead of pulling a
    # hardcoded owner/repo (see Task 8 / deployment/README.md).
    image: ${DOCKER_IMAGE:?Set DOCKER_IMAGE in .env — CI writes ghcr.io/<owner>/day-forge:<sha>}
    container_name: day_forge_web
    restart: unless-stopped
    # Published on 0.0.0.0:8006 so habit_reward's central Caddy reaches it via
    # host.docker.internal:8006 (Docker bridge gateway on Linux — NOT 127.0.0.1,
    # so do not bind 127.0.0.1:8006:8006 as the primary exposure fix).
    # UFW alone does NOT block public :8006 — Docker publishes via iptables
    # (DOCKER chain) and bypasses ufw. SEE deployment/README.md §3 for the
    # required DOCKER-USER iptables rules + off-host verification curl.
    ports:
      - "8006:8006"
    env_file:
      - .env
    environment:
      # Overrides any REDIS_URL in .env: talk to the compose-internal service.
      REDIS_URL: redis://redis:6379/0
    volumes:
      - ./data:/app/db                 # SQLite file: /app/db/day_forge.db
      - ./staticfiles:/app/staticfiles  # collectstatic target (optional persist)
    depends_on:
      redis:
        condition: service_healthy
    healthcheck:
      # DEBUG=0: proto header (SECURE_SSL_REDIRECT) + Host (ALLOWED_HOSTS — not localhost).
      test: ["CMD", "curl", "-fsS", "--max-time", "5", "-H", "X-Forwarded-Proto: https", "-H", "Host: dayforge.habitreward.org", "http://localhost:8006/accounts/login/"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 40s

  redis:
    image: redis:7-alpine
    container_name: day_forge_redis
    restart: unless-stopped
    # Not published to the host — only the web service reaches it on the
    # compose network. KEY_PREFIX "dayforge" namespaces keys (settings.py).
    healthcheck:
      test: ["CMD", "redis-cli", "ping"]
      interval: 5s
      timeout: 3s
      retries: 5
```

- [ ] **Step 2: Validate the compose schema**

Run: `DOCKER_IMAGE=day-forge:local docker compose -f deployment/docker/docker-compose.yml config`
Expected: prints the resolved config with no errors. (`DOCKER_IMAGE` is required — no default image in the file; CI writes it on deploy.)

- [ ] **Step 3: Commit**

```bash
git add deployment/docker/docker-compose.yml
git commit -m "feat(0016): production docker-compose (web + redis)"
```

---

### Task 7: Caddy block for the shared central Caddyfile

**Files:**
- Create: `deployment/caddy/dayforge.caddy` (reference copy; the live edit happens in the **habit_reward** repo's `Caddyfile`)

day-forge runs **no Caddy**. The central Caddy in habit_reward owns :80/:443 and already fans subdomains to host ports. We add one block. WhiteNoise serves static inside the app, so Caddy only reverse-proxies (no `file_server` needed, unlike habit_reward's main site).

- [ ] **Step 1: Create the reference snippet**

`deployment/caddy/dayforge.caddy`:

```caddyfile
# Add this block to habit_reward's central Caddyfile, then reload Caddy.
# day-forge serves its own static via WhiteNoise, so no file_server here.
dayforge.habitreward.org {
	encode zstd gzip

	# Django trusts this via SECURE_PROXY_SSL_HEADER (settings.py).
	reverse_proxy host.docker.internal:8006 {
		header_up X-Forwarded-Proto https
	}

	header {
		Strict-Transport-Security "max-age=31536000; includeSubDomains; preload"
		X-Content-Type-Options "nosniff"
		X-Frame-Options "SAMEORIGIN"
		Referrer-Policy "strict-origin-when-cross-origin"
	}

	log {
		output file /var/log/caddy/dayforge-access.log
	}
}
```

- [ ] **Step 2: Commit**

```bash
git add deployment/caddy/dayforge.caddy
git commit -m "feat(0016): Caddy reverse-proxy block for dayforge subdomain"
```

> The actual Caddyfile edit + `docker exec <caddy> caddy reload` (or `docker compose restart caddy`) in the **habit_reward** repo is a one-time manual step — see `deployment/README.md`.

---

### Task 8: GitHub Actions deploy pipeline

**Files:**
- Create: `.github/workflows/deploy.yml`

Gated: `deploy` only runs if `test` passes. Triggers on push to `main` and manual dispatch. Mirrors habit_reward/fitness-challenge: test (backend pytest + frontend vitest + vue-tsc) → build & push to GHCR → SSH deploy → health-check.

- [ ] **Step 1: Create the workflow**

`.github/workflows/deploy.yml`:

```yaml
name: Deploy

on:
  push:
    branches: [main]
  workflow_dispatch:

concurrency:
  group: deploy-${{ github.ref }}
  cancel-in-progress: false

env:
  IMAGE: ghcr.io/${{ github.repository_owner }}/day-forge

jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Install uv
        uses: astral-sh/setup-uv@v5

      - name: Set up Python
        run: uv python install 3.14

      - name: Install backend deps
        run: uv sync --frozen

      - name: Run backend tests
        # AI rate-limit tests assume LocMemCache (conftest pins it); leave
        # LLM_API_KEY unset so ai.E001 does not require Redis in CI.
        run: uv run pytest backend/tests/ -q

      - name: Set up Node
        uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: frontend/package-lock.json

      - name: Install frontend deps
        working-directory: frontend
        run: npm ci --no-audit --no-fund

      - name: Frontend type-check + tests
        working-directory: frontend
        run: |
          npm run type-check
          npm test

  build-and-push:
    needs: test
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: write
    outputs:
      image_tag: ${{ steps.meta.outputs.tag }}
    steps:
      - uses: actions/checkout@v4

      - name: Log in to GHCR
        uses: docker/login-action@v3
        with:
          registry: ghcr.io
          username: ${{ github.actor }}
          password: ${{ secrets.GITHUB_TOKEN }}

      - name: Set up Buildx
        uses: docker/setup-buildx-action@v3

      - name: Compute tags
        id: meta
        run: echo "tag=${GITHUB_SHA::12}" >> "$GITHUB_OUTPUT"

      - name: Build and push
        uses: docker/build-push-action@v6
        with:
          context: .
          file: deployment/docker/Dockerfile
          push: true
          tags: |
            ${{ env.IMAGE }}:latest
            ${{ env.IMAGE }}:${{ steps.meta.outputs.tag }}
          cache-from: type=gha
          cache-to: type=gha,mode=max

  deploy:
    needs: build-and-push
    runs-on: ubuntu-latest
    permissions:
      contents: read
      packages: read
    steps:
      - name: Install SSH key
        uses: webfactory/ssh-agent@v0.9.0
        with:
          ssh-private-key: ${{ secrets.SSH_PRIVATE_KEY }}

      - name: Add server to known_hosts
        run: ssh-keyscan -H "${{ secrets.SERVER_HOST }}" >> ~/.ssh/known_hosts

      - name: Copy deployment files to droplet
        env:
          SSH_TARGET: ${{ secrets.SSH_USER }}@${{ secrets.SERVER_HOST }}
          DEPLOY_PATH: ${{ secrets.DEPLOY_PATH }}
        run: |
          # Container runs as uid 1000 — host dirs must be writable (see deployment/README.md §3b).
          ssh "$SSH_TARGET" "mkdir -p \"$DEPLOY_PATH/data\" \"$DEPLOY_PATH/staticfiles\" && sudo chown -R 1000:1000 \"$DEPLOY_PATH/data\" \"$DEPLOY_PATH/staticfiles\""
          scp deployment/docker/docker-compose.yml "$SSH_TARGET:$DEPLOY_PATH/docker-compose.yml"

      - name: Write .env, pull image, restart stack
        env:
          SSH_TARGET: ${{ secrets.SSH_USER }}@${{ secrets.SERVER_HOST }}
          DEPLOY_PATH: ${{ secrets.DEPLOY_PATH }}
          IMAGE_REF: ${{ env.IMAGE }}:${{ needs.build-and-push.outputs.image_tag }}
          DJANGO_SECRET_KEY: ${{ secrets.DJANGO_SECRET_KEY }}
          ALLOWED_HOSTS: ${{ secrets.ALLOWED_HOSTS }}
          CSRF_TRUSTED_ORIGINS: ${{ secrets.CSRF_TRUSTED_ORIGINS }}
          CALDAV_ENCRYPTION_KEY: ${{ secrets.CALDAV_ENCRYPTION_KEY }}
          LLM_API_KEY: ${{ secrets.LLM_API_KEY }}
          LLM_BASE_URL: ${{ secrets.LLM_BASE_URL }}
          LLM_MODEL: ${{ secrets.LLM_MODEL }}
          LLM_DRAFT_MODEL: ${{ secrets.LLM_DRAFT_MODEL }}
          DJANGO_SUPERUSER_USERNAME: ${{ secrets.DJANGO_SUPERUSER_USERNAME }}
          DJANGO_SUPERUSER_EMAIL: ${{ secrets.DJANGO_SUPERUSER_EMAIL }}
          DJANGO_SUPERUSER_PASSWORD: ${{ secrets.DJANGO_SUPERUSER_PASSWORD }}
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
          GITHUB_ACTOR: ${{ github.actor }}
        run: |
          # Build .env via Python — never interpolate secrets inside double-quoted shell
          # echo (metacharacters in DJANGO_SUPERUSER_PASSWORD etc. break or inject).
          python3 <<'PY'
          import os, sys

          def require(name: str) -> str:
              value = os.environ.get(name, "")
              if not value:
                  sys.exit(f"missing required env var: {name}")
              if "\n" in value or "\r" in value:
                  sys.exit(f"{name} must not contain newlines")
              return value

          def dotenv_line(key: str, value: str, *, quote: bool = True) -> str:
              """Single-quoted values: Compose env_file does not expand $ inside quotes."""
              if not quote:
                  return f"{key}={value}"
              escaped = value.replace("'", "\\'")  # Compose: only ' is escaped inside '...'; \ is literal
              return f"{key}='{escaped}'"

          lines = [
              "DEBUG=0",
              dotenv_line("DJANGO_SECRET_KEY", require("DJANGO_SECRET_KEY")),
              dotenv_line("ALLOWED_HOSTS", require("ALLOWED_HOSTS")),
              dotenv_line("CSRF_TRUSTED_ORIGINS", require("CSRF_TRUSTED_ORIGINS")),
              dotenv_line("CALDAV_ENCRYPTION_KEY", require("CALDAV_ENCRYPTION_KEY")),
              dotenv_line("LLM_API_KEY", require("LLM_API_KEY")),
              dotenv_line("LLM_BASE_URL", require("LLM_BASE_URL")),
              dotenv_line("LLM_MODEL", require("LLM_MODEL")),
              dotenv_line("LLM_DRAFT_MODEL", require("LLM_DRAFT_MODEL")),
              dotenv_line("DJANGO_SUPERUSER_USERNAME", require("DJANGO_SUPERUSER_USERNAME")),
              dotenv_line("DJANGO_SUPERUSER_EMAIL", require("DJANGO_SUPERUSER_EMAIL")),
              dotenv_line("DJANGO_SUPERUSER_PASSWORD", require("DJANGO_SUPERUSER_PASSWORD")),
              dotenv_line("DOCKER_IMAGE", require("IMAGE_REF")),
          ]
          path = "/tmp/day-forge.env"
          with open(path, "w", encoding="utf-8") as f:
              f.write("\n".join(lines) + "\n")
          PY
          scp /tmp/day-forge.env "$SSH_TARGET:$DEPLOY_PATH/.env"
          rm -f /tmp/day-forge.env
          ssh "$SSH_TARGET" "grep -q '^DEBUG=0$' '$DEPLOY_PATH/.env'"
          ssh "$SSH_TARGET" "bash -s" <<EOF
          set -e
          cd "$DEPLOY_PATH"
          echo "$GITHUB_TOKEN" | docker login ghcr.io -u "$GITHUB_ACTOR" --password-stdin
          export DOCKER_IMAGE="$IMAGE_REF"
          docker compose pull
          docker compose up -d --remove-orphans
          docker image prune -f
          EOF

  health-check:
    needs: deploy
    runs-on: ubuntu-latest
    steps:
      - name: Wait for stabilization
        run: sleep 30

      - name: Probe HTTPS endpoint
        run: |
          for i in $(seq 1 5); do
            code=$(curl -s -o /dev/null -w "%{http_code}" https://dayforge.habitreward.org/accounts/login/ || true)
            echo "attempt $i: HTTP $code"
            if [ "$code" = "200" ]; then exit 0; fi
            sleep 10
          done
          echo "health check failed"; exit 1
```

> `.env` is built on the runner with a Python script reading secrets from step `env:` (never `${{ secrets.* }}` inside double-quoted `echo` — shell metacharacters corrupt or inject). Secret values are written as **single-quoted** dotenv literals (`key='value'`) so Compose `env_file` does not treat `$` in passwords/API keys as variable interpolation; only embedded `'` is escaped (`\'`); other characters including `\` are literal inside single quotes (e.g. `can't` → `'can\'t'`, `some\tvalue` → `'some\tvalue'`). The script rejects newline-containing values. `deploy` job sets `permissions: packages: read` for GHCR pull via `GITHUB_TOKEN`. The deploy step also runs `sudo chown -R 1000:1000` on bind-mount dirs — grant `SSH_USER` passwordless sudo for that path (see README §3b).

- [ ] **Step 2: Lint the workflow YAML**

Run: `docker compose -f deployment/docker/docker-compose.yml config >/dev/null && python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/deploy.yml')); print('yaml ok')"`
Expected: `yaml ok`.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/deploy.yml
git commit -m "feat(0016): gated GitHub Actions deploy pipeline (GHCR + SSH)"
```

---

### Task 9: Env documentation

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Append the deploy/superuser block to `.env.example`**

Add (under the existing prod section):

```bash
# --- Production deploy (feature 0016) ---------------------------------------
# Set as GitHub Actions secrets; CI writes them into .env on the droplet.
# REDIS_URL is overridden by docker-compose to redis://redis:6379/0; set it
# here only for non-compose runs.
# Required for DEBUG=0 boot (calendar_sync.E001) even if CalDAV is unused.
CALDAV_ENCRYPTION_KEY=
# DJANGO_SUPERUSER_* are consumed by deployment/scripts/entrypoint.sh on first
# boot to create the /admin user idempotently.
DJANGO_SUPERUSER_USERNAME=
DJANGO_SUPERUSER_EMAIL=
DJANGO_SUPERUSER_PASSWORD=
```

- [ ] **Step 2: Commit**

```bash
git add .env.example
git commit -m "docs(0016): document deploy + superuser env vars"
```

---

### Task 10: Deploy runbook + knowledge-base updates

**Files:**
- Create: `deployment/README.md`
- Modify: `RULES.md`, `CLAUDE.md` (Production Deployment section), `README.md`

- [ ] **Step 1: Create `deployment/README.md`** with the one-time manual ops:

````markdown
# Deploying day-forge

Target: `dayforge.habitreward.org` on the shared habitreward DigitalOcean droplet,
behind the central Caddy that already lives in the **habit_reward** repo's compose.

## First deploy order (blocking)

Complete **before** expecting a green CI health-check:

1. DNS A record (`dayforge` → droplet IP)
2. GitHub Actions secrets (below)
3. Droplet firewall + **DOCKER-USER** iptables (restrict public `:8006`; ufw alone is insufficient)
4. **Bind-mount ownership** — `sudo chown -R 1000:1000 "$DEPLOY_PATH/data" "$DEPLOY_PATH/staticfiles"` (container uid `app` = 1000; required for SQLite + collectstatic)
5. **Central Caddy block** in habit_reward + reload (§4 below)
6. Push to `main` or run **Deploy** workflow manually

Steps 1–5 are required: the workflow's HTTPS probe hits Caddy, not the app port
directly. CI re-applies the `chown` on every deploy; first boot still needs it
before the first successful `migrate` if you bring the stack up manually.

## One-time setup

### 1. DNS (Namecheap)
Add an **A record**: host `dayforge` → the droplet's public IP. (Subdomain of
`habitreward.org`, so it inherits the zone.)

### 2. GitHub Actions secrets (repo → Settings → Secrets → Actions)
| Secret | Example / note |
|---|---|
| `SSH_PRIVATE_KEY` | deploy key for the droplet |
| `SERVER_HOST` | droplet public IP |
| `SSH_USER` | e.g. `deploy` — must have **passwordless `sudo`** for `chown -R 1000:1000` on `$DEPLOY_PATH/data` and `staticfiles` (CI runs this every deploy) |
| `DEPLOY_PATH` | e.g. `/home/deploy/day-forge` |
| `DJANGO_SECRET_KEY` | 50+ random chars |
| `ALLOWED_HOSTS` | `dayforge.habitreward.org` |
| `CSRF_TRUSTED_ORIGINS` | `https://dayforge.habitreward.org` |
| `CALDAV_ENCRYPTION_KEY` | `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"` |
| `LLM_API_KEY` | OpenRouter key |
| `LLM_BASE_URL` | `https://openrouter.ai/api/v1` |
| `LLM_MODEL` | OpenRouter model id (command/chat) |
| `LLM_DRAFT_MODEL` | OpenRouter model id (draft) |
| `DJANGO_SUPERUSER_USERNAME` / `_EMAIL` / `_PASSWORD` | admin login — `$` and `'` are fine (CI writes single-quoted `.env` with `\'` escaping) |

> `CALDAV_ENCRYPTION_KEY` is **required** for a `DEBUG=0` boot even if nobody uses
> Apple Calendar (`calendar_sync.E001` blocks startup otherwise).

### 3. Restrict public access to `:8006` (ufw + DOCKER-USER)

The web container publishes `8006:8006` on `0.0.0.0` so the central Caddy can reach
`host.docker.internal:8006` via the Docker bridge gateway. **Do not** switch to
`127.0.0.1:8006:8006` as the primary fix — on Linux, Caddy in habit_reward's compose
reaches the host through the bridge gateway, not loopback, and localhost-only binds
break the Caddy → app path.

**UFW alone is not enough:** Docker publishes ports through iptables (`DOCKER` chain)
and traffic to `droplet-ip:8006` often bypasses ufw entirely. Keep ufw for SSH/80/443,
then add **DOCKER-USER** rules (evaluated before Docker's own ACCEPT rules):

```bash
sudo ufw allow OpenSSH
sudo ufw allow 80,443/tcp
sudo ufw deny 8006/tcp        # belt-and-suspenders; pair with DOCKER-USER below
sudo ufw enable

# Allow established/related, loopback, and Docker-private-source → host :8006 (Caddy path).
# habit_reward's central Caddy runs on a Compose `br-*` bridge, NOT `docker0` — use
# source-CIDR allow (covers default bridge + user-defined compose networks).
# Drop other inbound to host :8006 (internet scanners).
sudo iptables -I DOCKER-USER 1 -m conntrack --ctstate RELATED,ESTABLISHED -j RETURN
sudo iptables -I DOCKER-USER 2 -i lo -j RETURN
sudo iptables -I DOCKER-USER 3 -s 172.16.0.0/12 -p tcp --dport 8006 -j RETURN
sudo iptables -I DOCKER-USER 4 -p tcp --dport 8006 -j DROP

# Persist across reboot (pick what the droplet already uses):
#   Debian/Ubuntu: sudo apt install -y iptables-persistent && sudo netfilter-persistent save
#   or document equivalent in habit_reward's droplet runbook.
```

**Verify from off-host** (laptop, not SSH'd into the droplet):

```bash
curl -s -o /dev/null -w "%{http_code}\n" --max-time 5 http://<DROPLET_IP>:8006/accounts/login/
# Expected: timeout or connection refused — NOT 200/301 from Django.

curl -fsS -o /dev/null -w "%{http_code}\n" https://dayforge.habitreward.org/accounts/login/
# Expected: 200 — Caddy → host.docker.internal:8006 still works after the DROP rule.
```

### 3b. Bind-mount permissions

The container runs as **uid 1000** (`app`). Ensure `$DEPLOY_PATH/data` (and
`staticfiles`) are writable by that uid on the host, e.g.:

```bash
mkdir -p "$DEPLOY_PATH/data" "$DEPLOY_PATH/staticfiles"
sudo chown -R 1000:1000 "$DEPLOY_PATH/data" "$DEPLOY_PATH/staticfiles"
```

### 4. Wire the subdomain into the central Caddy (habit_reward repo)
Paste the block from `deployment/caddy/dayforge.caddy` into habit_reward's
`Caddyfile`, commit/deploy there (or edit on the droplet), then reload:
```bash
docker exec habit_reward_caddy caddy reload --config /etc/caddy/Caddyfile
```

## Deploying
Push to `main` (or run the **Deploy** workflow manually). CI tests → builds →
pushes to GHCR → SSHes in → writes `.env` → `docker compose pull && up -d` →
health-checks `https://dayforge.habitreward.org/accounts/login/`.

## Rollback

On the droplet, pin the previous image tag in `.env` (`DOCKER_IMAGE=...`) and run
`docker compose pull && docker compose up -d`.

## Backups (manual)

Copying SQLite while the app is writing can corrupt the file. Prefer stopping
the stack or using SQLite's backup API:

```bash
# Option A: stop web, then scp
ssh <user>@<host> 'cd <DEPLOY_PATH> && docker compose stop web'
scp <user>@<host>:<DEPLOY_PATH>/data/day_forge.db ./day_forge-$(date +%F).db
ssh <user>@<host> 'cd <DEPLOY_PATH> && docker compose start web'

# Option B: online backup via Python stdlib (container running; no sqlite3 CLI in image)
# Write inside the container, copy to host /tmp, then scp — do NOT `docker cp ... -` to stdout
# (that streams a tar archive; redirecting to a .db file yields invalid SQLite).
ssh <user>@<host> 'docker exec day_forge_web python -c "
import sqlite3
from pathlib import Path
src = Path(\"/app/db/day_forge.db\")
dst = Path(\"/tmp/day_forge.db\")
with sqlite3.connect(src) as s, sqlite3.connect(dst) as d:
    s.backup(d)
"'
ssh <user>@<host> 'docker cp day_forge_web:/tmp/day_forge.db /tmp/day_forge-pull.db'
scp <user>@<host>:/tmp/day_forge-pull.db ./day_forge-$(date +%F).db
ssh <user>@<host> 'rm -f /tmp/day_forge-pull.db && docker exec day_forge_web rm -f /tmp/day_forge.db'
```
````

- [ ] **Step 2: Update `CLAUDE.md` Production Deployment section** — note that the WSGI/sync warning is resolved for the `dayforge.habitreward.org` deploy (now uvicorn ASGI, `--workers 1`), reference `deployment/` + `docs/features/0016_deploy_PLAN.md`, and that the middleware async-audit conclusion is "ship as-is (sync middlewares bridged, loop not blocked)".

- [ ] **Step 3: Update `RULES.md`** with the deploy gotchas:
  - `SECURE_PROXY_SSL_HEADER` is mandatory behind Caddy or `DEBUG=0` infinite-loops.
  - Docker/compose health probes to `http://localhost:8006/...` must send `X-Forwarded-Proto: https` **and** `Host: dayforge.habitreward.org` (`ALLOWED_HOSTS` rejects `localhost` with 400; proto alone still 301s without the header).
  - Prod is the `deployment/` stack; root `Dockerfile`/`docker-compose.yml` are dev-only.
  - Static path chain: Vite `frontend/dist` → `STATICFILES_DIRS` → `collectstatic` → WhiteNoise (no Caddy `file_server`).
  - SQLite lives at `/app/db/day_forge.db`; bind-mount `./data:/app/db` (host dir owned by uid 1000).
  - `:8006` must be restricted via **DOCKER-USER** iptables (ufw deny alone is insufficient); allow Docker-private source CIDRs (`172.16.0.0/12`), not `-i docker0` — Caddy uses Compose `br-*` bridges. Caddy reaches the app via `host.docker.internal` on the bridge — not `127.0.0.1:8006` binds.
  - First deploy: Caddy wired before CI HTTPS health-check passes.

- [ ] **Step 4: Update root `README.md`** with a short "Deploy" pointer to `deployment/README.md`.

- [ ] **Step 5: Commit**

```bash
git add deployment/README.md CLAUDE.md RULES.md README.md
git commit -m "docs(0016): deploy runbook + RULES/CLAUDE/README updates"
```

---

## Pre-flight verification (before first real deploy)

- [ ] Local image boots end-to-end with prod-like env:

```bash
docker build -f deployment/docker/Dockerfile -t day-forge:local .
docker network create dftest || true
docker run -d --name dfredis --network dftest redis:7-alpine
docker run -d --name day-forge-preflight --network dftest \
  -e DEBUG=0 \
  -e DJANGO_SECRET_KEY="$(python -c 'import secrets;print(secrets.token_urlsafe(50))')" \
  -e ALLOWED_HOSTS=localhost \
  -e CSRF_TRUSTED_ORIGINS=https://localhost \
  -e CALDAV_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet;print(Fernet.generate_key().decode())')" \
  -e REDIS_URL=redis://dfredis:6379/0 \
  -e LLM_API_KEY=dummy-key-for-boot \
  -e DJANGO_SUPERUSER_USERNAME=admin -e DJANGO_SUPERUSER_PASSWORD=adminpass \
  -p 8006:8006 day-forge:local
# Expect: migrations + collectstatic + superuser logs, then uvicorn running on :8006.
# In a second terminal (foreground `docker run` would block this shell):
curl -fsS -H "X-Forwarded-Proto: https" -o /dev/null -w "%{http_code}\n" \
  http://localhost:8006/accounts/login/
# → 200
# Deploy-blocking Django checks (same prod-like env as above):
docker exec day-forge-preflight python manage.py check --deploy
# Expected: exit 0 — no ai.E001 (Redis wired), no calendar_sync.E001 (Fernet key set).
docker rm -f day-forge-preflight dfredis; docker network rm dftest
```

Expected: `manage.py check --deploy` exits 0, uvicorn serves `/accounts/login/` 200 with the forwarded-proto header, the page loads the built `assets/app.js`/`app.css`.

- [ ] `git grep -n "habitreward\|8006\|dayforge"` in `deployment/` returns only intended references.

---

## Self-Review

**Spec coverage:** Host/subdomain (Tasks 6, 7, 10) ✓; uvicorn ASGI (Tasks 2, 5) ✓; AI+Redis (Task 6 redis service, env in Task 8) ✓; SQLite bind-mount (Tasks 5, 6) ✓; gated CI/CD (Task 8) ✓; superuser-only first boot (Task 4) ✓; OpenRouter (Tasks 8, 10 secrets) ✓; manual backups (Task 10) ✓; redirect-loop fix (Task 1) ✓.

**Open inputs from user (needed before deploy, not before implementation):**
- OpenRouter `LLM_BASE_URL` + `LLM_MODEL` + `LLM_DRAFT_MODEL` values (provided as secrets).
- Droplet `DEPLOY_PATH`, `SSH_USER`, deploy SSH key (provided as secrets).

**Risks / things that could break:**
1. `uv sync --no-dev` flag depends on how dev deps are declared (`[dependency-groups]` vs `[project.optional-dependencies]`) — verified in Task 5 Step 2; drop the flag if it errors.
2. `host.docker.internal` in the central Caddy requires `extra_hosts: ["host.docker.internal:host-gateway"]` on that Caddy service — already present in habit_reward's compose (confirmed during research).
3. Publishing `:8006` on `0.0.0.0` exposes the app to the host network → **DOCKER-USER iptables + ufw** are mandatory; ufw `deny 8006` alone does not block Docker-published ports (Task 10 §3). Allow rule must match Docker-private **source** CIDRs (`172.16.0.0/12`), not `-i docker0` — habit_reward Caddy uses Compose `br-*` bridges. Do not rely on `127.0.0.1:8006:8006` — breaks Caddy's `host.docker.internal` path on Linux.
4. `npm run build` runs `vue-tsc --noEmit` first — a type error fails the Docker build (good gate, but means TS errors block deploy; the CI `test` job catches it earlier).
5. SQLite + `--workers 1`: fine for current load; revisit (Postgres) if concurrency rises.
6. ~~Internal health checks missing `X-Forwarded-Proto` / `Host`~~ — **addressed** in Tasks 5, 6 (prod probes send both; pre-flight uses `ALLOWED_HOSTS=localhost`).
7. ~~Indented deploy heredoc writing spaces into `.env` keys~~ — **addressed** in Task 8 (Python writer + `scp` on runner; secrets in step `env:` only).
8. First CI deploy before Caddy is wired → HTTPS health-check fails until §4 of `deployment/README.md` is done.
