---
paths:
  - "frontend/scripts/playwright/**"
  - "frontend/tests/**"
  - "backend/tests/**"
  - "backend/scripts/seed_*.py"
  - "frontend/scripts/playwright/README.md"
---

# Testing and browser smoke

## Browser smoke

Read [frontend/scripts/playwright/README.md](../../frontend/scripts/playwright/README.md) for prerequisites, provider calls and cleanup options. The application requires both development servers and a test account.

Run scripts serially because they share the test user's AI rate-limit counters. `make e2e` runs all scenarios; `make e2e-chat` and `make e2e-draft` select AI groups. Pass `--cleanup` to an individual script when its seeded schedules should be deleted after the run. Cleanup defaults off to preserve debugging evidence.

- Browser smoke scripts share `frontend/scripts/playwright/test-utils.mjs`. Seed via `backend/scripts/seed_*.py`, run a GET preflight, and register seeded dates for opt-in cleanup. `make e2e` is serial because scenarios share rate limits and data; some scripts call a real provider. Review `frontend/scripts/playwright/README.md` before running them. A script tied to one layout pins its theme with `pinTheme` and restores it; read day-window times from the page, since the `playwright` user's window (06:00–23:00) differs from unit-test fixtures (05:00–22:00); at 390 px the fixed chat dock covers the bottom of the viewport, so centre an element (`scrollIntoView({ block: "center" })`) before hit-testing it; seeders write to the running checkout's `db/`, so Django must run from the same checkout. For changes to locks or retries, include independent SQLite connections and a competing write reservation; lock spies alone prove only intent.

**`SEED_*` variables (feature 0039 — test-only, never read in production)**: the Playwright smoke harness passes scenario parameters to the `backend/scripts/seed_*.py` seeders as environment variables (never interpolated into Python source or the `shell -c` command) via `frontend/scripts/playwright/test-utils.mjs`'s `seed()` helper. They are consumed **only** by those seed scripts and by `backend/tests/test_seed_scripts.py`; no production code path reads them. `SEED_MODE` selects the seeder branch; `SEED_USERNAME` / `SEED_PASSWORD` identify (and, in `reset-ensure` mode, provision) the test user; `SEED_DATE` / `SEED_DATES_JSON` / `SEED_HISTORY_WITH_REVIEW` / `SEED_HISTORY_NO_REVIEW` target schedule dates; `SEED_SCHEDULES_JSON` / `SEED_BLOCKS_JSON` / `SEED_TEMPLATE_JSON` carry the JSON payloads to upsert; `SEED_SNAPSHOT` picks the audit read-back format; `SEED_MARKER` templates the confirmation line the `.mjs` script parses.
