# Feature 0054 — External review trail

Feature: AI chat partial-apply of safe metadata + one conflict resolution (issue #111).
Branch: `feat/0054-partial-ai-apply`. Reviewers: OpenAI codex (`gpt-5.6-sol`) + Cursor agent, read-only.

## Local staged review (review-fix-loop-staged)

- 1 iteration, 5 categories. Security ✅ Performance ✅ (both clean, verified).
- Zero CRITICAL. Baseline green: 1034 backend + 19 frontend tests, ruff clean, tsc clean.
- Warnings surfaced (carried into external review): orphaned move/resize/remove dispatcher in `views.py` (deferred P3 cleanup); free-slot directional test gaps; stale `docs/api.md` all-or-nothing invariant.

## External review loop (ext-code-review) — 3 iterations, SUCCESS

### Iteration 1 — 6 valid P1/P2 accepted & fixed
- **P1** `test_from_event.py` off-grid test asserted obsolete 400 → full suite red. Migrated to the new 200 + skipped-outcome contract (times unchanged, `reason_code="granularity"`).
- **P2** `free_slot.py` — initial candidate never clamped into the window → valid `later`/`earlier` slots at the window edge returned `None`. Now clamps (`later`: `max(candidate, window.start_minutes)`; `earlier`: `min(candidate, grid-aligned max_start)`).
- **P2** `mutation_planner.py` merge reset a prior `later`/`earlier` direction to `exact` when a later same-`task_id` action supplied a time. Direction now derives from this action's own key, else inherits `prev.direction`.
- **P2** `views._build_resolution_ask` was action-order dependent and the `unresolved_conflict` question didn't name blocks. Now fixed precedence (order-invariant) + names both conflicting blocks.
- **P2** `schemas.validate_action_shape` didn't validate `direction`. Now enforces `{later,earlier,exact}`, rejects direction-without-time, rejects direction on non-`update` types.
- **P2** `prompts.build_system_prompt_chat` missing the two-step direction-answer protocol. Added.
- 13 regression tests added. Re-verify: 1047 backend + 19 frontend passed, ruff clean, tsc clean.
- **Rejected:** claim that `test_ai_mutation_planner.py:603` (two overlapping adds) asserts `partial` but fails — it PASSES; the cascade (A skipped vs unchanged, B survives) yields `overall_status="partial"` as asserted.

### Iteration 2 — 2 valid P2 accepted & fixed
- **P2** `schemas.py` — a non-string `direction` (list/dict) raised `TypeError` on set membership → escaped `AIParseError` → 500. Added `isinstance(str)` guard + regression test.
- **P2** prompt/schema contradiction — prompt told the model to re-emit a direction via `update/move`, but the schema rejects `direction` on `move` → whole-turn abort. Prompt now states `direction` is ONLY valid on `update`.
- **Downgraded to P3 (accepted):** `unresolved_conflict` naming when one party is a same-turn create — question selection is order-invariant and still correct; only naming *specificity* degrades in a rare mixed update+add mutual conflict.
- cursor: NO P1/P2 FINDINGS (full verification log, all fixes MATCH).

### Iteration 3 — clean
- codex: **NO P1/P2 FINDINGS**. cursor: **NO P1/P2 FINDINGS** (all fixes re-verified MATCH; cross-user IDs cannot leak — snapshot is this-schedule only).

## Accepted non-blocking gaps (P3)
- Orphaned move/resize/remove apply dispatcher + leftover `_validate_candidate`/`_build_diff` in the planner — deferred cleanup (planner owns chat apply now).
- Resolution-ask titles come from the pre-apply snapshot (a same-turn rename is named by its old title).
- `update` titles are not stripped at intake (`add` strips).
- `docs/api.md` still documents the old all-or-nothing/rollback invariant + omits `partial`/`outcomes[]` fields — update before/with the API-doc pass.
- Test-coverage gaps noted but non-blocking: two-turn exact→direction→concrete integration; no-slot `attempted_direction` surfaced in `ask`; large-turn `outcomes_json` validity.

## Final verification
- Backend: full suite green. Frontend: 19 useChat tests + tsc clean. Lint: ruff clean.
- Result: **SUCCESS** — zero valid P1/P2, tests + lint green.
