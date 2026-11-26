---
paths:
  - "backend/analytics/**"
  - "backend/tests/test_analytics_*.py"
  - "frontend/src/composables/useAnalytics.ts"
  - "frontend/src/pages/Analytics.vue"
  - "frontend/src/components/SkippedTasks.vue"
  - "frontend/src/components/StreakCounter.vue"
  - "frontend/src/components/CategoryBreakdown.vue"
  - "frontend/tests/Analytics.test.ts"
  - "frontend/tests/StreakCounter.test.ts"
  - "frontend/tests/SkippedTasks.test.ts"
  - "frontend/tests/CategoryBreakdown.test.ts"
  - "frontend/scripts/playwright/analytics-*.mjs"
---

## Analytics and review snapshots

- An analytics GET computes current statistics without creating or rewriting `DailyReview`. Capture schedule, blocks, review, and streak coherently. A frozen review is current only when status is `reviewed` and `reviewed_revision` equals the schedule revision. Otherwise display statistics from current blocks. Streak and AI draft history use the same predicate.
- Category deletion remaps category minutes and advances affected schedule revisions without recomputing frozen counts. Advance a reviewed snapshot's tag only if it matched the schedule revision before the remap. Preserve notes and review timestamps; never make an already stale snapshot current. The block remap, tag, maps and category deletion share one User transaction.
- `mark_reviewed` checks body size, date, ownership, and locked status before parsing the request body. A reviewed retry returns its current frozen result, or repairs a missing or stale snapshot at the existing revision, even if the body is malformed or its expected revision is obsolete. A draft day is refused without body parsing. Only an active day parses `expected_revision` and notes, freezes aggregates, and advances the revision. A reviewed retry does not update notes; use the notes PATCH route.
- Notes save lazily, including on a draft day. They do not alter schedule revision or snapshot tag. A review row's existence does not prove its aggregates are current. A stale snapshot is repaired only by explicit review POST, never by GET. A date change flushes outgoing notes; a user or session change discards pending notes. See [R10](../../docs/REFACTORING_R10.md).
- Analytics offers an explicit update for a reviewed day whose snapshot is missing or stale. Hide that control only for a frozen snapshot belonging to the canonical schedule and matching its revision. Maintenance never repairs stale aggregates automatically.
- The streak walks backward from yesterday. A missing schedule breaks it; a zero-block schedule skips without counting or breaking it. Past uncompleted blocks are skipped. On today, only uncompleted blocks whose end has passed are skipped; future days do not show skipped tasks.
