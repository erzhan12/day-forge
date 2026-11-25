# 0112 — External calendar past-state at saved-zone midnight

## Why

Leaving Schedule open across the user's saved-zone midnight left external-calendar past/current styling frozen on the first render's civil date (issue #229). See [docs/features/0112_PLAN.md](../../../docs/features/0112_PLAN.md).

## What Changes

- ExternalEventsPanel classifies `ee-item--past` from the reactive saved-zone civil date (`todayDate` from `useNowMinutes`), not a cached `todayString()` read.
- Schedule keeps passing that date to center and sidebar panel instances.
- A missing `todayDate` re-samples `todayString(timeZone)` when `nowMinutes` ticks, so the original nowMinutes-only wiring still rolls over. No second timer in the panel.

## Capabilities

- `frontend/external-sources`: ADDED "External calendar past-state follows the saved-zone clock"

## Impact

Frontend calendar panel styling only. No backend, API, migration, PiP, or logout-privacy change.
