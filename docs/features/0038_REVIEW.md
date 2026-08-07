# 0038 — Code Review

Feature: two fallback-literal guard tests for `useAnalytics.ts` (`markReviewed`
→ `"Could not mark this day reviewed."`, `saveNotes` → `"Could not save
notes."`). Test-only change; production code intentionally unmodified. Closes
the PR #128 tail item (`tasks/todo.md` line 174).

Scope: `frontend/tests/useAnalytics.test.ts` (+26 lines — one nested
`describe("useAnalytics fallback-literal guards")` with two `it()` tests).

## External review trail

**Engines:** OpenAI codex (`gpt-5.6-sol`, `--sandbox read-only`) + Cursor
agent (`--mode ask`). Run in parallel, independent prompts.

**Iterations:** 1/10.

### Iteration 1

- **codex** → `NO P1/P2 FINDINGS`, no P3s. (Its log contained test-run
  failures — `EPERM mkdir`, `__dirname is not defined` in `vite.config.ts` —
  which are artifacts of codex's own read-only sandbox, **not** code
  findings. The suite passes cleanly outside the sandbox.)
- **cursor** → `NO P1/P2 FINDINGS`, no P3s. Emitted a 14-row verification
  log, all rows `MATCH`, confirming: both literals pinned against production
  `useAnalytics.ts:36-38` / `:55-57`; `errJson(500, { errors: {} })` reaches
  the fallback via `errorMessage.ts:6-9` (`{}` truthy, no synthetic detail);
  local `fetch`/`errJson` mock style (not the `requestJson` mock used by the
  `useDraft.test.ts` sibling); nested `describe` inherits the outer
  `clearError()` so module-level `lastError` can't leak a false-green; both
  tests assert `result.ok === false` **and** the exact literal; existing
  tests untouched; `saveNotes` gains its first error-path coverage.

**Findings:** raised 0, accepted 0, rejected 0, P3-ignored 0.

**Fixes applied:** none (no valid findings).

**Verification:** `cd frontend && npm test -- useAnalytics` → 7/7 passed;
`npx vue-tsc --noEmit` → exit 0.

**Result:** SUCCESS — zero valid P1/P2 findings, tests + typecheck green.
