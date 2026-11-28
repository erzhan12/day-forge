# 0113 — Mobile schedule (Dark 4a, max-width 640 px)

## Why

The Dark 4a Schedule page has no phone layout: below 1024 px it shows the desktop timeline with a bottom chat dock, and its time axis, 40 px controls and inline editing do not fit a 390 px screen. The design mentor's SPEC section 11 defines a mobile layout. See [docs/features/0113_PLAN.md](../../../docs/features/0113_PLAN.md).

## What Changes

- A `max-width: 640px` breakpoint (`useIsMobile`) that, with Dark 4a, switches Schedule to a single-column list with a compact header, FAB, bottom sheets and a collapsed chat bar.
- Viewport meta `viewport-fit=cover, interactive-widget=resizes-content`, safe-area variables and a `100dvh` height variable.
- On mobile, deleting a block needs no confirmation and shows a 5-second `Block deleted · Undo` toast.
- On mobile, the full chat privacy text sits behind ⓘ in rest state.
- Delivered in stages (PR1 scaffold to PR8 close-out); stage 7 (touch drag) is deferred. Time and category editing in the sheet is issue #333.

## Capabilities

- `frontend/mobile-schedule`: ADDED (breakpoint and scaffold now; layout requirements as stages land)
- `frontend/undo-and-drag`: ADDED "Mobile delete is immediate" and "Mobile Undo toast"
- `frontend/chat-ui`: ADDED "Mobile privacy hint sits behind the info control"

## Impact

Frontend only, Dark 4a at 640 px and below. Wider screens and other themes keep their layout. No backend, API or migration change. The Playwright script `ai-chat-privacy-hint-always-on.mjs` and `dark4a-day-fit.mjs` (390 px checks) change in stages 3 and 6.
