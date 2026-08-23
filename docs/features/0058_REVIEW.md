# Feature 0058 — Code Review

## Review-fix-loop (staged fallback → `git diff HEAD`)

Nothing was staged; reviewed unstaged HEAD diff in
`.worktrees/feature-0058-pip-indicator-styles` on `feature/0058-pip-indicator-styles`.

**Files:** `RULES.md`, `frontend/src/components/FocusIndicatorView.vue`,
`frontend/src/composables/useFocusIndicator.ts`,
`frontend/tests/useFocusIndicator.test.ts` (plus untracked plan
`docs/features/0058_PLAN.md`).

**Iterations:** 1/3

**Criticals:** 0 found, 0 remaining.

**Warnings (not blocking):**

- `frontend/tests/useFocusIndicator.test.ts:329` — first-cut CSS assertions
  were unanchored substring matches and did not lock `CanvasText` /
  `currentColor` / button border (the actual blank-PiP regression).
- Same test: `"Standup with Bob"` cannot appear in a stylesheet; weak
  privacy lock. Existing 0049 integration test remains the real privacy gate.

**Info:** no SFC test that `<style scoped>` stayed deleted (acceptable: PiP
injection test is the load-bearing check).

**Result:** Ready to commit ✅ (zero criticals).

## External review trail (ext-code-review)

Engines: OpenAI Codex (`gpt-5.6-sol`), read-only. Cursor agent skipped
(user asked `only codex`). Plan: `docs/features/0058_PLAN.md`.

Previously-rejected findings carried in: none.

### Iteration 1

**Raised / deduped:**

1. **P3 (codex)** — `useFocusIndicator.test.ts:329`: test never asserted
   visibility-critical `CanvasText`/`Canvas`, `currentColor` fill, or
   button-border rules, so a regression recreating the blank dark PiP could
   still pass. **ACCEPTED (cheap).** Added those CSS matches plus a
   `.fi-complete` node assertion. Re-ran `npm test -- tests/useFocusIndicator.test.ts`
   (15 passed) then full `npm test`.

**Rejected:** none. **P1/P2:** none (`NO P1/P2 FINDINGS`).

## Verification

- `cd frontend && npm test -- tests/useFocusIndicator.test.ts` — 15 passed
- `cd frontend && npm test` — 76 files, 897 passed (after P3 tighten: 15/15
  on the touched file; full suite re-run after the test edit)
- Frontend lint script: none in `package.json` (no `eslint` target)

## Trace

```
ext-code-review trace
  scope: 5 files (4 modified + 1 untracked plan)
  engines: codex
  iterations: 1/10
  findings: raised 1, accepted 1 (fixed 1), rejected 0, P3-ignored 0
  verification: tests passed, lint n/a
  result: SUCCESS
```
