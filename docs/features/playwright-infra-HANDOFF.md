# Handoff: Playwright e2e harness infrastructure

## Your task

Improve the ergonomics and maintainability of the Playwright end-to-end smoke
scripts in `frontend/scripts/playwright/`. This is a **backlog cluster of 8
related follow-ups** (all raised by `claude-review` across PRs #11/#13/#14/#27),
tracked in `tasks/todo.md` lines 389–457. It is dev-tooling / test-infra work —
no user-facing product change.

Follow the project workflow in `/Users/erzhan/DATA/PROJ/CLAUDE.md` **exactly**:
Define → Research → **Plan (get explicit approval before editing code)** →
Implement on a feature branch → Verify → update `RULES.md` → confirm. Respect the
git discipline: create `feature/NNNN-slug` (next feature number — scan
`docs/features/` for the max `NNNN_PLAN.md`, currently 0103 is the max so use a
free number ≥ 0040), **never commit/push/merge without an explicit separate
instruction**, and prescribe TDD where a slice is testable.

## Ground truth (verified 2026-08-07 — trust this over the stale todo text)

- There are **21 `.mjs` scripts** in `frontend/scripts/playwright/`, not the "10"
  the todo mentions. The todo is stale; do not quote its count.
- A root **`Makefile` already exists** with `.PHONY` targets (`help`, `run`,
  `frontend-dev`, `test`, `check`, etc.) and a `help:` target that greps `##`
  doc-comments. There is **no `e2e` target yet** — add one that matches the
  existing style (target + `## description` so `make help` lists it).
- **No** `frontend/scripts/playwright/README.md` exists yet.
- **No** `backend/scripts/` directory exists yet.
- Every script hardcodes `BASE = "http://localhost:5173"` (21/21).
- Duplication is real but **inconsistent** (partial helpers already exist,
  copy-pasted with drift):
  - `fail` helper: ~15 scripts (`const fail` in 3, `function fail` in 12).
  - `preflight` helper: 5 scripts (the other 16 lack it → cryptic
    `ECONNREFUSED` when Django/Vite is down).
  - `login`: `async function login` in 3 (login logic is inlined/duplicated in
    the rest — goto `/accounts/login/`, fill `#username`/`#password`, read the
    `XSRF-TOKEN` cookie, send `x-xsrf-token` header).
  - `execSync` seed boilerplate: 20 scripts (multi-line
    `uv run python backend/manage.py shell -c "..."` template literals).
  - `waitForTimeout(...)` magic numbers across 15 scripts, values scattered:
    200(×3), 300(×2), 400(×6), 500(×4), 600(×2), 800(×3), 1200, 1500, 2000.

## Critical constraint — you CANNOT fully run these scripts in this environment

Most scripts drive the real app and make **real LLM calls** (need `LLM_API_KEY`
+ the full dev stack: Django on :8006 + Vite on :5173, per
`.claude/rules/workflows.md`). They also share per-user rate-limit counters and
**must run serially**. So:

- Do **not** try to execute the LLM scripts to "verify" a refactor here.
- For refactors that touch script files, verify by: `node --check <file>` (syntax),
  `cd frontend && npx vue-tsc --noEmit` (unaffected — scripts are `.mjs`, but run
  it anyway to confirm nothing else broke), and a careful read-diff that the
  extracted helper is behaviour-identical to what it replaced.
- Call out in your plan that final behavioural verification is a **manual
  step the user runs** (per the workflow's § Manual Testing) — list the exact
  command(s).

## The 8 items (verbatim intent from `tasks/todo.md:389–457`)

1. **Makefile target** — add `make e2e` (+ optional grouped `e2e:chat` /
   `e2e:command` / `e2e:draft`) so scripts are discoverable via `make help` and
   one-keystroke to run. *(PR #13)*
2. **`README.md`** in `frontend/scripts/playwright/` — prereqs (Django + Vite +
   the `playwright` test-user creation snippet), how to run individual scripts,
   per-script cost/duration (which make real LLM calls vs the `ai-draft-409`
   short-circuit that makes none), shared assumptions (seed dates, idempotent
   setup). *(PR #11/#13/#27)*
3. **Extract magic numbers** — named consts (`WAIT_FOR_PATCH_MS`,
   `LOGIN_POLL_MAX_TRIES`, etc.). More urgent now 15 scripts share inconsistent
   values. *(PR #13/#27)*
4. **`test-utils.mjs` shared helpers** — factor `login()`, `fail()`, seed
   `execSync` boilerplate, and the server preflight into one module so each
   script is just its scenario logic. **Touches every script — its own PR.**
   *(PR #13/#14)*
5. **Preflight server-reachable check** at the top of every script — a
   `fetch(BASE + "/accounts/login/", { method: "HEAD" })` with a clear "start
   them with `make run` / `make frontend-dev`" message instead of late
   `ECONNREFUSED`. Pairs with #4 (same shared file). *(PR #14)*
6. **`finally` cleanup behind a `--cleanup` flag (default off)** — delete the
   seeded schedules on exit only when asked; default-off preserves the DB for
   post-mortem inspection after a failed run. *(PR #14)*
7. **Extract Django shell seeds** to `backend/scripts/seed-*.py` (create the
   dir) so seeds are auditable/testable with real Python tooling instead of
   inline `execSync` template literals. The `test-utils.mjs` `seed()` helper
   would shell out to these. *(PR #14)*
8. **N+1 regression test for draft history** — a **backend pytest** (this one IS
   runnable + TDD-friendly, no browser): use
   `django.test.utils.CaptureQueriesContext` on
   `POST /api/ai/schedules/<date>/generate-draft/` with `LLM_HISTORY_DAYS=3` and
   assert the `analytics_dailyreview` query count is **1**, not N. Guards the
   PR #15 fix (`select_related("daily_review")` in the draft-history query in
   `backend/ai/views.py`). Replaces the `// TODO: N+1 sanity` comment in
   `ai-draft-on-empty-day.mjs`. *(PR #27)*

## Suggested phasing (propose your own in the plan; this is a starting point)

- **Phase A (standalone, TDD, no cross-script churn, ship first):** item #8 —
  the N+1 pytest. Red→green against the existing `select_related`. Low risk,
  independently mergeable. Will need to mock the LLM call (see how existing
  `backend/tests/test_ai_*` tests stub `openai.AsyncOpenAI` / the service layer)
  so the test hits the DB-query path without a real provider call.
- **Phase B (the harness refactor — biggest, one PR):** items #4 + #5 + #7 +
  #3 together — create `test-utils.mjs` (`login`, `fail`, `preflight`, `seed`,
  named wait/poll consts) and `backend/scripts/seed-*.py`, then migrate all 21
  scripts to import from them. This is the churny one; keep behaviour identical.
- **Phase C (docs + discoverability):** items #1 + #2 — `make e2e` target(s) +
  the README, written against the now-consistent Phase-B structure.
- **Phase D (small):** item #6 — the `--cleanup` flag in the shared `seed`/
  teardown helper.

Phases can be separate PRs (recommended — #4/#7 warned "defer to its own PR").
Confirm scoping with the user before implementing.

## Definition of done

- Each shipped phase: lint clean (`make lint`), typecheck clean
  (`make typecheck`), backend tests green (`make test-backend`) for Phase A,
  `node --check` clean on every touched `.mjs` for Phase B.
- The matching `tasks/todo.md` items flipped `[ ]`→`[x]` as each lands.
- `RULES.md` updated with the new harness layout (where `test-utils.mjs` and
  `backend/scripts/seed-*.py` live, how to add a new script, the `make e2e`
  entrypoint) so the next contributor doesn't re-derive it.
- The stale "10 scripts" note in the todo corrected or removed.

## Key references

- `tasks/todo.md:389–457` — the 8 source items with PR provenance.
- `.claude/rules/workflows.md` — § Manual Testing (browser smoke), the serial-run
  requirement, the `--noreload` variant.
- `/Users/erzhan/DATA/PROJ/CLAUDE.md` + `day-forge/CLAUDE.md` — workflow + git
  discipline (branch, no unprompted commit/merge, ff-merge only).
- `backend/ai/views.py` (`ai_generate_draft`) — the `select_related("daily_review")`
  the N+1 test guards.
- Existing `backend/tests/test_ai_*` — the LLM-stubbing pattern for Phase A.
