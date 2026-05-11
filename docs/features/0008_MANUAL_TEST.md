---
name: 0008 — AI chat as collapsible right sidebar (manual tests)
description: Manual verification matrix for feature 0008. Run from a clean dev server (`uv run python backend/manage.py runserver 8006` + `cd frontend && npm run dev`), authenticated as the `playwright` superuser.
type: manual-test
---

# 0008 — AI chat as collapsible right sidebar — Manual tests

Pre-reqs:
- Django on `:8006`, Vite on `:5173`, `LLM_API_KEY` set.
- Logged in as `playwright` / `playwright`.
- Browser DevTools open with the "responsive" / device-toolbar mode available — several tests need explicit viewport sizes.

## Test 1 — Wide viewport default

**Steps**

1. Set viewport to **1280×800** (wider than the 1024px breakpoint).
2. Hard-reload `http://localhost:5173/schedule/2026-05-12/` (or any future date; pick a non-busy day).
3. Observe initial UI state.

**Expected**

- Right-hand sidebar visible, ~380px wide, light background.
- Header shows "AI Chat" and a `›` collapse button.
- Textarea is visibly large — about 6 lines tall — before typing anything.
- No bottom dock (`.command-bar.variant-dock` not present).
- Schedule remains centered with no overlap from the sidebar.

## Test 2 — Toggle collapse / expand

**Steps**

1. From Test 1's state, click the `›` button in the sidebar header.
2. Observe.
3. Click the `‹` button on the resulting rail.

**Expected**

- Sidebar collapses to a 32px rail with a `‹` button. Header text and textarea are unmounted.
- Schedule content stays fully visible — no horizontal scroll, no `TimeBlock` hidden under the sidebar.
- Clicking `‹` expands the sidebar back to 380px with the same chat thread visible (no message loss).

## Test 3 — Persistence after reload (wide)

**Steps**

1. Collapse the sidebar (Test 2 step 1).
2. Reload the page (Cmd+R / F5).

**Expected**

- Sidebar restores in the collapsed state (32px rail, `‹` button).
- `localStorage.getItem("day-forge:chat-sidebar:open")` returns `"false"` in the browser console.

## Test 3a — Cross-viewport persistence

**Steps**

1. From the collapsed wide state (Test 3), resize the window below **1024px** (e.g. 900×800).
2. Observe.
3. Reload at the narrow size.

**Expected**

- The bottom dock variant is visible and functional — the persisted `false` does NOT hide the only AI entry point on narrow viewports.
- localStorage still holds `"false"`, but is intentionally ignored on narrow.

## Test 3b — Breakpoint boundary

**Steps**

1. Set viewport to exactly **1024×768**.
2. Observe.
3. Resize to exactly **1023×768**.
4. Observe.

**Expected**

- At 1024px → sidebar variant renders. No bottom dock.
- At 1023px → bottom dock variant renders. No sidebar.

## Test 3c — Horizontal-overflow check at the boundary

**Steps**

1. Viewport at exactly **1024×768**, sidebar open.
2. Scroll through the schedule body.

**Expected**

- No horizontal scrollbar on `<html>`.
- No part of any `TimeBlock` is hidden under the sidebar's left edge.

**If overflow appears** — first fix is to narrow the sidebar to 360px (pure CSS, keeps the 1024px breakpoint). Last resort is raising the breakpoint to `(min-width: 1040px)`; that **changes the product decision** and MUST be called out in the PR description.

## Test 3d — Thread-scroll inside sidebar

**Steps**

1. Sidebar open on a wide viewport.
2. Exchange enough turns (≥10 short messages, OR one long pasted brief that wraps to many lines) to overflow the visible thread area.

**Expected**

- Older messages scroll inside the `.thread` element (panel grows its own scrollbar).
- The textarea and privacy hint remain anchored at the bottom of the panel, fully visible.
- Textarea is never pushed off-screen by long history.

## Test 4 — Narrow viewport (regression)

**Steps**

1. Set viewport to **900×800**.
2. Hard-reload the schedule page.

**Expected**

- No sidebar. Bottom dock visible at the bottom of the page.
- Textarea max ~10 rows (unchanged from feature 0007).
- All six AI-chat Playwright scripts pass if re-run at this viewport:
  - `ai-chat-clarifying-question.mjs`
  - `ai-chat-clear-cancels-inflight.mjs`
  - `ai-chat-date-change-resets-thread.mjs`
  - `ai-chat-privacy-hint-always-on.mjs`
  - `ai-chat-single-turn-apply.mjs`
  - `ai-chat-token-race.mjs`

Playwright launches with a default 1280×720 viewport, so those scripts will exercise the **sidebar** variant by default. They query by `data-testid`, which is preserved across variants.

## Test 5 — Cross-viewport thread survival

**Steps**

1. On wide (sidebar open), send 2 messages; verify they appear in the thread.
2. Resize the window to below 1024px.
3. Observe the bottom dock.

**Expected**

- The same 2 messages are visible in the dock's thread strip (latest-4 cap).
- Sending a new message from the dock works; resizing back to wide shows all 3 messages in the sidebar (no cap).

## Test 6 — `/` global hotkey

**Steps**

1. Wide viewport, sidebar open. Click on an empty area of the page so focus is on `<body>`.
2. Press `/`.
3. Collapse the sidebar.
4. With focus on body again, press `/`.

**Expected**

- Step 2 → textarea inside the sidebar receives focus.
- Step 4 → no-op. The sidebar does NOT auto-expand on `/`. This is intentional: prevents stray keystrokes from causing layout shifts.

## Test 7 — Schedule visual integrity at edge widths

**Steps**

1. Viewport at exactly **1280×800** (typical Playwright default). Sidebar open.
2. Verify schedule layout looks right.
3. Resize to **1600×800**.

**Expected**

- Schedule column remains 640px wide and stays centered in the available area (viewport minus 380px sidebar).
- No content sits beneath the sidebar.

## Test 8 — A11y of the toggle button

**Steps**

1. Open the sidebar.
2. Open DevTools → Accessibility tree → focus the toggle button.
3. Collapse the sidebar.
4. Re-inspect the toggle button (now in the rail).

**Expected**

- Open state: button has `type="button"`, `aria-label="Collapse AI chat panel"`, `aria-expanded="true"`, `aria-controls="chat-sidebar-body"`.
- Collapsed state: button has `type="button"`, `aria-label="Expand AI chat panel"`, `aria-expanded="false"`, `aria-controls="chat-sidebar-body"`.

---

## Done when

- All tests above pass.
- Existing 0007 Playwright suite passes (`for f in frontend/scripts/playwright/ai-chat-*.mjs; do node "$f"; done`).
- `cd frontend && npm test` reports green.
- `cd frontend && npx vue-tsc --noEmit` reports clean.
