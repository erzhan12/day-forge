# Playwright smoke harness

These 19 scripts exercise Day Forge through a real browser. They are smoke
scenarios rather than an isolated test suite: several call the configured LLM
or Todoist account, and all use the shared `playwright` Django user.

## Prerequisites

Start the full development stack in separate terminals:

```sh
make run
make frontend-dev
```

Create the local-only test user once. The known password and superuser status
make this command unsafe against any shared or production database:

```sh
uv run python backend/manage.py shell -c "from django.contrib.auth.models import User; u, _ = User.objects.get_or_create(username='playwright', defaults={'is_staff': True, 'is_superuser': True}); u.set_password('playwright-pw-do-not-use-in-prod'); u.save()"
```

The AI scenarios need `LLM_API_KEY` and the cache configuration required by
the backend. Todoist scenarios need `TODOIST_API_TOKEN` and
`TODOIST_ENCRYPTION_KEY`; `todoist-complete-refresh.mjs` also expects Redis.
`draft-prompt-history-suffix.mjs` needs
`LLM_DRAFT_CAPTURE_PROMPT_PATH=/tmp/draft_prompt_test7.txt` in the backend
environment followed by a Django restart.

## Running scripts

Run one script from `frontend/`:

```sh
cd frontend
node scripts/playwright/ai-chat-privacy-hint-always-on.mjs
```

Run every script, or an AI group, from the repository root:

```sh
make e2e
make e2e-chat
make e2e-draft
```

Always run them serially. The AI scripts share the user's draft and chat
rate-limit counters, the 409 scenario asserts those counters do not change,
and some seed dates collide (`ai-chat-clarifying-question` and
`regenerate-422-fallback` both use 2026-09-21). Each script resets its own
scenario safely when run in sequence; parallel runs can corrupt one another.

Pass `--cleanup` to delete schedules seeded by a script after the browser
closes. Cleanup is off by default so failed runs leave evidence in the local
database. Schedule-seeding scripts honor the flag; `template-editor-layout`,
`theme-switch-persistence`, and the two Todoist scripts do not seed schedules
and therefore have nothing to remove.

```sh
cd frontend
node scripts/playwright/timeblock-double-save.mjs --cleanup
```

## Cost and typical duration

Durations are rough local-development estimates. “LLM calls” counts the
scenario's intended provider requests; it is a more durable cost indicator
than a currency estimate because the configured model can change.

| Script | LLM calls | Typical duration / extra requirement |
|---|---:|---|
| `ai-chat-clarifying-question` | 2 | 30–90s |
| `ai-chat-clear-cancels-inflight` | 1 | 15–45s; includes controlled delays |
| `ai-chat-date-change-resets-thread` | 2 | 30–90s |
| `ai-chat-privacy-hint-always-on` | 0 | 5–15s; route is stubbed |
| `ai-chat-single-turn-apply` | 1 | 15–45s |
| `ai-chat-token-race` | 0 | 10–20s; both routes are stubbed |
| `ai-draft-409-on-non-empty` | 0 | 5–20s; pre-seeds today's row to suppress login auto-draft |
| `ai-draft-on-empty-day` | 1 draft | 30–90s |
| `analytics-unfreeze-on-edit` | 0 | 15–40s |
| `compact-timeline-stubs` | 0 | 5–15s |
| `draft-prompt-history-suffix` | 1 draft | 30–120s; prompt capture required |
| `regenerate-422-fallback` | 0 from its explicit 422 request | 10–60s; see auto-draft caveat below |
| `settings-topic-navigation` | 0 | 10–20s |
| `skipped-tasks-today-aware` | 0 | 5–20s |
| `template-editor-layout` | 0 | 15–40s; writes local screenshots |
| `theme-switch-persistence` | 0 | 10–30s |
| `timeblock-double-save` | 0 | 5–15s |
| `todoist-complete-refresh` | 0 | 15–60s; real Todoist task create/complete |
| `todoist-integration` | 0 | 15–60s; real Todoist connect/list/disconnect |

Login redirects to today's schedule. If that first visit creates today's
schedule and sets `auto_draft_pending`, it can independently trigger a real
draft call. The 409 script prevents that side effect by ensuring today's row
exists without changing an existing row. The regenerate script's explicit
pre-LLM 422 path still carries the auto-draft caveat, so keep today's local test
state controlled when measuring provider calls there.

## Harness layout and adding a scenario

- `test-utils.mjs` owns login, failure styles, the GET server preflight,
  CSRF POSTs, named waits, seeder invocation, and opt-in cleanup. Shared helper
  modules must be named `*-utils.mjs` — the `make e2e` glob skips that suffix so
  helpers aren't executed as smoke scripts.
- `backend/scripts/seed_*.py` contains importable, pytest-covered database
  setup. JavaScript passes values through `SEED_*` environment variables.
- `backend/tests/test_seed_scripts.py` guards row shape, exact stdout markers,
  parsing, timed operations, and idempotence.

For a new scenario, reuse the shared constants/helpers, call `await
preflight()` before seeding, add a parameterized seeder mode only when an
existing one cannot express the data shape, register every seeded schedule in
the `finally` cleanup call, and add the script to this cost table. Verify with
`node --check` and the relevant backend seeder test before running the browser.
