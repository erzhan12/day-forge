# Feature 0049 — Code Review

## External review trail (ext-code-review)

Scope: the deferred PR #145 round-2 P3 — surface a Document Picture-in-Picture
`open()` failure to the user. Files reviewed (vs `main`):

- `frontend/src/composables/useFocusIndicator.ts`
- `frontend/src/components/ShowIndicatorButton.vue`
- `frontend/src/pages/Schedule.vue`
- `frontend/tests/useFocusIndicator.test.ts`
- `frontend/tests/ShowIndicatorButton.test.ts`
- `frontend/tests/scheduleFocusIndicator.test.ts`

Engines: OpenAI codex (`gpt-5.6-sol`) + Cursor agent, read-only.

### Iteration 1

**Raised / deduped:**

1. **P2 (codex) / P3 (cursor)** — `useFocusIndicator.ts:124`: the `catch` block
   reset `pendingOpen` and ran `teardown(true)` *before* the epoch check, unlike
   the success path (`:102`). A stale rejection arriving after `cleanup()` + a
   newer `open()` had adopted its window would tear down the **newer** live
   window and clobber the newer request's in-flight guard. **ACCEPTED.**
   - Fix: guard the whole catch recovery (`pendingOpen` reset + `teardown` +
     `showOpenError`) behind `if (myEpoch === epoch)`, mirroring the success
     path. A superseded request is no longer user-actionable, so no error shows.
   - Regression test: `"a stale rejection after cleanup()+reopen leaves the new
     window and shows no error"`.

2. **P3 (both)** — rejection test left a real 5s `setTimeout` (`showOpenError`)
   alive across the test boundary. **ACCEPTED (cheap):** the test now calls
   `fi.cleanup()` to release the timer.

3. **P3 (cursor)** — no test asserted `openError` stays null on the
   epoch-cancelled path. **ACCEPTED:** covered by the new race regression test
   (`expect(fi.openError.value).toBeNull()`).

**Rejected:** none. (Codex's `vite.config.ts __dirname` errors were its own
sandbox tooling invocation artifacts — the standard `npm test` runner passes;
not a code finding.)

**Verification after fixes:** `npm test` → 782 passed (65 files); `vue-tsc
--noEmit` → clean.

### Iteration 2

**Raised / deduped:**

1. **P2 (codex) / P3 (cursor)** — `useFocusIndicator.ts:100`: the **success**
   path had the *same* class of bug as the iter-1 catch fix — it reset the
   shared `pendingOpen` *before* the `if (myEpoch !== epoch)` epoch check. A
   stale fulfillment (request #1 resolving after `cleanup()` + a newer `open()`)
   clobbered the newer request's in-flight guard, letting a third `open()` slip
   through and spawn a duplicate/orphan window. **ACCEPTED.**
   - Fix: move `pendingOpen = false` to *after* the epoch check; a superseded
     resolution now only closes its orphan and leaves shared state untouched.
   - Regression test: `"a stale resolution does not clobber a newer pending
     request's in-flight guard"` (asserts a third `open()` is a no-op —
     `requestWindow` called exactly twice).

2. **P3 (cursor)** — stale `NotAllowedError` "quiet failure" comment was
   misleading now that a matched-epoch failure surfaces the 5s alert.
   **ACCEPTED (doc):** comment reworded to describe the *console* policy
   explicitly and note the log intentionally stays outside the epoch guard.

**Rejected / by-design:** cursor P3 that `console.error` runs outside the epoch
guard — kept deliberately (a genuine programming-error log is worth keeping even
for a superseded request; `NotAllowedError` remains unlogged).

**Verification after fixes:** `npm test` → 783 passed; `vue-tsc --noEmit` → clean.

### Iteration 3 (convergence check)

Both engines re-reviewed the final state:

- **codex**: `NO P1/P2 FINDINGS`, no P3.
- **cursor**: `NO P1/P2 FINDINGS` — verification log confirms both post-`await`
  paths check epoch before any shared-state reset, single `await` site, both
  regressions covered.

**Result: SUCCESS.** Zero valid P1/P2; tests + typecheck green (783 passed).
