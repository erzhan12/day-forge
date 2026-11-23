# 0106 — Dark 4a UI fixes: stack timeline, controls, calendar card, empty day

## Why

In Dark 4a a 5-minute block renders 10 px tall and clips its row, a free gap of a few hours takes hundreds of pixels, header buttons use four heights, the calendar card shows the account email, and a day without a template shows only a long empty row. Native controls in Settings stay light. See [docs/features/0106_PLAN.md](../../../docs/features/0106_PLAN.md).

## What changes

- The Dark 4a timeline stacks its items: blocks are at least 28 px, free gaps are capped at 60 px, and hour labels, the now line and drag follow that layout through one axis map frozen at drag start.
- Short blocks render as one compact row with a tooltip; free gaps render as `Free · 2h 50m` with an add action.
- Calendar events reach the timeline only through the explicit `Add to schedule` import. Below 1024 px in Dark 4a the calendar panel renders in the centre position so that action stays reachable.
- A Dark 4a day with no template and no blocks shows an empty state instead of the timeline.
- Presentation only: Dark 4a tokens, one control skin for buttons, fields, links and settings checkboxes, a 13 px text floor, the dark `color-scheme`, the chat input font, and Log out moved to Settings in Dark 4a.

## Capabilities

- `frontend/schedule-page`: ADDED stack layout, compact block, gap row, empty day.
- `frontend/undo-and-drag`: MODIFIED "Drag cancellation and frozen geometry" (the frozen state includes the axis map).
- `frontend/external-sources`: ADDED calendar events stay off the timeline; MODIFIED "Poll fan-out by visible branch" (Dark 4a narrow centre fallback).

## Impact

Frontend only, except one backend characterisation test. Other themes keep their behaviour; the Education colour migration is a separate change.
