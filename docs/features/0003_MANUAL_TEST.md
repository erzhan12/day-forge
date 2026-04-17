# Phase 3 — Manual Test Plan

Scope: drag-and-drop reordering, cascade conflict resolution, and the client-side undo stack (drag, inline edit, checkbox toggle, add, delete).

---

## Setup

Two terminals:

```bash
# Terminal 1 — Django
uv run python backend/manage.py runserver 8006

# Terminal 2 — Vite
cd frontend && npm run dev
```

1. Open http://localhost:5173/ and log in.
2. Navigate to a day that has **4–6 time blocks**. If empty, add several blocks spread across the day (e.g. 09:00, 10:30, 13:00, 15:00, 17:00) before starting.
3. Open DevTools → **Network** tab (filter: `Fetch/XHR`) and **Console**. Keep both visible while testing.

Expected endpoints to watch:
- `POST /api/schedules/<date>/blocks/reorder/` — drag save
- `POST /api/schedules/<date>/blocks/restore/` — undo
- `PATCH /api/blocks/<id>/` — inline edit + checkbox toggle
- `POST /api/schedules/<date>/blocks/` — add
- `DELETE /api/blocks/<id>/` — delete

---

## 1. Basic drag-and-drop

- [ ] Press and hold the **drag handle on the left edge** of a block. Body cursor changes; a ghost of the block follows the pointer.
- [ ] Drag the ghost to an empty slot and release.
- [ ] Expect: ghost disappears, block lands at the new time, one `reorder/` request returns **200**.
- [ ] Reload the page — the new time persists.

## 2. Snap-to-grid (5 min)

- [ ] Start a drag and move the pointer slowly across ~15 minutes of vertical space.
- [ ] The ghost's time badge jumps in **5-minute increments only** (e.g. 09:00 → 09:05 → 09:10). Never lands on 09:03 or 09:07.

## 3. Live time badge preview

- [ ] While dragging, the ghost shows the **projected start–end time** updating in real time.
- [ ] Other blocks that would be displaced during cascade show a **shifted-state visual cue** (check `shiftedBlockIds` styling).

## 4. Conflict resolution — forward cascade

- [ ] Drag a block onto a slot already occupied by another block.
- [ ] Expect: the overlapping block(s) **slide forward** with a smooth ~200 ms animation. The dragged block lands exactly where you dropped it.
- [ ] Drop a block onto a spot where **3+ subsequent blocks overlap** in a row — all downstream blocks cascade forward in one pass.

## 5. Conflict resolution — dragged-backwards anchor

- [ ] Drag a block *backwards in time* onto an earlier block's slot.
- [ ] Expect: the **earlier block moves forward past** the dragged one. The dragged block stays anchored at the drop position (it does *not* get pushed back).

## 6. Invalid drop (end-of-day overflow)

- [ ] Drag a block near the end of the day such that the cascade would push a trailing block past **23:00**.
- [ ] Expect: ghost shows an **invalid-drop state**; releasing cancels the drag with **no** `reorder/` network call.
- [ ] Block returns to its original position.

## 7. Escape to cancel

- [ ] Start a drag, move the ghost away from origin, press **Esc** before releasing.
- [ ] Expect: no network call; block stays at original time; body cursor resets.

---

## 8. Undo — drag

- [ ] After a successful drag, a toast appears at the bottom: *"Moved "{title}" to HH:MM — Undo"*.
- [ ] Click **Undo** in the toast.
- [ ] Expect: block returns to original position; toast changes to *"Undone: Moved …"* and auto-dismisses in ~8 s. One `restore/` call returns **200**.
- [ ] Repeat the drag, this time press **Ctrl+Z** (⌘+Z on macOS) instead of clicking. Same result.

## 9. Undo — inline edit

- [ ] Click a block's title, change it, press **Enter** (or blur).
- [ ] Toast appears. Press Ctrl/⌘+Z.
- [ ] Title reverts to the prior value.

## 10. Undo — checkbox toggle

- [ ] Check or uncheck the completion checkbox on a block.
- [ ] Press Ctrl/⌘+Z.
- [ ] Checkbox returns to prior state.

## 11. Undo — add

- [ ] Use the Add form to create a new block.
- [ ] Press Ctrl/⌘+Z.
- [ ] The newly added block disappears.

## 12. Undo — delete

- [ ] Delete a block (confirm the dialog).
- [ ] Press Ctrl/⌘+Z.
- [ ] The deleted block reappears with its original title, time, and completion state.

## 13. Consecutive undos (LIFO)

- [ ] Perform **4 different actions** in order: drag → edit → toggle → add.
- [ ] Press Ctrl/⌘+Z four times.
- [ ] Each press reverses the **most recent** action first (add → toggle → edit → drag).
- [ ] A fifth Ctrl+Z does nothing (stack empty, no error).

## 14. Stack cap (20 actions)

- [ ] Perform **21+ actions** (fastest: toggle the same checkbox on/off repeatedly).
- [ ] Press Ctrl+Z repeatedly.
- [ ] Exactly the last 20 actions can be undone; the oldest action is dropped silently.

## 15. Toast auto-dismiss

- [ ] Trigger any action and do not interact.
- [ ] Toast disappears after **~8 seconds**.

## 16. Ctrl+Z inside text inputs

- [ ] Focus the AddBlockForm title field. Type some text. Press Ctrl/⌘+Z.
- [ ] Expect: **native text undo inside the field** (characters disappear). Schedule state is NOT undone.
- [ ] Click outside the input, press Ctrl/⌘+Z — now schedule undo fires.

---

## 17. Second drag during first drag's save (race guard)

Regression check for the `snapshot` capture fix in `useDrag.ts`.

- [ ] Drag **block A** to a new time, release.
- [ ] **Immediately** (before the `reorder/` response lands) grab **block B** and drag it to another time. Release.
- [ ] Wait for both network calls to finish.
- [ ] Press Ctrl+Z once → block B returns to its original position (block A stays moved).
- [ ] Press Ctrl+Z again → block A returns to its original position.
- [ ] **Fail signal:** any undo that wipes the entire day (all blocks disappear) or restores the wrong pre-drag state.

## 18. Cross-tab known limitation

Documenting, not blocking — confirm behavior matches the header comment in `useUndo.ts`.

- [ ] Open the same day in **two tabs** (tab A and tab B).
- [ ] In tab B: edit a block title and save.
- [ ] In tab A: press Ctrl+Z (with any pending undoable action from before tab B's edit).
- [ ] Expect (known): tab A's `restore/` call wipes tab B's edit. Not a bug for MVP; flag if it behaves any worse (e.g. crash, stuck toast).

---

## What to watch for

- **Network**: every successful drag emits exactly one `reorder/` call. Every undo emits exactly one `restore/` call. No duplicates.
- **Console**: no errors, no warnings. The expected `InvalidPointerId` / `NotFoundError` from pointer-capture release is silenced in code — if you see it surface, that's a regression.
- **Animation**: shifted blocks slide ~200 ms ease; the dragged block jumps instantly to its drop point.
- **Reload**: after each drag/edit/add/delete, the state must survive a page reload. Undo stack is in-memory — it **does not** survive reload (that's Phase 7).

---

## Failure template

If a step fails, capture:
1. Step number (e.g. "Step 17, second press of Ctrl+Z").
2. Expected vs. actual behavior.
3. Console errors (copy full text).
4. Failing Network request: method, path, status, response body.
5. Schedule state before and after (screenshot or block list).
