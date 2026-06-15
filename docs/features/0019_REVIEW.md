# 0019 — Code Review: Sound notifications at block start/end (issue #56)

Review of the feature implemented per [0019_PLAN.md](0019_PLAN.md). Method:
6-dimension multi-agent review (plan-fidelity, bugs, data-alignment,
over-engineering, style, tests) per `commands/code_review.md`, each finding
adversarially verified against the actual code before inclusion.

## Round 1 — findings

**Severity tally:** P0 = 0, P1 = 0, P2 = 2, P3 = 6. (3 further candidates
rejected on verification as non-actionable nits — see bottom.)

No blocker (P0) or should-fix-before-merge (P1) issues. The plan was
implemented faithfully: strict-only-on-true storage, module-level
never-close singleton `AudioContext`, crossed-since-last-sample `(prev, now]`
detection with first-tick-no-backfill and a backward-step guard, the
`nowDate` reset watch, Schedule/Settings wiring, and a 13-case spec.

### P2 — fixed

1. **fired-Set keyed by id, not boundary minute → re-timed boundary
   suppressed.** `useSoundNotifications.ts`. The idempotency key was
   `${type}:${block.id}:${date}`. If a block's boundary already fired and the
   user then edited the block's time (or dragged it to a new time) on the
   same open day — a re-flow via `router.reload({only:['blocks','schedule']})`
   keeps the same `id` — the new boundary was silently dropped because the
   id+date key was already in `fired`. **Fix:** include the boundary minute in
   the key (`start:${id}:${date}:${s}`). A re-timed boundary now gets a
   distinct key and fires; a stationary re-flow at the same minute still
   self-dedupes; the Set still clears on date change so it stays bounded.
   Regression test added (detector test 12).

2. **Audio-node wiring half of the plan's stated test contract unasserted.**
   `tests/useSoundNotifications.test.ts`. The plan names the test contract as
   "start ≠ end tone, AND both produce an oscillator + gain wired to
   `destination`." Tests asserted oscillator count + rising/falling frequency
   but never that `osc → gain → ctx.destination` was connected, that
   `start`/`stop` ran, or that the gain envelope was scheduled — so a
   silent-output regression (oscillator built but never connected) would pass.
   **Fix:** test 2 now asserts `osc.connect(gain)`, `gain.connect(destination)`,
   `start`/`stop` called once, and both gain ramps scheduled.

### P3 — fixed

3. **DRY: duplicate `hhmmToMinutes`.** It was byte-equivalent to the exported
   `timeToMinutes` in `utils/scheduleTime.ts` (the canonical converter used
   across the schedule code). **Fix:** import and use `timeToMinutes`; deleted
   the local copy.

4. **`unlockAudioContext` not guarded against a synchronous throw.**
   `audioContext.ts`. `playSound` wraps its `resume()` in try/catch but the
   unlock path (called inside the toggle's click handler) did not — an
   asymmetry. Spec-conformant `resume()` returns a promise, so the risk is low,
   but **fix:** wrapped in try/catch to mirror `playSound`.

5. **Detector return surface + `watch(enabled)` untested / "dead".** Three
   P3 findings shared one root: the detector returns `{enabled, setEnabled}`
   that both call sites discard, and `watch(enabled)` (the mid-session-enable
   reset) is never driven in production (Settings uses a separate instance +
   remount). **Resolution:** the return and watch are a deliberate
   same-instance safety net from the plan; rather than delete plan-sanctioned
   code, the new detector test 13 captures the returned `setEnabled`, toggles
   it off→on mid-session, and asserts no back-fire — making the surface live
   and the watch covered. Added a comment noting the watch is defensive-only.

### Rejected on verification (non-actionable nits)

- `aria-disabled` not mirrored from `DesignSelector` — the toggle is fully
  synchronous (no `isSaving` state), so there is nothing to disable. The plan
  scoped aria attrs to "as applicable."
- `role="switch"` on a native checkbox — valid and arguably the more
  appropriate idiom for an on/off setting; `aria-checked` is correctly bound.
- Defensive `resume()` in `playSound` not asserted — a no-op best-effort call
  on a narrow edge case; pinning it would couple the test to an implementation
  detail. (Test 12/12b already assert the unlock-path `resume`.)

## Round 2 — re-review of the fixes

Re-reviewed the changed files (`useSoundNotifications.ts`, `audioContext.ts`,
the test file) for correctness and any regression introduced by the P2/P3
fixes. **Result: P0 = 0, P1 = 0.** Typecheck clean; full suite 373/373 pass
(+2 new). No new findings of any severity. Loop terminates — no P0/P1
outstanding.
