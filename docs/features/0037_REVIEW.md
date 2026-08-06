# 0037 — De-duplicate `extractErrorMessage` — Review

## External review trail

**Engines:** OpenAI codex (`gpt-5.6-sol`, read-only) + Cursor agent (`--mode ask`).
**Rounds:** 1 (converged — zero valid P1/P2).
**Scope:** 12 composables + 12 composable test files + 2 new files
(`frontend/src/utils/errorMessage.ts`, `frontend/tests/errorMessage.test.ts`).

### Findings

Both engines returned **NO P1/P2 FINDINGS**. All P3s below.

| # | Engine | Finding | Verdict |
|---|--------|---------|---------|
| 1 | both | `docs/features/0037_PLAN.md` not present in the branch worktree | **REJECT (non-code)** — the plan lives untracked on the main checkout; not a code defect. Will be committed alongside the feature. |
| 2 | codex | `errorMessage.ts` header comment said "first non-empty flattened value", but impl only inspects `flat()[0]` — an empty first value falls through to `fallback` even if a later key holds a non-empty string | **ACCEPT (doc)** — behaviour is intentional and copied verbatim from the 12 originals; reworded the comment to state the first-value-only semantics explicitly. No behaviour change. |
| 3 | codex | No test for a bare non-array scalar value (`{ field: "boom" }`), which the declared input type `Record<string, string \| string[]>` permits | **ACCEPT (test)** — added a unit case asserting `{ field: "boom" }` → `"boom"` (`flat()` leaves scalars). |
| 4 | cursor | `useDraft.test.ts` guard comment characterised 409 as "resolves via statusToMessage"; 409 actually early-returns in `generateDraft` before either helper runs | **ACCEPT (comment)** — reworded to `503/429/422 resolve via statusToMessage; 409 early-returns`. |

### Fixes applied (all P3, non-blocking)

- `frontend/src/utils/errorMessage.ts` — clarified header comment (first-value-only semantics; behaviour preserved).
- `frontend/tests/errorMessage.test.ts` — added scalar-value coverage case.
- `frontend/tests/useDraft.test.ts` — corrected the 409 characterisation in the guard-block comment.

### Reviewer-confirmed invariants

- All 12 composables migrated; each call site passes its **own** prior fallback literal (no swap — the swap-prone `useCalendar` "Calendar fetch failed" vs `useCalendarAccount` "Account operation failed" pair verified clean by cross-grep).
- All 16 fallback-literal guards genuinely reach the shared helper's fallback branch: status `500` hits every `statusToMessage` `default` (returns `null`) and, for Habitica/Todoist, satisfies `>= 401` so `state.error` surfaces past the panel gate; the two 503-ternary sites drive a non-503 status.
- `useAI` guard uses `errJson(500, { errors: {} })` — the real `requestJson` maps a body with no `errors` key to a synthetic `{ detail: "Server error (N)" }`, so the `{ errors: {} }` body is required to reach the fallback (author got this right).
- No user-visible error string changed. No data-shape (snake_case / nested `{data:{}}`) issues. No-semicolon style preserved.

### Verification

- `npm test` — **715 passed** (58 files).
- `npx vue-tsc --noEmit` — exit 0.

**Result: SUCCESS** — zero valid P1/P2; tests + type-check green.
