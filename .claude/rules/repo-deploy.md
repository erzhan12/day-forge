---
paths:
  - "deployment/**"
  - ".github/**"
  - "Dockerfile"
  - "docker-compose.yml"
  - ".dockerignore"
  - "frontend/public/**"
  - "backend/templates/base.html"
  - "backend/day_forge/settings.py"
  - "backend/day_forge/asgi.py"
  - "docs/features/0060_PLAN.md"
---

## Repository, secrets, and deployment

Secrets, GitHub Actions SHA pins, the image-retention CI check, and the no-merge-without-instruction rule live in [workflow.md](workflow.md).

- Production is the `deployment/` stack. TLS terminates at Caddy, so the forwarded-proto setting and production health-check headers are required. Build Vite assets and run `collectstatic` before serving them through WhiteNoise. Files in `frontend/public/` become public static assets; links in `backend/templates/base.html` need working development and production URLs. See `deployment/README.md`.
- The production Caddy config is deployed from the habit_reward repository, and its deploy overwrites manual server edits. A routing change in `deployment/caddy/dayforge.caddy` (`/mcp*` → `:8009`, catch-all → `:8006`) needs a matching pull request there, merged and deployed before the Day Forge deploy that depends on it; never hand-edit Caddy on the server. A 404 from `/mcp/health` most likely means that route is missing upstream. See step 4 of `deployment/README.md`.
