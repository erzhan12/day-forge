# 0047 — Atomic reorder swap for rule lists — Review trail

Feature: shared `swap_ordering_field` helper (`backend/schedules/http.py`) +
two thin views (`rules_swap` in `templates_mgr/api.py`, `travel_rules_swap`
in `calendar_sync/travel_rules.py`), URL routes, frontend `swapRules` in
`useRules.ts`/`useTravelRules.ts`, both sibling components repointed.

## External review trail

Engines: OpenAI codex (`gpt-5.6-sol`) + Cursor agent, read-only.

### Round 1

**Raised:** codex 1×P2 + 3×P3; cursor 0×P1/P2 + 7×P3.

**Accepted & fixed:**

- **[P2, codex] Target rows not locked; `bulk_update` rowcount ignored.**
  `swap_ordering_field` locked only the User row. The detail DELETE view does
  not take the User lock, so a concurrent same-user delete between the SELECT
  and the `bulk_update` could update only the survivor yet return 200 —
  violating both-or-neither. Fix: `select_for_update()` the two target rows.
  A concurrent delete now either blocks until the swap commits or makes the
  `get()` raise `DoesNotExist` → clean 404. No-op on SQLite (whole-db write
  lock via `atomic()`).
- **[P3, codex] Rollback tests raised before any write** → passed even without
  `transaction.atomic()`. Fix: tests now call the real `bulk_update`, then
  raise, proving `atomic()` rolls back a landed write.
- **[P3, codex+cursor] `RulesList` equal-value nudge silent on PATCH failure**
  (sibling `TravelRulesList` set `rowError`). Fix: `RulesList` nudge now sets
  `rowError` on failure — sibling parity.
- **[P3, cursor] Stale comment** in `test_patch_does_not_compact_priorities`
  justified "no PATCH compaction" via the removed two-PATCH path. Updated to
  cite the equal-value nudge / manual edits.
- **[P3, cursor] Travel 400 copy** said "rule ids" on the travel endpoint →
  "travel rule ids".
- **[P3, codex] Bool-id branch untested** (the reason `is_plain_int` exists) →
  added `test_swap_bool_id_returns_400` to both suites.
- **[P3, cursor] Success tests asserted id-set only** → now assert the swapped
  `priority`/`order` values in the response envelope.

**Accepted gaps (not fixed — non-blocking):**

- `TestTravelRuleSwap` lives in `test_from_event.py` rather than a dedicated
  module (discoverability only; plan permitted alternatives).
  *(Resolved in feature 0048 — moved to `backend/tests/test_travel_rules.py`.)*
- `RulesList` distinct-value component test covers the "down" direction only.
- `tasks/todo.md` `0026-followup` checkbox — bookkeeping, flipped at merge.
- The two thin near-identical swap views retain ~15 lines of duplicated
  request parsing — intentional per plan (two thin views over one branching
  endpoint); the read-modify-write core is shared in `swap_ordering_field`.
  *(Resolved in feature 0048 — request parsing extracted to
  `schedules.http.parse_swap_body`.)*

**Rejected:** none (all round-1 findings were valid or accepted gaps).

### Round 2

Re-run after fixes. Both engines: **NO P1/P2**. 5×P3, all accepted & fixed:

- **[codex]** Swap-composable tests lacked `toHaveBeenCalledOnce()` — a
  duplicate-POST impl could pass. Added to both `useRuleSwaps.test.ts` cases.
- **[cursor]** Fix-(a) inline comment claimed "the detail DELETE view does not
  take the user lock" — inaccurate: `rule_detail` DELETE *does* (feature 0046);
  only `travel_rule_detail` doesn't. Reworded the comment + docstring + RULES.md
  to say the row lock serializes the swap against the travel-rule delete
  specifically.
- **[cursor]** `swap_ordering_field` docstring + `RULES.md` still documented
  only the user lock — updated to mention the target-row `select_for_update`.
- **[cursor]** No regression test for the new `RulesList` equal-nudge
  failure→`rowError` path — added `test surfaces an error when the
  equal-priority nudge PATCH fails`.
- **[cursor]** Stale `∓1` in the compaction-test comment (RulesList uses `±1`)
  — corrected.

**Rejected:** none.

### Result: SUCCESS (2 rounds, zero valid P1/P2 remaining)

### Verification (final)

- Backend: `test_templates_api.py` + `test_from_event.py` swap/compaction
  classes — 22 passed.
- Frontend: `RulesList.test.ts` + `TravelRulesList.test.ts` +
  `useRuleSwaps.test.ts` — 18 passed. `vue-tsc --noEmit` clean.
- Lint: `ruff check backend/` clean.
