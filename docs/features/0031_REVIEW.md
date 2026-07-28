# Feature 0031 — Code Review Trail

## External review trail — /ext-code-review (2026-07-28)

**Engines:** codex (`gpt-5.6-sol`, read-only) + cursor (`agent --mode ask`), parallel.
**Scope:** feature 0031 change surface — `backend/{calendar_sync,gcal_sync}/views.py` +
their tests, `frontend/src/composables/{useCalendar,useGoogleCalendar,useExternalSourcePoll}.ts`
(+ tests), `frontend/src/pages/Schedule.vue`, `frontend/tests/Schedule.test.ts`, docs.
**Iterations:** 1 (converged).

### Findings

| # | Engine | Sev | Location | Verdict |
|---|--------|-----|----------|---------|
| 1 | codex | P2 | `useGoogleCalendar.ts:91,142-145` | **REJECTED** |
| 2 | codex | P2 | `useCalendar.ts:85-86,136-138` | **REJECTED** |
| 3 | codex | P3 | `gcal_sync/views.py:9` (E501) | **FIXED** |
| 4 | codex | P3 | `useExternalSourcePoll.test.ts` listener leak | recorded (non-blocking) |
| 5 | codex | P3 | `Schedule.test.ts` gate: no `connected&&!statusKnown` case | recorded (non-blocking) |
| 6 | codex | P3 | cache tests don't pin non-`"1"` refresh value | recorded (non-blocking) |
| 7 | cursor | P3 | twin inverted flag names `blankOnError`/`preserveOnError` | recorded (non-blocking) |
| 8 | cursor | P3 | `Schedule.vue` `defineExpose` test seam on large page | recorded (non-blocking) |
| 9 | cursor | P3 | mocked poller can't catch TDZ regression | recorded (non-blocking) |
| 10 | cursor | P3 | Google-only connected fan-out only covered negatively | recorded (non-blocking) |
| 11 | cursor | P3 | `deployment/README.md:40` interval note task-only | **FIXED** |

Cursor overall verdict: **NO P1/P2 FINDINGS** (16-row verification log, all PASS).

### Rejections (with evidence)

**#1 / #2 — "silent whole-request-failure blanks events when superseding a loading
request violates the plan."** Rejected. The `preserveOnError = silent && !state.loading`
guard is intentional and more correct than the plan's blanket "never blank on silent"
rule:
- Steady-state silent poll (`loading===false`) → preserves last-good events on
  whole-request failure. Matches plan intent (no panel flash on transient blips).
- Silent refresh superseding an **in-flight non-silent load** (`loading===true` — a
  date-change `fetchEvents` it just aborted at `_fetchEvents` line 81) → blanks. Correct:
  the new date's events never committed, so preserving would leave **prior-day events
  under the new date header**. The plan's mental model was steady-state only and did not
  consider the date-change race.
- Behavior is documented (`useGoogleCalendar.ts:71-76,89-91`), tested
  (`useGoogleCalendar.test.ts:321`; CalDAV analog `useCalendar.test.ts`), and matches
  prior established behavior. Codex's claim that the test "incorrectly codifies" the
  divergence is wrong — the test pins the intended race-safe behavior.

### Fixes applied

- **#3** `backend/gcal_sync/views.py:9` — docstring line was 105 chars (Ruff E501 >100),
  introduced by the `(?refresh=1 bypasses)` suffix. Dropped redundant "async" → 99 chars.
- **#11** `deployment/README.md:40` — env-var description broadened from "external-task
  sidebar refresh interval" to "external task + calendar background refresh interval"
  (the interval now also drives calendar `refreshEvents`).

Both fixes are docstring/markdown only — no runtime behavior change.

### Verification

- `uv run ruff check backend/calendar_sync/views.py backend/gcal_sync/views.py` → **clean**.
- Backend suite (`uv run pytest backend/tests/ -q`, run by codex mid-review) → **834 passed**.
  Not re-run after the fixes since they are non-runtime (docstring + markdown).

**Result: SUCCESS** — zero valid P1/P2, lint clean, tests green.
