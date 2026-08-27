# 0066 — Code Review Trail

Feature: PiP focus indicator shows the next block's title + minutes-until-start during the idle between-block pause (issue #176).

## Local staged review (superpowers review-fix-loop-staged)

- Iterations: 1/3. Criticals: 0.
- Verified: `vue-tsc --noEmit` 0 errors; 77 focus tests pass; `ruff check backend/` clean; privacy invariant intact (active state + `document.title` generic; gap-only title by design).
- Info (non-blocking): split validation across Schedule↔View layers (defensible prop-boundary guard); `.trim()` at view not source; composite "now-inside-completed + later" gap render only transitively covered.
- Result: Ready to commit.

## External review trail (ext-code-review)

Engines: codex (`gpt-5.6-sol`, read-only) + cursor (`agent --mode ask`). Plan: `docs/features/0066_PLAN.md`.

### Iteration 1

Both engines independently verified the **code as fully correct** (Cursor's 16-point verification log: all MATCH — selection algorithm, fail-closed, privacy invariant, snake_case fields, PIP_STYLES declarations, seam correction). All findings were **test-coverage gaps** vs the plan's coverage matrix. Codex labelled them P3; Cursor labelled the same gaps P2. Triaged by own verdict:

Accepted + fixed:
- **A** — `scheduleFocusIndicator.test.ts`: completed-future and empty-title were one case (`title:"", is_completed:true`), so a completed→real-title render and an empty→Untitled render were both unproven. Split into two dedicated cases (`Dentist` completed real title; separate empty-title → Untitled).
- **B** — added integration case: now inside a completed block **with a later block** → PiP shows the later title, not the completed-containing block.
- **C** — the `off-today` row of the invalid-data `it.each` nulled **both** `nowMinutes` and `nowDate`, so it never pinned the `nowDate`-only today-signal. Extracted to a dedicated test keeping `nowMinutes` finite (600) and nulling only `nowDate` with a later-looking block present.
- **D** — added integration case: now after the last block's start (no later block) → PiP retains `—` / `No active block`.
- **E** — `FocusIndicatorView.test.ts`: the empty-title and null-title tests did not assert the neutral sentinels (`.fi-neutral` / `.fi-sr-only`) absent (Untitled case) or `.fi-next-remaining` absent (null-title case). Strengthened both.

Rejected (evidence recorded):
- **F** (Cursor P3) — "RULES.md:891-897 documents PiP completion / `justCompletedId`, contradicting display-only PiP." REJECTED as out-of-scope for this PR: `justCompletedId` / `handleIndicatorComplete` / `focusCompletion` exist **nowhere** in `frontend/src` (grep clean; only unrelated `setCompleted` in `useBlockCompletion.ts`). The staleness is **pre-existing** — not introduced or made stale by feature 0066, whose surface is the gap-title state. Worth a separate doc-cleanup pass; not this feature's scope.

Verification after fixes: `vue-tsc --noEmit` 0 errors; full frontend suite 1002/1002 pass (focus subset 80/80).

### Iteration 2

Both engines: **NO P1/P2**. Two P3 doc-accuracy findings, both accepted (cheap, clearly right, within 0066's own doc surface):

- codex P3 — the plan's "known-gap" note (0066_PLAN.md) described a malformed-duration *active* block leaking the gap state, citing a backend "constraint". Verified against code: `findCurrentBlock`'s half-open filter `start <= now < end` never matches an empty/`NaN` interval, so a malformed-duration block is never the active block — the scenario cannot arise. And `start_time >= end_time` is rejected by `TimeBlock.clean()` (validation), not a DB constraint. Rewrote the note to be accurate.
- cursor P3 — `RULES.md` completion-controller bullet called the PiP "display-only (progress + remaining minutes)", now stale after the gap title+countdown. Tightened the parenthetical (left the `justCompletedId` paragraph untouched).

Both fixes are markdown-only (no code change); tests/lint unaffected.

### Trace

```
ext-code-review trace
  scope: 10 files (4 src, 4 test, 2 rules) + 2 docs
  engines: both (codex gpt-5.6-sol + cursor)
  iterations: 2/10
  findings: raised ~12, accepted 7 (fixed 7), rejected 1 (RULES justCompletedId — pre-existing, out of scope), P3-ignored 0
  verification: vue-tsc 0 errors, 1002/1002 frontend tests pass, ruff clean
  result: SUCCESS
```
