---
name: 0011 - Apple Calendar (CalDAV) read-only integration
description: Fetch and display Apple Calendar events via iCloud CalDAV alongside the daily schedule, with encrypted per-user credential storage and lazy, cached server-side fetch.
type: feature-plan
---

# 0011 - Apple Calendar (CalDAV) read-only integration

## Context

GitHub issue #23 — "Retrieve Apple Calendar events via CalDAV".

> Add support for retrieving events from Apple Calendar so Day Forge can show calendar commitments alongside the generated daily schedule. Apple Calendar/iCloud does not provide a Google-style OAuth Calendar API. The practical server-side integration path is CalDAV using the user's Apple ID email and an app-specific password.

Verbatim scope from the issue:

- Read-only Apple Calendar event retrieval via iCloud CalDAV.
- Connect with: Apple ID email, app-specific password, CalDAV base URL defaulting to `https://caldav.icloud.com/`.
- Fetch events for a given schedule date.
- Normalize events to: `title`, `start datetime`, `end datetime`, `calendar name`, `all-day flag`, `external UID`.
- Display imported events as external calendar commitments or busy blocks.
- Do not write changes back to Apple Calendar in the first version.
- Treat the app-specific password as a secret. Never log credentials. Do not commit credentials to `.env`. If stored per user, encrypt at rest.

Out of scope (verbatim): two-way sync; creating/updating/deleting Apple Calendar events; full recurring-event editing; Google/Microsoft calendar integrations.

Acceptance criteria (verbatim): user can configure CalDAV credentials; backend fetches events for a selected date; events visible without mutating `TimeBlock` data; invalid credentials return a clear error; network/provider failures handled without crashing the schedule page; tests cover successful fetch, invalid credentials, empty calendar day, and provider failure.

Clarified decisions:

- Credentials stored per user, encrypted at rest with `cryptography.Fernet` keyed by a new `CALDAV_ENCRYPTION_KEY` env var.
- One CalDAV account per user (`OneToOneField`).
- Events fetched lazily from the schedule page (not in the Inertia render path) so iCloud latency cannot block first paint.
- Server-side per-(user, date) cache to keep iCloud round-trips bounded.
- Date-range fetch is single-day only in V1, matching the schedule view.

## Dependencies

Add to `pyproject.toml` via `uv add`:

- `caldav` — high-level CalDAV client (DAV discovery, principal/calendar listing, time-range queries).
- `icalendar` — iCalendar (RFC 5545) parsing.
- `recurring-ical-events` — expands `RRULE`/`EXDATE`/`RDATE` into concrete instances for a given window.
- `cryptography` — Fernet symmetric encryption for stored credentials (already a transitive dep; add as direct).

## New Django app: `backend/calendar_sync/`

Mirrors the layout of `backend/ai/` and `backend/analytics/`.

Files to create:

- `backend/calendar_sync/__init__.py`
- `backend/calendar_sync/apps.py` — `CalendarSyncConfig`, registers system checks.
- `backend/calendar_sync/models.py` — `CalDAVAccount` model (details below).
- `backend/calendar_sync/crypto.py` — `encrypt_password(plaintext) -> bytes` / `decrypt_password(ciphertext) -> str` using `cryptography.fernet.Fernet`. Loads the key from `settings.CALDAV_ENCRYPTION_KEY`; raises `ImproperlyConfigured` if unset.
- `backend/calendar_sync/service.py` — CalDAV client wrapper. Functions:
  - `verify_credentials(apple_id, password, base_url) -> None` — opens a `caldav.DAVClient`, fetches `principal()`, lists calendars; raises typed errors on auth failure / network failure / timeout.
  - `fetch_events_for_date(account: CalDAVAccount, target_date: date) -> list[NormalizedEvent]` — opens client, enumerates calendars, runs `calendar.date_search(start, end, expand=True)`, falls back to manual `recurring-ical-events.of(...)` expansion if the server returns master components, normalizes to a `NormalizedEvent` dataclass with fields `title`, `start`, `end`, `calendar_name`, `all_day`, `external_uid`.
  - Typed exception hierarchy: `CalDAVError` (base), `CalDAVAuthError`, `CalDAVTimeoutError`, `CalDAVProviderError`. Views translate these to HTTP status codes.
- `backend/calendar_sync/schemas.py` — request/response shapes for the API (input validation for `POST /api/calendar/account/`).
- `backend/calendar_sync/views.py` — endpoints (details below).
- `backend/calendar_sync/cache.py` — versioned cache wrappers around `django.core.cache.cache`. Key shape: `caldav_events:{user_id}:{account_version}:{date_iso}`, where `account_version = account.updated_at.isoformat()` (microsecond precision). **Do not use integer-second precision** — two POSTs inside the same second would reuse the same cache key and the second request would serve the first's events. Django's `DateTimeField(auto_now=True)` stores microseconds, so `isoformat()` produces a `YYYY-MM-DDTHH:MM:SS.ffffff[+TZ]` string that changes on every save (modulo clock-skew within a worker — acceptable for cache purposes). TTL `settings.CALDAV_CACHE_TTL_SECONDS` (default 300). Versioning replaces the previous "invalidate next 7 days on delete" hack:
  - **Credential / base-URL change** (POST): `account.save()` bumps `updated_at` via `auto_now=True`. The new key is computed by the next read, so old keys become unreachable and expire via TTL.
  - **Account deletion** (DELETE): the row is gone, so the user has no `caldav_account` to read; future event fetches return `503` rather than hitting any cache key, and old keyed entries are *unreachable* (not "bumped" — the row no longer exists) and expire via TTL. If the user later re-creates the account, the new row gets a fresh `updated_at`, so prior cached entries are still unreachable from the new key.
  - **`auto_now=True` footgun**: this only fires when `updated_at` is actually written. `account.save(update_fields=[...])` that omits `updated_at` from the list bypasses `auto_now` and the cache key stays the same — serving stale events. Implementation rule: account-mutation paths in `views.py` MUST either call plain `account.save()` (no `update_fields`) OR include `"updated_at"` in the `update_fields` list. Document this in the docstring of `CalDAVAccount.set_password` and the POST endpoint. Test #14 (`test_cache_invalidates_on_account_update`) regression-catches the runtime symptom; the docstring catches it at code-review time.
  - Functions: `events_cache_key(account, target_date)`, `get_cached_events(account, target_date)`, `set_cached_events(account, target_date, events)`.
- `backend/calendar_sync/checks.py` — two Django system checks, mirroring `backend/ai/checks.py`:
  - `calendar_sync.W001` (**Warning**, not `Error`) — when `DEBUG=False` AND a `CalDAVAccount` row exists, warn if `CACHES['default']['BACKEND']` is one of three "ineffective for this feature" backends: `LocMemCache` (per-process — each worker re-hits iCloud), `FileBasedCache` (per-host — each host re-hits iCloud), or `DummyCache` (no caching at all — every request hits iCloud). Shared backends like `RedisCache`/`MemcachedCache` are silent. **This is a performance concern, not a correctness one.** Versioned cache keys (see `cache.py` below) include `account.updated_at`, so credential rotation invalidates every worker's cache independently — no stale-event correctness risk regardless of cache backend. The remaining cost of an ineffective cache is that each gunicorn worker (or each request, under `DummyCache`) hits iCloud on its first lookup for a given `(user, date, version)`, multiplying baseline iCloud QPS. That's a perf/cost issue, not a security/correctness issue, so this is a `Warning` rather than the startup-blocking `Error` used by `ai.E001`. `ai.E001` does **not** cover the CalDAV case (early-returns on empty `LLM_API_KEY`, see `backend/ai/checks.py:32-33`), so a CalDAV-only deployment would silently ship without any cache warning at all.
  - **DB-access safety**: system checks run during `manage.py migrate` and `manage.py check`, and on the *first* migration the `calendar_sync_caldavaccount` table doesn't exist yet — a naive `CalDAVAccount.objects.exists()` raises `OperationalError`/`ProgrammingError` and blocks the migration. The check MUST wrap the `.exists()` call in `try / except (OperationalError, ProgrammingError): return []`. The `ai.E001` pattern doesn't have this problem because it only reads `settings`, never the DB — explicitly call this out so the implementer doesn't copy the AI pattern verbatim.
  - `calendar_sync.E001` — when `DEBUG=False`, require `CALDAV_ENCRYPTION_KEY` set. Loud `Error`-level failure at startup so a misconfigured prod deploy doesn't silently fall back to an empty key. Only reads `settings`, no DB query needed.
- `backend/calendar_sync/admin.py` — register `CalDAVAccount` (display `user`, `apple_id`, `base_url`, `last_verified_at`; **never** expose the encrypted password field in the admin form).
- `backend/calendar_sync/migrations/0001_initial.py` — `CalDAVAccount` table.
- `backend/tests/test_calendar_sync_*.py` — service + endpoint tests (details below).

### `CalDAVAccount` model

Fields:

- `user = OneToOneField(settings.AUTH_USER_MODEL, on_delete=CASCADE, related_name="caldav_account")`
- `apple_id = EmailField()`
- `password_encrypted = BinaryField()` — Fernet ciphertext; **never** rendered to JSON. No `__str__`/`__repr__` includes this field.
- `base_url = URLField(default="https://caldav.icloud.com/")`
- `last_verified_at = DateTimeField(null=True, blank=True)` — set on successful `verify_credentials`.
- `created_at = DateTimeField(auto_now_add=True)`
- `updated_at = DateTimeField(auto_now=True)`

Model `Meta`: no special ordering required. `OneToOneField` provides per-user uniqueness.

Model methods:

- `get_password() -> str` — decrypts via `crypto.decrypt_password`. Logs only `account.pk`, never the plaintext or ciphertext bytes.
- `set_password(plaintext: str) -> None` — encrypts via `crypto.encrypt_password`, assigns to `password_encrypted`. Caller must `save()`.

## Settings additions (`backend/day_forge/settings.py`)

Register the new app: append `"calendar_sync"` to `INSTALLED_APPS` after the existing `"ai"` / `"analytics"` entries. Without this, the migration won't be detected, the admin won't register, the models won't be picked up, and the system checks won't run.

Append after the existing `LLM_*` block:

- `CALDAV_ENCRYPTION_KEY` — Fernet key (URL-safe base64, 32 bytes). No insecure dev default. In `DEBUG=True` an empty value is permitted but `CalDAVAccount.set_password` raises `ImproperlyConfigured` on use.
- `CALDAV_DEFAULT_BASE_URL` — default `https://caldav.icloud.com/`.
- `CALDAV_REQUEST_TIMEOUT` — default `10.0` seconds. Hard cap on each CalDAV HTTP call to prevent hung iCloud connections from holding a worker (same risk profile as `LLM_REQUEST_TIMEOUT`).
- `CALDAV_CACHE_TTL_SECONDS` — default `300`. Per-(user, date) event-list cache window.

Shared-cache note: surfaced as `calendar_sync.W001` (warning, not blocker — see `checks.py` above). Versioned cache keys mean a per-process cache is a *performance* downgrade (one extra iCloud round-trip per worker per `(user, date, version)`), not a correctness risk. The existing `ai.E001` rate-limit check stays a hard `Error` because its bypass is a security issue; the CalDAV cache concern is not.

Document all four env vars in `.claude/rules/project.md` under the existing "Environment Variables" section.

## URL wiring (`backend/day_forge/urls.py`)

Add imports `from calendar_sync import views as calendar_views`. Add two routes (serving four method handlers in total) alongside the existing `api/ai/...` block:

- `path("api/calendar/account/", calendar_views.account, name="caldav_account")` — handles `GET`/`POST`/`DELETE`.
- `path("api/calendar/events/<str:date>/", calendar_views.events, name="caldav_events")` — `GET` only.

## API endpoints (`backend/calendar_sync/views.py`)

All endpoints `@login_required`, JSON request/response, `@require_http_methods` per method, CSRF-protected via Inertia's existing `X-XSRF-TOKEN` header.

**Error envelope contract**: every non-2xx JSON response uses the shape `{"errors": {"detail": "<human message>", ...}}`. This matches what `frontend/src/composables/useHttp.ts:77` actually reads — a bare `{"detail": "..."}` body collapses to "Server error (N)" in the UI. Per-field validation errors (e.g. malformed `apple_id`) use additional keys inside `errors`. **Every test that asserts a non-2xx response MUST assert the envelope shape**, not just the status code, so a regression to bare-`detail` is caught at unit-test time.

1. `GET /api/calendar/account/`
   - Returns `{"connected": bool, "apple_id": str | null, "base_url": str | null, "last_verified_at": iso8601 | null, "default_base_url": str}`. The `default_base_url` field always echoes `settings.CALDAV_DEFAULT_BASE_URL` (regardless of `connected`) so the Settings form can populate its "advanced — CalDAV base URL" input without hardcoding the default on the frontend. Never includes password fields.

2. `POST /api/calendar/account/`
   - Body: `{"apple_id": str, "password": str, "base_url": str (optional, defaults to `CALDAV_DEFAULT_BASE_URL`)}`.
   - Algorithm:
     1. Validate body shape; reject missing fields with `400` `{"errors": {"detail": "...", "apple_id": "...", ...}}`.
     2. Call `service.verify_credentials(apple_id, password, base_url)`. Map `CalDAVAuthError → 401`, `CalDAVTimeoutError → 504`, `CalDAVProviderError → 502` — all with the standard `{"errors": {"detail": "..."}}` envelope.
     3. On success: `upsert` the `CalDAVAccount` row for `request.user`, encrypt password via `set_password`, set `last_verified_at = now()`, then `account.save()` — plain save with no `update_fields`, OR include `"updated_at"` in `update_fields` if a partial save is unavoidable. The write must touch `updated_at` (see the `auto_now` footgun in the cache section), which advances the cache-key version and makes every prior cached event entry for this user unreachable across every date.
     4. Return the same shape as `GET`.

3. `DELETE /api/calendar/account/`
   - Deletes the row if present. Returns `{"connected": false, "apple_id": null, "base_url": null, "last_verified_at": null, "default_base_url": "..."}`. Cache invalidation is automatic by virtue of removing the read path: after deletion the user has no `caldav_account` for the events endpoint to load, so subsequent `GET /api/calendar/events/<date>/` returns `503` and never consults any cache key. Prior cached entries are unreachable (no code path computes their key) and expire naturally via TTL. If the user later re-creates the account, the new row gets a fresh `updated_at` and therefore a fresh key namespace — old entries remain unreachable. No explicit cache enumeration needed.

4. `GET /api/calendar/events/<date>/`
   - Algorithm:
     1. Parse `date` as `YYYY-MM-DD`; `400 {"errors": {"detail": "Invalid date format. Use YYYY-MM-DD."}}` on malformed.
     2. Load `request.user.caldav_account`; if missing, return `503 {"errors": {"detail": "No CalDAV account configured"}}`.
     3. Check `cache.get_cached_events(account, date)`. If hit, return cached list.
     4. Call `service.fetch_events_for_date(account, date)` — the **service** owns credential decryption (see Service layer note below). The view never touches `account.get_password()`. Map exceptions to the standard envelope:
        - `CalDAVAuthError → 401 {"errors": {"detail": "Invalid Apple Calendar credentials"}}`.
        - `CalDAVTimeoutError → 504 {"errors": {"detail": "Apple Calendar request timed out"}}`.
        - `CalDAVProviderError → 502 {"errors": {"detail": "Apple Calendar provider failure"}}`.
     5. Cache the normalized list under `events_cache_key(account, date)`. Return `{"events": [...]}` (2xx responses keep their natural shape — the `errors` envelope is non-2xx only).

Response event shape:

```
{
  "title": str,
  "start": iso8601,
  "end": iso8601,
  "calendar_name": str,
  "all_day": bool,
  "external_uid": str
}
```

## CalDAV fetch algorithm (`service.fetch_events_for_date`)

**Service boundary owns the secret**: `fetch_events_for_date(account, target_date)` is the only function that calls `account.get_password()`. Views pass the `CalDAVAccount` instance through; they never touch the plaintext. This keeps the decryption surface to a single file, makes the "credentials never logged" test (test #11 below) tractable, and prevents future view-layer refactors from accidentally leaking the password into request-logging or error-reporting middleware.

1. Convert `target_date` to a tz-aware `datetime` pair: `start = target_date 00:00` in the user's local timezone (V1: `settings.TIME_ZONE` since per-user TZ isn't stored), `end = start + 1 day`.
2. Decrypt the password via `account.get_password()` (only call site). Open `caldav.DAVClient(url=account.base_url, username=account.apple_id, password=<plaintext>, timeout=settings.CALDAV_REQUEST_TIMEOUT)`. Bind the plaintext to a local variable scoped to this function only.
3. Fetch `principal = client.principal()`. Wrap any `caldav.lib.error.AuthorizationError` as `CalDAVAuthError`; wrap `socket.timeout` / `requests.exceptions.Timeout` as `CalDAVTimeoutError`; wrap anything else as `CalDAVProviderError`.
4. Iterate `principal.calendars()`. For each calendar:
   - Attempt server-side expansion: `events = calendar.date_search(start=start, end=end, expand=True)`.
   - If the server returns master `VEVENT`s with `RRULE` still present (some iCloud calendars do), parse each `caldav.Event` into an `icalendar.Calendar` and pass to `recurring_ical_events.of(parsed).between(start, end)` to expand locally. **The exact parse path from `caldav.Event` to `icalendar.Calendar` is pinned by the Phase 0 spike below** — do not assume `event.icalendar_component` vs `event.vobject_instance` vs raw `event.data` until the spike commits a chosen accessor.
5. For each expanded `VEVENT`:
   - `external_uid = vevent["UID"]` + `RECURRENCE-ID` suffix if present (so each occurrence is unique).
   - `all_day = isinstance(dtstart.dt, date) and not isinstance(dtstart.dt, datetime)`.
   - Promote naive datetimes to `settings.TIME_ZONE` then convert to UTC for serialization.
   - `calendar_name = calendar.name` (fallback to URL path if absent).
6. Drop events that fall entirely outside `[start, end)` (defensive). Return list sorted by `start`.

Recurring events: only event-instance expansion within the requested day window. No editing UI, no exception handling beyond expansion. Master-only events with no occurrence inside the window are silently skipped.

## Frontend changes

### Composable `frontend/src/composables/useCalendar.ts` (new)

Mirrors `useDraft.ts` / `useAI.ts`. Exposes:

- `state` ref: `{ events: NormalizedEvent[], loading: boolean, error: string | null, connected: boolean }`.
- `fetchEvents(date: string)` — `GET /api/calendar/events/<date>/`. Maps 503 to `connected = false` (UI hides the panel and prompts a setup link). Maps 401 to a "credentials invalid — reconnect in Settings" message. Maps 502/504 to a generic "Calendar service unavailable" message.
- `fetchAccountStatus()` — `GET /api/calendar/account/`, used by both `Schedule.vue` (to decide whether to render the panel) and `Settings.vue`.

### Composable `frontend/src/composables/useCalendarAccount.ts` (new)

Used by Settings page only. Wraps `GET/POST/DELETE /api/calendar/account/`. Exposes `connect({apple_id, password, base_url})`, `disconnect()`, `status` ref.

### Component `frontend/src/components/ExternalEventsPanel.vue` (new)

Read-only display. Props: `events: NormalizedEvent[]`, `loading: boolean`, `error: string | null`, `connected: boolean`. Renders:

- When `!connected`: nothing (or a small dismissible hint in V1 — keep V1 simple, render nothing).
- When `loading`: skeleton list.
- When `error`: inline warning row with retry button (calls back to parent).
- When events present: list of read-only rows showing `title`, time range (or "All day"), and `calendar_name` as a subtle chip.

No drag, no edit, no completion checkbox. Distinct visual style from `TimeBlock.vue` to communicate "external / not editable".

### `frontend/src/pages/Schedule.vue` (edit)

- Import `useCalendar`. Call `fetchEvents(props.date)` on `onMounted` and on date change (mirroring how `useDraft` reacts to date).
- Render `<ExternalEventsPanel>` above the time-block list, or beside it on wide viewports (use existing `useViewport.ts` breakpoint pattern).
- Failure of the calendar fetch must not affect the rest of the page (catch is local to the composable).

**Stale-response guard** (`useCalendar.ts` and `useCalendarAccount.ts`): without it, a user who rapidly clicks 18→19→20 in `DateNavigator` can see events from day 18 render after they navigate to day 20 (XHR for 18 finishes last → `state.events` overwritten with stale list). The same risk exists in Settings during connect/disconnect spam.

**Plumbing prerequisite** — `frontend/src/composables/useHttp.ts:31` currently accepts `(url, method, body?)` only; it has no `signal` option. The stale-response guard CANNOT be added on top of `requestJson` as-is. Pick one of:
- **Option A (preferred)**: extend `requestJson` to `requestJson(url, method, body?, options?: { signal?: AbortSignal })`. Threads through to `fetch(..., { signal })` and lets `AbortError` propagate as a thrown rejection (the existing `try/catch` around `fetch` already maps generic network failures to `{ok: false, errors: {detail: "Network error..."}}`; add a branch that rethrows `AbortError` instead of mapping it, so callers can swallow it cleanly). One-line behaviour change, backward-compatible for every existing caller. Document in the `useHttp.ts` header comment alongside the existing CSRF note.
- **Option B**: keep `requestJson` untouched; write a local `requestJsonCancellable` wrapper inside `useCalendar.ts` that duplicates the CSRF + `{errors: ...}` envelope handling. Larger surface to maintain in sync — only choose this if Option A is rejected during review.

The plan assumes Option A; flag any deviation in the PR description.

**Per-operation cancellation, shared-state-scope commit guard**: each cancellable operation owns its own `AbortController` so a Settings POST doesn't cancel a Schedule `fetchEvents` (and vice versa). The **commit guard** (the "should I write to state" check) is keyed differently per composable:

- In `useCalendar.ts`, `fetchEvents` and `fetchAccountStatus` write to *disjoint* state slices, so each carries an independent commit token.
- In `useCalendarAccount.ts`, `connect`/`disconnect`/`fetchAccountStatus` all write to the **same** `status` slice, so naive separate per-op seqs let a later-resolving older write overwrite a newer one. But sharing **one** seq across reads AND writes is also wrong — it lets a read supersede a write (see scenario in `latestAccountWriteSeq` section below). The correct split: **writes share one commit seq** (`latestAccountWriteSeq`), **reads have their own seq** (`statusReadSeq`), and **reads additionally gate on whether any write committed during their flight** (`writeCompletionTick`). Cancellation `AbortController`s remain per-operation. Full design follows.

Concrete refs:

- `useCalendar.ts`:
  - `eventsAbortController: Ref<AbortController | null>` — controls `fetchEvents` lifetime only.
  - **Two commit tokens for `fetchEvents`** (both required — date alone is insufficient because two requests for the same date can interleave via retry, `onMounted` + `watch` double-trigger, or refetch after a status change):
    - `latestRequestedEventDate: Ref<string | null>` — assigned on entry, checked on response. Catches the cross-date race (D1 → D2 → D1 resolves last).
    - `eventsRequestSeq: Ref<number>` — incremented and captured on entry, checked on response. Catches the same-date race (D2 → D2-retry → first D2 resolves last).
    - Commit gate: `expectedDate === latestRequestedEventDate.value && seq === eventsRequestSeq.value`. Both must hold; either alone leaks one of the two races.
  - `accountStatusAbortController: Ref<AbortController | null>` — controls `fetchAccountStatus` lifetime only.
  - `accountStatusRequestSeq: Ref<number>` — incremented and captured on each `fetchAccountStatus` call; response commits only if `seq === accountStatusRequestSeq.value` at resolution time.
- `useCalendarAccount.ts`:
  - **Server-side mutation race is NOT solvable by client-side abort alone**. The commit-token guard prevents the UI from rendering a stale POST response, but it cannot undo a write Django has already committed. Scenario: user clicks Connect → POST starts → user clicks Disconnect → DELETE starts → server processes POST first (or POST has shorter round-trip) → DB row exists → DELETE arrives → DB row deleted → DELETE response returns first, UI flips disconnected → POST response returns later, UI drops it (correct) — **but the database transient state briefly contained the row, and the eventual state is correctly disconnected because DELETE was processed after POST**. *Reverse* the network ordering, though: POST arrives at Django **after** DELETE → POST creates the row → final DB state = connected, contrary to user's latest intent (disconnect). Client-side `controller.abort()` is not guaranteed to stop a request Django has already accepted.
  - **Mitigation: UI-level serialization** of mutating account operations. Introduce `accountOperationInFlight: Ref<"connect" | "disconnect" | null>`. Rules:
    - On entry into `connect` or `disconnect`: if `accountOperationInFlight.value !== null`, **reject the call** (return `{ok: false, errors: {detail: "Another account operation is in progress. Please wait."}}` — no network call made). Otherwise set the ref to the operation name.
    - On resolution (success, failure, or abort), clear the ref back to `null`.
    - The Settings form binds `disabled` on both Connect submit and Disconnect button to `accountOperationInFlight.value !== null`. The user cannot start a second mutation while one is in flight — eliminating the server-side race at the source.
    - `fetchAccountStatus` is read-only and does not **set** the lock, but it **does** read it: while `accountOperationInFlight.value !== null`, the read returns immediately without making a network call (the in-flight mutation's response will be the authoritative next status update — no value in reading mid-mutation). See `writeCompletionTick` below for the belt-and-suspenders guard that catches reads that squeak past the lock check via a lifecycle quirk.
  - Three independent `AbortController` refs: `connectAbortController`, `disconnectAbortController`, `statusAbortController` — for cancellation only (e.g. component unmount, or to release the network slot when the user navigates away).
  - **Separate commit tokens for reads vs writes** (a shared one lets a read supersede a write — see scenario below). Concretely:
    - `latestAccountWriteSeq: Ref<number>` — incremented and captured on entry to `connect` / `disconnect`. Write responses commit only if their captured seq matches.
    - `statusReadSeq: Ref<number>` — incremented and captured on entry to `fetchAccountStatus`. Read responses commit only if their captured seq matches AND no write has completed since the read started (see `writeCompletionTick` below).
    - `writeCompletionTick: Ref<number>` — bumped at the very end of any committed write response (success OR failure that updates state). On entry to `fetchAccountStatus`, capture `tickAtEntry = writeCompletionTick.value`; on response commit, require `tickAtEntry === writeCompletionTick.value`. If a write committed during the read, drop the read (the write already updated `status` to a more authoritative value).
    - **Reads also bounce off the serialization lock**: while `accountOperationInFlight.value !== null`, `fetchAccountStatus` returns immediately without making a network call (no point reading state mid-mutation — the mutation response will be the authoritative next update). This eliminates the race at the source for the common path; `writeCompletionTick` is the belt-and-suspenders for the case where a read squeaked through (e.g. component lifecycle quirk fires `fetchAccountStatus` in the same tick as the mutation submit).
  - **Why a shared seq across reads and writes is wrong**: scenario — `connect()` enters → `seq = ++shared = 1`, POST in flight. `fetchAccountStatus()` enters → `seq = ++shared = 2`, GET in flight reads the *pre-mutation* state. GET resolves first → its seq (2) matches current (2) → commits **disconnected** state. POST resolves → its seq (1) ≠ current (2) → dropped as "stale". UI stays disconnected even though the server is connected. The fundamental error is letting a read (older state observation) bump the token that gates writes (newer state intent). Reads must never supersede writes.
  - The `fetchAccountStatus` instance here is **separate from** the one in `useCalendar` — each composable owns its own controllers + seqs. (Settings page and Schedule page each manage their own copy of the status.)

Implementation rules:

1. **On entry**:
   - For `connect` / `disconnect` in `useCalendarAccount`: check the serialization lock first — if `accountOperationInFlight.value !== null`, reject (see lock rules above). Otherwise set the lock to the op name.
   - For `fetchAccountStatus` in `useCalendarAccount`: also check the lock — if `accountOperationInFlight.value !== null`, return immediately with no network call (the in-flight mutation's response will be the authoritative next update). `fetchEvents` and `fetchAccountStatus` in `useCalendar` skip this lock entirely (they don't write account state).
   - Abort prior controller for this op: `<op>AbortController.value?.abort()`. Assign a fresh `AbortController` to `<op>AbortController.value`.
   - Capture the commit token(s) for this op:
     - `fetchEvents`: `latestRequestedEventDate.value = date` AND `const seq = ++eventsRequestSeq.value`. Local `expectedDate = date`. Both tokens are required on the commit gate.
     - `fetchAccountStatus` (in `useCalendar`): `const seq = ++accountStatusRequestSeq.value`.
     - `connect` / `disconnect` (in `useCalendarAccount`): `const seq = ++latestAccountWriteSeq.value`.
     - `fetchAccountStatus` (in `useCalendarAccount`): `const seq = ++statusReadSeq.value` AND `const tickAtEntry = writeCompletionTick.value`. Both required on the commit gate (see step 3).
2. **Make the call**: `requestJson(url, method, body, { signal: <op>AbortController.value.signal })`. For GETs (no body), pass `undefined` as the third positional arg so the options object lands in the fourth slot — see "GET call shape" note below.
3. **On resolution, before mutating state**:
   - `fetchEvents`: commit only if `expectedDate === latestRequestedEventDate.value && seq === eventsRequestSeq.value`. Both checks required.
   - `fetchAccountStatus` (in `useCalendar`): commit only if `seq === accountStatusRequestSeq.value`.
   - `connect` / `disconnect`: commit only if `seq === latestAccountWriteSeq.value`. On commit, **before** any other state writes, increment `writeCompletionTick.value++` so any concurrently-resolving read knows a write landed.
   - `fetchAccountStatus` (in `useCalendarAccount`): commit only if `seq === statusReadSeq.value && tickAtEntry === writeCompletionTick.value`. The second clause is the critical one — if any write committed while the read was in flight, drop the read (the write already updated `status` to the authoritative post-write value, and the read's payload is by definition pre-write).
   - If the check fails, return silently — do **not** clear `loading`, do **not** write `error`; the most-recent operation owns those.
4. **Always-run cleanup (regardless of commit check outcome)**:
   - `connect` / `disconnect`: clear `accountOperationInFlight.value = null` in a `finally` block so the controls re-enable. This MUST happen even when the commit guard drops the response, otherwise the lock could leak and disable the UI permanently after a stale response is dropped.
5. **AbortError handling**: a thrown `AbortError` (from `fetch`'s aborted promise) is swallowed silently. Do not clear `loading` from the aborted op either — the superseding op already manages its own `loading` flip. The `finally`-block lock cleanup from rule 4 still runs.

**GET call shape with the extended `requestJson`**: the extended signature is `requestJson(url, method, body?, options?: { signal?: AbortSignal })`. For GETs, the third positional is `undefined`, not the options object:

```
// Correct
requestJson("/api/calendar/events/2026-05-19/", "GET", undefined, { signal })

// WRONG — sends {signal: ...} as the JSON request body
requestJson("/api/calendar/events/2026-05-19/", "GET", { signal })
```

If this footgun feels too easy to trip over, add overloaded signatures in `useHttp.ts` (`requestJson(url, "GET", options?)` and `requestJson(url, method, body, options?)`) — Option A1. Otherwise the positional-`undefined` discipline is sufficient — Option A. Default to A; A1 only if review pushes back. Document whichever lands in the `useHttp.ts` header comment.

Frontend tests — out-of-order coverage MUST include:

In `frontend/tests/useCalendar.test.ts`:
- Two `fetchEvents` calls for *different* dates (`D1` then `D2`); resolve `D1` after `D2`; assert `state.events` matches `D2`'s payload (cross-date race).
- Two `fetchEvents` calls for the *same* date (e.g. retry, or `onMounted` + `watch` double-trigger); resolve the first call after the second; assert `state.events` matches the second call's payload (same-date race — regression-catches a date-token-only guard).
- One `fetchEvents` + one `fetchAccountStatus` interleaved; resolve in mixed order; assert **both** complete cleanly and neither cancels the other (regression-catches the shared-controller bug).
- A `fetchEvents` aborted mid-flight by a subsequent `fetchEvents`; assert no `AbortError` leaks into `state.error`.

In `frontend/tests/useCalendarAccount.test.ts`:
- **Serialization lock**: start `connect()`; while it's pending, call `disconnect()`; assert the `disconnect` call returns an error response *without* making a network call (lock rejection), and `accountOperationInFlight` is `"connect"` for the lock duration.
- **Lock release on success**: `connect()` resolves successfully → `accountOperationInFlight === null` → `disconnect()` is now accepted.
- **Lock release on failure / abort**: `connect()` rejects (network error, 401, AbortError) → `accountOperationInFlight === null` (lock cleared in `finally`) → `disconnect()` is accepted. Regression-catches a lock-leak bug that would freeze the UI.
- **Commit-token belt-and-suspenders** (programmatic bypass of the lock): manually invoke two `connect`s in quick succession by temporarily nulling the lock between them; resolve in reverse order; assert the older response is dropped (status reflects the newer response). Confirms `latestAccountWriteSeq` works even if the lock is somehow bypassed.
- **Read cannot supersede a write** (regression test for the shared-seq bug fixed in this design): start `connect()`; while it's pending, call `fetchAccountStatus()` — assert it is **rejected without a network call** (lock blocks it). Resolve `connect()` successfully; assert `state.status` reflects connected. The read must never have a chance to overwrite the write.
- **Late read after committed write is dropped** (belt-and-suspenders for `writeCompletionTick`): bypass the lock (e.g. temporarily null it for the test, or call the internal function directly) to start a `fetchAccountStatus()` *first*, then while it is pending, start and resolve a `connect()`. The connect commits and bumps `writeCompletionTick`. Now resolve the still-in-flight status read with stale pre-connect data; assert the read is **dropped** (its `tickAtEntry !== writeCompletionTick.value`) and `state.status` remains connected. Confirms the tick guard catches the lock-bypass case.
- **Status read while idle is allowed**: with no mutation pending, `fetchAccountStatus()` runs normally and commits its response. Confirms the lock doesn't accidentally block the happy path.

### `frontend/src/pages/Settings.vue` (edit)

Add a new "Apple Calendar" section below the existing template/rules editors. Inside it:

- Status badge ("Connected as alice@example.com" / "Not connected").
- Form fields: Apple ID (email), App-specific password (`type="password"`, never pre-populated even when connected), CalDAV base URL (advanced — collapsed by default, populated with `default_base_url` from the `GET /api/calendar/account/` response — never hardcoded on the frontend, so a backend default change rolls out without a frontend redeploy).
- Submit button → `useCalendarAccount.connect(...)`. Disable on submit. Show inline error from API.
- "Disconnect" button (when connected) → `useCalendarAccount.disconnect()`.

Help text: "Use an [Apple ID app-specific password](https://support.apple.com/en-us/HT204397). Day Forge never reads two-factor codes." (Static link text only; no outbound fetch from the form.)

### Types

Add `NormalizedEvent` to `frontend/src/types/` (new file `calendar.ts` or extend the existing types index — match whatever pattern `frontend/src/types/` already uses).

## Tests (`backend/tests/test_calendar_sync_*.py`)

**Test location follows the repo convention** (`Makefile:71`, `CLAUDE.md:20`, `AGENTS.md:18`, `README.md:104`): all backend tests live under `backend/tests/` and run via `uv run pytest backend/tests/ -v`. An app-local `backend/calendar_sync/tests.py` would be **silently skipped** by the project test command. Split the cases below across files that mirror the existing AI pattern (`test_ai_service.py` / `test_ai_views.py` / `test_ai_views_chat.py`): e.g. `test_calendar_sync_service.py` (service-layer tests #1–#7, #11), `test_calendar_sync_views.py` (endpoint tests #8–#10, #12–#15), `test_calendar_sync_checks.py` (system-check tests #16–#20).

Mock the `caldav.DAVClient` at the boundary (not the HTTP layer) so tests are deterministic and offline. Cover the four acceptance-criteria scenarios plus the recurrence path:

1. `test_fetch_success` — mock client returns two `VEVENT`s, one all-day and one timed; assert normalized output shape and ordering.
2. `test_fetch_invalid_credentials` — client raises `AuthorizationError`; assert service raises `CalDAVAuthError` and endpoint returns `401` with the expected message.
3. `test_fetch_empty_day` — mock client returns `[]` from `date_search`; assert endpoint returns `{"events": []}` with `200`.
4. `test_fetch_provider_failure` — client raises a generic `caldav.lib.error.DAVError`; assert `CalDAVProviderError` and endpoint returns `502`.
5. `test_fetch_timeout` — client raises `requests.exceptions.Timeout`; assert `CalDAVTimeoutError` and endpoint returns `504`.
6. `test_recurring_event_expansion` — mock returns a master `VEVENT` with daily `RRULE`; assert exactly one occurrence is returned for a single-day fetch and `external_uid` includes the `RECURRENCE-ID`.
7. `test_cache_hit` — first call hits the (mocked) client, second call within TTL does not.
8. `test_account_endpoint_post_persists_encrypted` — assert `password_encrypted` on the DB row is **not** the plaintext (round-trip via `Fernet.decrypt` matches).
9. `test_account_endpoint_get_never_returns_password` — JSON response shape contains no password-shaped fields.
10. `test_account_endpoint_post_invalid_credentials_does_not_persist` — `verify_credentials` raises auth error → no `CalDAVAccount` row is written.
11. `test_credentials_never_logged` — capture `logging` output across a successful flow and a failure flow; assert plaintext password substring is absent.
12. `test_events_endpoint_503_when_no_account` — user with no `CalDAVAccount` hitting `GET /api/calendar/events/<date>/` returns `503`.
13. `test_error_envelope_shape` — for every non-2xx case in tests #2, #4, #5, #10, #12 plus the malformed-date `400` path, assert the body has shape `{"errors": {"detail": <non-empty str>}}`. A regression to bare `{"detail": ...}` (which `useHttp.ts` silently swallows) fails here, not in production.
14. `test_cache_invalidates_on_account_update` — first call populates cache for `(user, date)`; `POST /api/calendar/account/` with new credentials; second call for the same date misses cache and re-fetches via the (mocked) client. Asserts versioned-key correctness — no stale events after credential rotation.
15. `test_cache_invalidates_on_account_delete` — same as #14 but via `DELETE`; subsequent `GET /api/calendar/events/<date>/` returns `503` (account gone), and re-creating the account starts with a cold cache.
16. `test_w001_warning_fires_with_locmem_and_account` — set `CACHES['default']['BACKEND'] = 'django.core.cache.backends.locmem.LocMemCache'`, `DEBUG=False`, create a `CalDAVAccount` row, run the check via `django.core.checks.run_checks`; assert a single `Warning` with id `calendar_sync.W001` is returned.
17. `test_w001_silent_with_no_account` — same cache backend + `DEBUG=False`, but no `CalDAVAccount` row; assert no `W001`. Confirms the gate (feature not in use → no noise).
18. `test_w001_fires_with_ineffective_backends` — parametrize over `LocMemCache`, `FileBasedCache`, and `DummyCache`. For each, `DEBUG=False` + `CalDAVAccount` row → assert a single `W001`. Confirms the three ineffective-backend cases all fire.
18b. `test_w001_silent_with_shared_cache` — `DEBUG=False`, `CalDAVAccount` row exists, but cache backend is `RedisCache` (or `MemcachedCache`, parametrized); assert no `W001`. Confirms shared backends pass the check.
19. `test_w001_swallows_db_error_during_first_migrate` — patch `CalDAVAccount.objects.exists` to raise `django.db.utils.OperationalError`; assert the check returns `[]` rather than propagating. Simulates the pre-`migrate` state where the table doesn't exist yet — without this guard, the first `manage.py migrate` would fail.
20. `test_e001_fires_when_encryption_key_missing_in_prod` — `DEBUG=False`, `CALDAV_ENCRYPTION_KEY = ""`; assert a single `Error` with id `calendar_sync.E001`. And the inverse: `DEBUG=True` OR key set → no `E001`.

Frontend tests live at `frontend/tests/` (verified by `ls`: `frontend/tests/ChatSidebar.test.ts`, `Schedule.test.ts`, etc. — there is no `frontend/src/__tests__/` directory). Add:

- `frontend/tests/useCalendar.test.ts` — mock fetch responses for 200/401/502/503/504 and assert state transitions; MUST also cover the out-of-order-response case described in the Schedule.vue section above (rapid date navigation → most-recent-date wins, regardless of resolution order).
- `frontend/tests/ExternalEventsPanel.test.ts` — render snapshot for connected/disconnected/loading/error states.
- `frontend/tests/useCalendarAccount.test.ts` — connect / disconnect / status round-trip; assert password is never echoed back from the status endpoint.

Manual test plan: `docs/features/0011_MANUAL_TEST.md` covering Settings connect, Settings disconnect, Schedule page with events, Schedule page with invalid creds, Schedule page with empty day, network failure simulation.

## Phasing

Phase 0 — `caldav` parse-path spike (must land before Phase 1 service work):
- Add `caldav`, `icalendar`, `recurring-ical-events` to `pyproject.toml` (via `uv add`).
- Write a single `backend/tests/test_caldav_parse_spike.py` that builds an in-memory `caldav.Event` (or its closest stand-in) from a recorded VEVENT-with-RRULE string and exercises whichever accessor (`event.icalendar_component`, `event.vobject_instance`, or `icalendar.Calendar.from_ical(event.data)`) yields a structure that `recurring_ical_events.of(...)` accepts.
- Commit the chosen accessor into the plan / service docstring as the canonical path. Until this test passes, treat the recurrence expansion in step 4 of the fetch algorithm as unverified.
- Out-of-scope for the spike: real network calls, the full normalization pipeline, the model — just the parse step.

Phase 1 — data layer and backend service:
- New app skeleton, `CalDAVAccount` model + migration, `crypto.py`, `service.py` (using the parse accessor pinned in Phase 0), `cache.py` (versioned-key implementation), `checks.py` (`calendar_sync.W001` warning + `calendar_sync.E001` error — **no `E002`**; the downgrade in the checks section collapsed two checks into one warning plus the encryption-key error), system check wiring, settings additions (including `INSTALLED_APPS += ["calendar_sync"]`), env-var docs in `.claude/rules/project.md`.

Phase 2A — API endpoints:
- `views.py`, URL wiring, backend tests (including envelope tests #13 and cache-invalidation tests #14/#15).

Phase 2B — Frontend (can run in parallel with 2A once the response schema is frozen):
- `useCalendar.ts`, `useCalendarAccount.ts`, `ExternalEventsPanel.vue`, edits to `Schedule.vue` and `Settings.vue`, frontend tests.

Phase 3 — manual test pass and documentation:
- `docs/features/0011_MANUAL_TEST.md` (new) covering the manual-smoke flows.
- `RULES.md` updates for any pitfalls discovered (e.g., iCloud DNS quirks, `expand=True` server-side support, the chosen `caldav.Event` accessor).
- `CLAUDE.md` (file exists, see its existing `## Production Deployment` section) — append a short note that the shared-cache *recommendation* now also affects `caldav_events:*` keys (perf only; surfaced as `calendar_sync.W001`, not a startup blocker). This is distinct from the existing `ai.E001` hard requirement and should be phrased as such, so the reader doesn't misread it as a new mandatory configuration.
- Env-var reference docs: `.claude/rules/project.md` (already done in Phase 1 — not re-touched here). Phase 3 does **not** add env-var docs to `CLAUDE.md`.
