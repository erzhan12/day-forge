---
name: "0013 show time remaining - implementation review"
description: Code review against docs/features/0013_PLAN.md
date: 2026-05-22
---

# Feature 0013 — Code Review

Review of the frontend-only “time remaining on current block” implementation (GitHub Issue #25) against `docs/features/0013_PLAN.md`.

## Verdict

**Approve — ready to merge.** Implementation matches the plan’s behavioral contract. Tests and type-check are green. No blocking or important issues.

---

## Findings

### No blocking or important issues

No bugs, data-shape mismatches, or missing core functionality were found in the schedule/countdown path.

### Minor (optional follow-ups)

| ID | Area | Note |
|----|------|------|
| M1 | Tests | Plan § optional integration: `Schedule.test.ts` does not assert that `NowLine` reappears after Inertia-style navigation from a non-today date to today. Coverage is adequately delegated to `useNowMinutes.test.ts` + `TimeBlock.test.ts`; adding this would be low-friction polish only. |
| M2 | Overlap edge case | `findCurrentBlock` sorts overlapping matches by `(start_time, sort_order)`; `displayList`’s NowLine splice uses iteration order of `props.blocks`. With normal API payloads (backend ordering + overlap rejection) they agree. With corrupt overlapping data in unsorted order, countdown and NowLine could theoretically diverge — same class of edge case the plan documents as unlikely. |
| M3 | Analytics midnight | `SkippedTasks` still derives `isPastDay` / `isToday` from `todayString()` inside computeds that only re-run when `props.date` or `currentHHMM` changes. A tab left on Analytics across midnight without navigation can leave date classification stale until props change. This predates 0013; the composable refactor preserves prior behavior and is out of 0013 scope. |
| M4 | Comment removal | `SkippedTasks.vue` dropped the comment explaining why the 60s tick exists. Restoring a one-liner pointing at `useNowMinutes` would help future readers. |

---

## Plan compliance

| Plan requirement | Status |
|------------------|--------|
| Frontend-only; no backend/API/DB changes | ✅ |
| `findCurrentBlock`, `remainingMinutesForBlock`, `formatDurationMinutes`, `formatRemainingMinutes` in `scheduleTime.ts` | ✅ |
| Pure helper: `nowDate` explicit input, no `todayString()` inside `findCurrentBlock` | ✅ |
| Half-open `[start, end)` interval; overlap → first by `(start_time, sort_order)` | ✅ |
| `useNowMinutes` composable with watch + tick midnight rollover handling | ✅ |
| Refactor `Schedule.vue` + `SkippedTasks.vue` to composable | ✅ |
| Parent computeds `currentBlock` + `currentBlockRemaining`; pass props to both block slots | ✅ |
| `effectiveBlocks` used for current-block lookup (drag preview) | ✅ |
| `TimeBlock.vue`: shared duration formatter + optional `isCurrent` / `remainingMinutes` props + badge UI | ✅ |
| No active-row border/background in v1 | ✅ |
| `scheduleTime.test.ts`, `useNowMinutes.test.ts`, extended `TimeBlock.test.ts` | ✅ |
| `SkippedTasks` analytics semantics unchanged (existing tests still pass) | ✅ |

---

## Confirmed good

### Architecture and data alignment

- **Snake_case end-to-end:** `TimeBlock` props use `start_time`, `end_time`, `sort_order` consistently with backend JSON and existing components. No camelCase drift.
- **Composable contract:** `useNowMinutes` exposes `{ nowMinutes, nowDate, currentHHMM }` exactly as specified. `nowDate === null` gates all today-only UI in `Schedule.vue` (`displayList`, countdown props).
- **Presentation boundary:** `Schedule.vue` owns current-block selection; `TimeBlock.vue` only renders when `isCurrent && remainingMinutes > 0`. No business logic duplicated in the child.
- **DRY duration labels:** `formatDurationMinutes` centralizes the whole-hour cases (`60` → `"1h"`, `120` → `"2h"`) previously inlined in `TimeBlock.vue`. `formatRemainingMinutes` appends `" left"` — single source of truth.
- **Navigation bug fix:** Replacing `onMounted`-only interval setup with `watch(viewedDate, …, { immediate: true })` fixes frozen `nowMinutes` when Inertia navigates non-today → today without remount (the primary regression called out in the plan).
- **Midnight rollover:** Interval `tick()` re-evaluates `todayString()` vs `viewedDate` and calls `leaveToday()` when they diverge — prevents a stale NowLine/countdown on yesterday’s view after midnight.

### UI

- Compact blocks: `remaining-badge` after time badge, `flex-shrink: 0`.
- Expanded blocks: badge between `.duration` and `.delete-btn`; total duration unchanged.
- Styling uses existing tokens (`--accent` on badge, `--text-muted` on time badge) — no CSS token freeze violations.

### Code style

- Matches existing composable patterns (`watch` + `onUnmounted` cleanup).
- File sizes remain reasonable; no over-abstraction beyond the required composable extraction.

---

## Tests review

### Coverage map

| File | What it proves |
|------|----------------|
| `frontend/tests/scheduleTime.test.ts` | `nowDate === null`; in-window selection; gap/boundary/end-exclusive; overlap ordering; remaining clamp; formatter contract including negative guard and `1440` → `"24h"`. |
| `frontend/tests/useNowMinutes.test.ts` | Same-instance today entry; 60s tick; leave-today clear; round-trip fresh sample; no duplicate intervals (`setInterval`/`clearInterval` ordering); midnight rollover without navigation; unmount cleanup. **Primary owner of the navigation regression.** |
| `frontend/tests/TimeBlock.test.ts` | Active compact/expanded badges; inactive omission; whole-hour duration regression (`1h`, `2h`); compact 30m layout unchanged. |
| `frontend/tests/SkippedTasks.test.ts` | Past/today/future filtering preserved; list grows when interval advances past block end (composable tick still drives `currentHHMM`). |

### Test quality

- **Isolation:** Time helpers tested without Vue; composable tested via minimal harness; component tests mock `useSchedule` / Inertia as existing suites do.
- **Naming:** Descriptive `it(...)` strings aligned with project conventions.
- **Speed:** Fake timers used appropriately; no unnecessary network or DOM setup.
- **Mocking:** `useNowMinutes.test.ts` spies `setInterval`/`clearInterval` only where needed to prove no handle leaks.

### Gap (non-blocking)

- Optional `Schedule.test.ts` NowLine-after-navigation integration (plan M1) not added — acceptable given composable unit coverage.

---

## Verification run

Commands executed during this review:

```bash
cd frontend && npm test -- --run scheduleTime.test.ts useNowMinutes.test.ts TimeBlock.test.ts
cd frontend && npm run type-check
cd frontend && npm test -- --run
```

Results:

- Targeted tests: **3 files, 49 tests passed**
- `vue-tsc --noEmit`: **passed**
- Full frontend suite: **32 files, 299 tests passed**

---

## Manual verification

Automated tests prove wiring and interval lifecycle. A quick manual pass on the dev site is still worthwhile:

1. Open today’s schedule with a block spanning “now” — confirm `Xm left` on that row only.
2. Navigate to yesterday and back to today without full reload — confirm NowLine and countdown appear immediately.
3. Check a ≤30 min compact block and a >30 min expanded block for badge placement.

No dedicated `0013_MANUAL_TEST.md` was required by the plan.
