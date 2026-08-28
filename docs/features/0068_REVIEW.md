# 0068 — Code Review Trail

Feature: AI chat duration resizing (`resize` gains `duration_minutes` + `duration_delta_minutes`; backend computes the new end in integer minutes). Plan: `docs/features/0068_PLAN.md`.

## Local staged review (5 parallel category agents)

- **Code quality / Security / Performance / Documentation:** no CRITICAL findings. The implementation was traced against the plan contract and matches every load-bearing point (reject-not-clamp, integer `derived_end_minutes` as single source of truth, chain-poison pre-check ordered first, dedicated duration branch before the supplied-window check, effective-start guard gated on `start_supplied`, forward/reverse merge-inherit hazards handled, no unbounded value reaches `datetime.time()`).
- **Testing:** ~20 of the plan's mandated planner/view tests are **missing** (the `>=1440`/`<=0` ValueError edges, chain-poison, effective-start guard vs standalone pre-window, interval-vs-granularity precedence collision, forward-chain move→duration, overlap unchanged-vs-changed-neighbour). **User explicitly accepted this gap and chose to ship without adding them.** The implementation itself is present and traced-correct; 236 focused tests pass.

## External-engine review (codex gpt-5.6-sol + cursor, read-only)

Both engines ran against the staged diff.

- **cursor:** full plan-contract verification log — every point MATCH. `NO P1/P2 FINDINGS`.
- **codex:** 2×P2 raised, both triaged and **rejected** with evidence:
  1. "resize accepts unknown/camelCase duration keys and treats duration+boundary as boundary-only" — **REJECTED**: verified via `validate_action_shape` that `duration_minutes + end_time` → rejected (`mode_count=2`), camelCase `durationMinutes` → rejected (`mode_count=0`). Only a stray `title` on resize is silently ignored (P3 robustness, not a defect).
  2. "no legal single-action shape for combined rename+duration" — **REJECTED as P2**: the two-action (update rename + resize duration) same-task merge path works and is tested; this is P3 prompt-polish, not a code defect. Feature scope was duration resize.

**Valid P1/P2 across both engines: 0.**

### P3s fixed (trivially-cheap, clearly-right)

- `backend/ai/schemas.py:73-77` — stale comment claiming `duration_minutes` is valid only on untimed adds; updated to include the resize operand (plan REFACTOR mandate).
- `backend/ai/mutation_planner.py:753` — production `assert upd.derived_end_minutes is not None` replaced with a defensive `reject(..., "out_of_window") + continue` (an `assert` is stripped under `-O`).

### P3s accepted (not fixed)

- Mixed duration+boundary emits a second (redundant but correct) error alongside the exclusivity error.
- Duration-mode calls `compute_move_resize_times` then overwrites its result (harmless; documented intentional).
- Leftover `_apply_move_or_resize` (non-chat, dead path) ignores duration fields.
- Test organization: some auto-placement assertions sit under the duration-resize test class.

## Verification

- `uv run pytest backend/tests/test_ai_{schemas_draft,mutation_planner,service_chat,views_chat,prompts_command_chat}.py -q` → **236 passed**.
- `uv run ruff check backend/` → **clean**.

## Trace

```
ext-code-review trace
  scope: 10 files (3 source, 5 tests, 2 docs)
  engines: both (codex + cursor)
  iterations: 1/10
  findings: raised 8, accepted 2 (P3, fixed 2), rejected 2 (P2, evidence recorded), P3-ignored 4
  verification: 236 passed, lint clean
  result: SUCCESS
```
