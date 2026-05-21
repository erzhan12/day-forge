# 0011 Code Review — Apple Calendar CalDAV

**Verdict:** Ready to merge. Implementation matches `docs/features/0011_caldav_apple_calendar_PLAN.md`; acceptance criteria are covered by automated tests. **No open findings** after the follow-up fixes in this pass.

## Plan compliance

| Area | Status |
|------|--------|
| Phase 0 spike (`test_caldav_parse_spike.py`, `icalendar_instance` pin) | Done |
| `calendar_sync` app (model, crypto, service, cache, checks, admin, views) | Done |
| Settings (`CALDAV_*`, `INSTALLED_APPS`, URLs) | Done |
| API envelope `{"errors": {"detail": ...}}` on all non-2xx | Done |
| Encrypted credentials; password never in JSON/admin | Done |
| Versioned cache keys + invalidation on POST/DELETE | Done |
| `calendar_sync.W001` (warning) + `calendar_sync.E001` (error) | Done |
| `useHttp` Option A (`signal`, `AbortError` rethrow) | Done |
| `useCalendar` / `useCalendarAccount` stale-response + write serialization | Done |
| `ExternalEventsPanel`, `Schedule.vue`, `Settings.vue` | Done |
| Backend + frontend tests per plan | Done |
| `0011_MANUAL_TEST.md`, `RULES.md`, `.claude/rules/project.md`, `CLAUDE.md` cache note | Done |
| `docs/api.md` Calendar (CalDAV) section | Done |

## Open findings

None.

## Resolved in this pass (follow-up to prior review)

### Resolved — `docs/api.md` Calendar section

- File: `docs/api.md` (feature 0011 section)
- Documents `GET/POST/DELETE /api/calendar/account/` and `GET /api/calendar/events/{date}/` with request/response shapes, status codes, and the `errors` envelope contract.

### Resolved — decryption misconfig returns 500, not 502

- Files: `backend/calendar_sync/service.py`, `backend/calendar_sync/views.py`
- `ImproperlyConfigured` from `get_password()` / decrypt propagates through the service (not wrapped as `CalDAVProviderError`) and is caught in `events()` → HTTP 500 with `"Calendar service is misconfigured. Contact the administrator."`
- Documented in `docs/api.md` for both POST (encrypt) and GET events (decrypt).
- Regression: `test_decryption_misconfig_returns_500_with_config_message`

## Resolved from earlier review

### Resolved — `date_search()` provider failures are no longer hidden

- Per-calendar `DAVError` propagates → `CalDAVProviderError` → 502 with standard envelope.
- Coverage: `test_fetch_per_calendar_dav_error_propagates`, `test_per_calendar_dav_error_returns_502_envelope`.

### Resolved — Account POST validates email and URL formats

- `validate_email` / `URLValidator`; empty `base_url` falls back to `CALDAV_DEFAULT_BASE_URL`.
- Coverage: `test_post_malformed_apple_id_returns_400_per_field`, `test_post_malformed_base_url_returns_400_per_field`, `test_post_empty_base_url_falls_back_to_default`.

## Test coverage vs plan

Plan tests #1–#20 plus the review follow-up (`test_decryption_misconfig_returns_500_with_config_message`) are in `backend/tests/test_calendar_sync_*.py` and `test_caldav_parse_spike.py`. Test #13 (error envelope) is satisfied via `_assert_envelope()` on every non-2xx assertion.

Frontend plan scenarios are in `frontend/tests/useCalendar.test.ts`, `useCalendarAccount.test.ts`, and `ExternalEventsPanel.test.ts`.

## Code quality notes

- **Service boundary:** only `fetch_events_for_date` calls `get_password()`; views pass the model through.
- **POST upsert:** plain `save()` so `updated_at` advances and cache keys rotate.
- **Style:** matches existing Django app + composable patterns (`ai/`, `useDraft.ts`, `useHttp.ts`).
- **`useCalendarAccount._internals`:** exposed for tests; Settings uses the lock ref for `disabled` — acceptable.

## Verification (this review)

```text
uv run pytest backend/tests/test_caldav_parse_spike.py \
  backend/tests/test_calendar_sync_service.py \
  backend/tests/test_calendar_sync_views.py \
  backend/tests/test_calendar_sync_checks.py -q
# 48 passed

uv run ruff check backend/calendar_sync/
# All checks passed

cd frontend && npx vitest run \
  tests/useCalendar.test.ts \
  tests/useCalendarAccount.test.ts \
  tests/ExternalEventsPanel.test.ts
# 20 passed
```
