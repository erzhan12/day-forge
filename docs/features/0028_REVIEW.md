# Feature 0028 — Desktop notifications — Code Review

## External review trail

**Engines:** codex (`--sandbox read-only`) + cursor agent (`--mode ask`).
**Rounds:** 1 (plus one cursor re-run — see below). **Scope:** 14 staged files
(5 new src, 2 changed src, Schedule/Settings wiring, 5 tests, RULES.md) + the
plan doc added during review.

### Local staged review (review-fix-loop-staged)
Two parallel category reviewers (code-quality/correctness, tests/docs). Both
returned **CLEAN** — zero criticals, zero warnings. No fixes required.

### Codex — 1 round
- **NO P1/P2 FINDINGS.**
- P3: stale-request race test covered only the late-`granted` result.
  **Accepted + fixed** — added a sibling late-`denied` test proving the
  unconditional guard also blocks the denied branch from stamping
  `permissionDenied=true` (`useDesktopNotifications.test.ts`).
- P3: comments reference `docs/features/0028_PLAN.md` which was "absent from
  the working tree". Root cause = the plan was an untracked file on `main` and
  did not carry into the fresh worktree. See cursor P2 below — resolved by
  committing the plan doc to the branch.

### Cursor — first run REJECTED (wrong project)
Cursor's first pass reviewed an unrelated FastAPI "workout motivation" codebase
(`workout_service.py`, `is_workout_motivation_active`) — nothing to do with Day
Forge. All findings discarded; re-run pinned to the worktree path + exact file
list.

### Cursor — re-run (correct repo)
- **NO P1 FINDINGS.** Full verification log: detector extraction preserves 0019
  behaviour, stale-request guard is an unconditional early return, DOM resync
  present, `notSupported`/`permissionDenied` distinct, minute-in-tag aligned —
  all **PASS**.
- **P2**: `docs/features/0028_PLAN.md` not shipped in the branch. **Accepted +
  fixed** — the plan doc is now committed with the feature (repo convention:
  every feature ships its plan; `docs/features/` previously topped out at 0027).
- P3: desktop "detector parity" suite omits the shared-detector "block added
  without remount" case (#6). **Recorded gap, not fixed** — the shared
  `useBlockBoundaryDetector.test.ts` owns that behaviour (case 6); the desktop
  suite only needs channel-wiring coverage, which it has.
- P3: no dual-harness test mounting sound + desktop together to lock the
  independent-cursor contract. **Recorded gap, not fixed** — behaviour follows
  from separate closures; non-blocking.

## Verification
- `cd frontend && npm test` — **629 passed** (57 files).
- `cd frontend && npx vue-tsc --noEmit` — **no type errors**.

## Result
Zero valid P1/P2 outstanding. Two P3 gaps recorded and consciously deferred
(both are redundant coverage, not correctness holes). **SUCCESS.**
