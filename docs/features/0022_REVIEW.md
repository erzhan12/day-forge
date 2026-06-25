# Feature 0022 — Code Review: Google Calendar via OAuth 2.0

**Reviewed:** staged working tree vs `docs/features/0022_PLAN.md`  
**Review date:** 2026-06-26 (re-review after fix pass)  
**Verification:**

- `uv run pytest backend/tests/test_gcal_sync_checks.py backend/tests/test_gcal_sync_service.py backend/tests/test_gcal_sync_views.py -q` — 69 passed
- `cd frontend && npm test -- --run useGoogleCalendar useGoogleAccount ExternalEventsPanel useCalendar` — 37 passed

## Verdict

**Approved for merge.** No Critical or Warning findings remain. All actionable items from the first review pass are fixed or correctly rejected. Residual items are acknowledged V1 trade-offs or optional cleanup.

### Independent re-review — 2026-06-26

Re-checked the current staged implementation against `docs/features/0022_PLAN.md`
and this review file. No new commit-blocking bugs were found.

Additional verification:

- `uv run pytest backend/tests/test_gcal_sync_checks.py backend/tests/test_gcal_sync_service.py backend/tests/test_gcal_sync_views.py -q` — 69 passed
- `cd frontend && npm test -- --run useGoogleCalendar useGoogleAccount ExternalEventsPanel useCalendar` — 37 passed
- `uv run ruff check backend/` — passed
- `cd frontend && npx vue-tsc --noEmit` — passed
- Real `google-auth-oauthlib` authorization URL construction was smoke-tested via `service.build_authorization_url(...)` with local test settings.

---

## Critical

None.

---

## Warning

None (all prior warnings resolved — see Fix Verification below).

---

## Suggestion

**`backend/gcal_sync/views.py:35-39`** — `_SERVICE_ERROR_STATUS` is defined but unused. The events view maps per-account failures into `account_errors[]`; connect/callback redirect instead of JSON error envelopes. Harmless dead code copied from the CalDAV skeleton; optional removal.

---

## Fix Verification (first review → this pass)

| ID | Finding | Status |
|----|---------|--------|
| W1 | Callback only caught `GoogleCalError` → raw 500 on unexpected `exchange_code` failures | **Fixed** — `views.py:106-112` `except Exception` → `?google=error&reason=provider` |
| W2 | Connect-time `_fetch_calendar_list_sync` fetched only page 1 | **Fixed** — `service.py:170-203` paginates with `_MAX_PAGES` ceiling |
| W6 | Whole-request Google error left stale `events` / `accountErrors` beside banner | **Fixed** — `useGoogleCalendar.ts:117-122` clears both |
| W7 | Settings never re-fetched after `?google=connected` | **Fixed** — `Settings.vue:136-140` second `fetchAccounts()` |
| S3 | `disconnect()` `AbortError` left `state.loading=true` | **Fixed** — `useGoogleAccount.ts:110-115` |
| S6 | `TestCredentialsNeverLogged` missing access-token ciphertext | **Fixed** — `test_gcal_sync_service.py:583-585` |
| W4 | Plan stale re `include_granted_scopes` | **Fixed** — `0022_PLAN.md:124` documents shipped deviation |
| W5 | `deployment/` missing E001 boot note | **Fixed** — `deployment/README.md:50-54` |
| Tests | `#` encoding, reconnect field update, mixed cache+auth failure, timeout→unavailable, Apple `account_label:""` | **Fixed** — +3 backend, +1 frontend tests (69 backend / 37 frontend total in scope) |

### Correctly rejected (not bugs)

| ID | Claim | Reason |
|----|-------|--------|
| W3 | E001 early-return skips client-var errors | **Invalid** — client-var loop runs before token-key check (`checks.py:86-123`); `test_fires_when_token_key_missing` + per-var tests cover multi-error emission |
| S4 | Reconnect CTA should link to `/connect/` | **Not a bug** — plan §3.5 allows Settings; better UX for multi-account |
| S5 | `.env.example` should list optional `GOOGLE_*` vars | **Not a bug** — matches CALDAV/TODOIST convention; optional defaults documented in `project.md` |

### Acknowledged, not done (acceptable cost/benefit)

| Item | Rationale |
|------|-----------|
| S1 — dead `except httpx.HTTPStatusError` in `fetch_events_for_account` | Harmless defensive guard; REST path uses `_raise_for_rest_status()` |
| Settings component test | Heavy mount; composable + panel tests cover the wiring |
| Schedule merge-sort test | Backend sort contract tested; `mergedExternalEvents` uses identical tuple |
| Concurrent `asyncio.gather` refresh test | Cross-thread DB in `sync_to_async`; persisted-token correctness tested via `_persist_refreshed_tokens` directly |

---

## Plan Compliance

### Backend (Phases 1, 2A, 2B)

- `gcal_sync` app, migration, settings block, URLs, admin, checks, crypto, model, cache, service, views.
- Multi-row `GoogleCalendarAccount` with Fernet encryption and token accessors.
- `NormalizedEvent.account_label` extension (wire-compatible with Apple empty sentinel).
- OAuth flow, id_token verify, paginated grant probe, access-token cache-then-refresh with locked persist + rotation double-check.
- Async multi-account events: `auser()`, `cache.aget`/`aset`, partial success `account_errors[]`, config-500 short-circuit.
- `gcal_sync.E001` / `gcal_sync.W001`; five routes; CSRF state; IDOR-safe DELETE.

### Frontend (Phase 3)

- Types, `useGoogleCalendar`, `useGoogleAccount`, merged `Schedule.vue` panel, non-suppressing `errorBanners`, dual chips + per-account banners in `ExternalEventsPanel`, Settings OAuth UX.

### Docs

- `.claude/rules/project.md`, `RULES.md`, `docs/api.md`, `deployment/README.md`, plan §2A.2 deviation note.

---

## Test Review

**Backend (69 tests)** — OAuth round-trip, refresh rotation + locked persist (including P1 rotation-when-fresh), access-token cache reuse, revoked grant, provider/timeout errors, cancelled-event skip, multi-calendar merge, all-day/timed normalization, `@` + `#` calendar-id URL encoding, credentials-never-logged (refresh + access ciphertext), state CSRF, missing code, callback upsert with field update on reconnect, multi-account fetch, partial success, mixed cache-hit + auth failure, timeout → `unavailable`, no-accounts 503, cache hit, `ImproperlyConfigured` 500, parsed-date contract, IDOR disconnect, E001/W001 checks.

**Frontend (37 tests in scope)** — `useGoogleCalendar` happy path, 503, partial `account_errors`, stale guard, whole-request stale clear; `useGoogleAccount` list/disconnect/redirect/serialization lock; `ExternalEventsPanel` dual chips, non-suppressing banners, `accountErrors`, `retry(provider)`; `useCalendar` `account_label: ""` fixture.

---

## Residual V1 Limitations (not regressions)

- **Warm cache after grant revocation** — versioned cache can serve events for up to `GOOGLE_CACHE_TTL_SECONDS` without surfacing `reconnect_required`. Same model as CalDAV.
- **Callback upsert after broad except** — `ImproperlyConfigured` on encrypt would 500 after a successful Google redirect in a misconfigured `DEBUG=True` env; blocked in prod by E001.
- **Session expiry mid-consent** — documented V1 limitation; user retries Connect after re-login.

---

## Prior review superseded

This document replaces the 2026-06-26 first-pass review. First-pass Warning items W1–W7 and test gaps are closed unless listed under Acknowledged above.
