---
paths:
  - "backend/schedules/daily_export.py"
  - "backend/schedules/export_*.py"
  - "backend/tests/test_daily_export*.py"
  - "backend/tests/test_export_*.py"
  - "backend/tests/test_whoop_export_api.py"
  - "backend/tests/fixtures/daily_export/**"
  - "frontend/src/utils/dailyExport.ts"
  - "frontend/src/composables/useDailyExportToken.ts"
  - "frontend/src/components/DailyExportDialog.vue"
  - "frontend/src/components/settings/DailyExportTokenPanel.vue"
  - "frontend/tests/dailyExport.test.ts"
  - "frontend/tests/DailyExport*.ts"
  - "frontend/tests/useDailyExportToken.test.ts"
---

## Daily export and the personal export token (feature 0088)

- `backend/schedules/daily_export.py` (Python) and `frontend/src/utils/dailyExport.ts` (TypeScript) must render byte-identical Markdown. Both are exercised against the same JSON fixtures in `backend/tests/fixtures/daily_export/` (consumed by `uv run pytest` and by the Vitest contract via Node `fs.readFileSync`, not a Vite import) so the two implementations cannot silently drift. Note normalization matches ECMAScript `trim()`/`\s` exactly, not Python `str.strip()` — the two whitespace definitions disagree on U+0085 and U+001C–U+001F (Python treats these as whitespace; JavaScript does not) and on U+FEFF (JavaScript treats it as whitespace; Python does not by default).
- A personal export token authorizes reads on exactly the routes in `export_auth.BEARER_ROUTE_NAMES`: `GET /api/export/daily/{date}/` and, since feature 0107, `GET /api/export/whoop/{date}/`, so the token also unlocks WHOOP health summaries. Each view runs its own `export_auth.resolve_export_owner` check — never through `AUTHENTICATION_BACKENDS`, middleware, or a session established via `login()`. A Bearer header on any other `/api/` route, including `/api/user/export-token/` itself, must behave exactly like an unauthenticated request; it must never flip a rejected anonymous request into a success. `backend/tests/test_daily_export_api.py` enforces this with a matrix dynamically discovered from the live urlconf (so a newly added route is automatically covered, not silently skipped); its exclusions are that constant, so widening the token is a one-line change to review as a security decision.
- Only the SHA-256 digest of the full raw credential is ever persisted (`PersonalExportToken.token_digest`, unique); the raw value is returned exactly once, from a successful `POST /api/user/export-token/`, and is never recoverable afterward. One active token per user. Creation and revocation run through `run_user_maintenance`, serializing against the same per-user write lock as every other policy write; authentication re-reads current database state on every request, so revocation takes effect on the very next call — nothing caches a token's validity.
- The export read is owner-scoped through `schedules.reads.read_schedule_day`, the same shared snapshot helper the Schedule page GET uses for its block read. It captures the schedule and ordered blocks (`start_time`, `sort_order`, `id`) inside one read transaction, never creates rows, and never reserves the SQLite writer. An absent day returns a `200` empty report (`0/0`) rather than bootstrapping one. `today` resolves through `window.user_local_date_readonly`, a non-creating sibling of `user_local_date`/`get_schedule_settings` — it must not create a `UserScheduleSettings` row or reserve the writer either.
- The exported `note` field is always `""`. `DailyExportDialog.vue`'s note is transient, component-local UI state — the HTTP export never substitutes `DailyReview.notes` for it and never persists a note of its own. Do not add a note-persistence mechanism to this endpoint without a separate plan.
- Adding this feature changed no existing middleware, CSRF, or frontend-release behavior: `FrontendVersionMiddleware` and `InertiaIdentityMiddleware` apply to both new routes unchanged (headerless export GETs still work; an explicit stale `X-Frontend-Version` still returns `409`; `X-Schedule-User` still cannot select the owner on a GET). `/api/user/export-token/` keeps ordinary CSRF enforcement and session authentication — it is session-only specifically because it rejects Bearer, not because it is CSRF-exempt.
