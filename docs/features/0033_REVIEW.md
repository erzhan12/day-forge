# 0033 — External code review trail

Feature: suppress stale block-boundary notification burst after long same-day
suspension (issue #112). Plan: `docs/features/0033_PLAN.md`.

## External review (ext-code-review)

- **Engines:** codex (`gpt-5.6-sol`, read-only) + cursor (`agent --mode ask`).
- **Scope:** `git diff HEAD` — `useBlockBoundaryDetector.ts`,
  `useNowMinutes.ts`, `useBlockBoundaryDetector.test.ts`, plan docs
  (0019/0028/0033), `RULES.md`.
- **Iterations:** 1.

### Verdicts

- **codex:** `NO P1/P2 FINDINGS`. (First run overran its turn budget mid-
  exploration and emitted no verdict; re-run findings-only returned clean.)
- **cursor:** `NO P1/P2 FINDINGS`. Verified the clamp formula
  `effectivePrev = prev === null ? null : Math.max(prev, now - MAX_COALESCE_GAP_MINUTES)`,
  the half-open `(effectivePrev, now]` window, the off-today/backward/
  `prev === null` non-regression branches, and tests #18–#23 vs #7 unchanged.

### Findings

No P1/P2 from either engine. Two P3s (non-blocking, not actioned):

1. **P3** `useBlockBoundaryDetector.test.ts` — horizon `5` hardcoded in
   fixtures/comments rather than importing `MAX_COALESCE_GAP_MINUTES`.
   Mitigated: #20/#23 fail on a wrong horizon. Deliberate — plan uses literal
   minute values for readability.
2. **P3** `useBlockBoundaryDetector.test.ts` — plan's *optional*
   "visibility-resume = large tick jump ≡ #18" case not added; behaviour is
   already covered by #18 (detector reads only `nowMinutes`, never
   `document.hidden`). Documentary gap only.

### Verification

- `npm test -- useBlockBoundaryDetector`: **23/23 passed**.
- `npx vue-tsc --noEmit`: **clean**.
- No code changed during this review round (zero valid P1/P2).

**Result:** SUCCESS — zero valid P1/P2, tests + type-check green.

## claude-review bot (PR #123)

- **Verdict:** APPROVED. No P0/P1/P2. Two P3 polish items — both applied:
  1. Exported `MAX_COALESCE_GAP_MINUTES` and imported it in the test file;
     delta-driven ticks (#20/#23) now derive from the constant and a horizon
     guard test pins the literal-minute fixtures to `=== 5`.
  2. Added explicit visibility-resume case #24 (large tick jump ≡ #18),
     documenting the detector's `document`-agnostic architecture.
- **Verification after P3 fixes:** `npm test -- useBlockBoundaryDetector`
  **25/25 pass**; `npx vue-tsc --noEmit` clean.
