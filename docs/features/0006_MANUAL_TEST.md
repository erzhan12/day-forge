# Phase 6 — Analytics & End-of-Day Review Manual Test Plan

Scope: the per-day analytics panel at `/analytics/<date>/`, the
**Mark reviewed** flow, the auto-unfreeze on edit, the streak counter,
the today-aware skipped-tasks list, the notes auto-save, and the
analytics injection into the AI draft prompt.

---

## Setup

Two terminals (from **project root**):

```bash
# Terminal 1 — Django (:8006)
# Set LLM_API_KEY in .env to exercise the AI prompt injection path (Test 7).
make run

# Terminal 2 — Vite (:5173)
make frontend-dev
```

1. Open http://localhost:5173/ and log in.
2. DevTools → **Network** (filter `Fetch/XHR`) and **Console**.
3. Have a shell ready to inspect rows:
   ```bash
   uv run python backend/manage.py shell -c "from analytics.models import DailyReview; [print(r.schedule.date, r.schedule.status, r.completed_count, r.planned_count, r.updated_at) for r in DailyReview.objects.order_by('-updated_at')[:10]]"
   ```

Endpoints to watch:
`GET /analytics/<date>/`,
`POST /api/analytics/schedules/<date>/mark-reviewed/`,
`PATCH /api/analytics/reviews/<pk>/notes/`.

Set up a past day with some completed/uncompleted blocks before starting
(e.g. `/schedule/<yesterday>/`, add 4 blocks, check 2 of them).

---

## Test 1 — Analytics view recomputes on every visit while ACTIVE

**Pre-state**: a past schedule with `status=active` and a mix of
completed/uncompleted blocks.

1. Visit `/analytics/<that-date>/`.
2. **Network**: a single `GET /analytics/<date>/` (Inertia). No JSON
   round-trip for the panel data.
3. The page shows: CompletionBar with the right ratio, CategoryBreakdown
   with 4 rows (work/personal/health/other), StreakCounter, SkippedTasks
   list (uncompleted blocks listed; completed ones absent), Notes textarea.
4. Status badge reads **Active**; **Mark reviewed** button is visible.
5. In another tab, edit a block on `/schedule/<that-date>/` (toggle
   completion).
6. Refresh the analytics page. The CompletionBar reflects the change;
   `updated_at` advances (verify via the shell query above).

---

## Test 2 — Mark reviewed flips status and freezes the snapshot

1. From the analytics page (still ACTIVE, with notes empty or filled),
   click **Mark reviewed**.
2. **Network**: `POST /api/analytics/schedules/<date>/mark-reviewed/`
   → `200`. The response body is the persisted `DailyReview`.
3. The page reloads (Inertia partial: `["review", "schedule"]`). Status
   badge flips to **Reviewed**; the **Mark reviewed** button disappears.
4. Verify in shell: `Schedule.status == "reviewed"`,
   `DailyReview.notes == "<whatever was in the textarea>"`.
5. Click **Mark reviewed** again is impossible (button hidden). To test
   server-side idempotency, use curl:
   ```bash
   curl -s -X POST -b cookies.txt -H "X-XSRF-TOKEN: $CSRF" \
     -H "Content-Type: application/json" \
     http://localhost:8006/api/analytics/schedules/<date>/mark-reviewed/
   # → 200 with the same updated_at as the first call
   ```
6. Verify the second call's `updated_at` matches the first.

---

## Test 3 — Idempotent on already-reviewed: body is ignored entirely

```bash
# Different notes value — must NOT overwrite the persisted notes.
curl -s -X POST -b cookies.txt -H "X-XSRF-TOKEN: $CSRF" \
  -H "Content-Type: application/json" \
  -d '{"notes": "different"}' \
  http://localhost:8006/api/analytics/schedules/<date>/mark-reviewed/
# → 200 with the ORIGINAL notes (not "different")

# Malformed JSON — must NOT 400.
curl -s -X POST -b cookies.txt -H "X-XSRF-TOKEN: $CSRF" \
  -H "Content-Type: application/json" \
  -d '{not json' \
  http://localhost:8006/api/analytics/schedules/<date>/mark-reviewed/
# → 200 with the persisted snapshot
```

The `200` on a malformed body is the regression that pins the
"body parsed only after under-lock status check" rule — without that
ordering, a flaky network's retry would surface as a `400` even though
the previous attempt succeeded.

---

## Test 4 — Editing a reviewed schedule unfreezes it

1. Navigate from `/analytics/<date>/` to `/schedule/<that-date>/` via
   the **← Back to schedule** link.
2. Toggle any block's completion checkbox.
3. **Network**: `PATCH /api/blocks/<id>/` → `200`. Inertia partial
   reloads `["blocks", "schedule"]`.
4. Status badge flips back to (no badge — the regular schedule view
   doesn't show the analytics-page badges).
5. Visit `/analytics/<date>/` again. Status badge is **Active**;
   **Mark reviewed** button is back; the panel reflects the edit
   (CompletionBar updated, `updated_at` advanced).
6. Repeat for the other forward-mutating endpoints to confirm the
   pattern: `+ Add Block`, drag-to-reorder, `× Delete`, AI command
   bar with a non-empty action.

The unfreezing comes from `mark_active_on_edit()` (the renamed
`mark_active_if_draft`), which is wired into every mutation endpoint.

---

## Test 5 — Notes auto-save (debounced)

1. Visit `/analytics/<date>/` (ACTIVE).
2. Type into the Notes textarea. The first keystroke does NOT fire a
   request.
3. Wait 1 second after the last keystroke. **Network**: `PATCH
   /api/analytics/reviews/<pk>/notes/` → `200`.
4. Continue typing — each batch of fast keystrokes results in exactly
   one PATCH after a 1s pause.
5. Refresh the page; the saved notes are preserved.
6. Mark reviewed. Notes still editable via the same PATCH endpoint
   (the textarea remains usable).

---

## Test 6 — Streak counter walks calendar days

**Pre-state**: at least 3 consecutive past days each with at least 80%
completion (the default `ANALYTICS_STREAK_THRESHOLD`).

1. Visit `/analytics/<today>/` (or any past day with a schedule).
2. The streak pill shows `🔥 N-day streak` where N matches the count
   of consecutive ≥80% days backward from yesterday.
3. Set up a "gap day" (a calendar day with NO `Schedule` row) somewhere
   in the streak.
4. Refresh — the streak count is now the days since today until the gap.
5. Replace the gap with a zero-block "rest day" Schedule
   (`Schedule.objects.create(user=..., date=..., status='active')` with
   no blocks). Refresh — the streak counts the 80% days *across* the
   rest day (rest days are skipped, not breaks).
6. Add a below-threshold day in the middle (e.g. 1/3 completed = 33%).
   Refresh — the streak count drops to the days between today and
   that below-threshold day.

---

## Test 7 — AI draft prompt includes per-day completion ratios

**Pre-state**: at least one past day with a persisted `DailyReview`
(any day you've marked reviewed in earlier tests works).

1. Navigate to a fresh future weekday you have NEVER visited (e.g.
   `/schedule/<two-weeks-from-now>/`). Auto-draft will fire if you have
   a weekday template configured.
2. **Network**: `POST /api/ai/schedules/<date>/generate-draft/` → `200`.
3. In the shell, inspect the latest draft AIInteraction row:
   ```bash
   uv run python backend/manage.py shell -c "from ai.models import AIInteraction; i = AIInteraction.objects.filter(kind='draft').last(); print(i.ai_response[:500])"
   ```
4. Look at the prompt that was sent. The `Recent history` section
   should contain a date header line for the reviewed day with a
   `(completed: X/Y)` suffix:
   ```
   # 2026-04-25 (Saturday) (completed: 5/7)
   ```
5. A history day **without** a `DailyReview` row should NOT have the
   suffix:
   ```
   # 2026-04-26 (Sunday)
   ```

The suffix only appears when `DailyReview.planned_count > 0`. Empty/zero
days are silently formatted without the suffix.

---

## Test 8 — Future date 400, missing schedule 404

```bash
curl -s -o /dev/null -w "%{http_code}\n" -b cookies.txt \
  http://localhost:8006/analytics/2099-12-31/
# → 400

curl -s -o /dev/null -w "%{http_code}\n" -b cookies.txt \
  http://localhost:8006/analytics/2026-01-01/
# → 404 (assuming no schedule exists for 2026-01-01)
```

---

## Test 9 — Cross-user PK guard on notes PATCH

1. Create a second superuser; log in as them in a private window.
2. From the second user, attempt to PATCH the first user's notes:
   ```bash
   curl -s -o /dev/null -w "%{http_code}\n" \
     -X PATCH -b user_b_cookies.txt -H "X-XSRF-TOKEN: $CSRF_B" \
     -H "Content-Type: application/json" \
     -d '{"notes":"hacked"}' \
     http://localhost:8006/api/analytics/reviews/<user-A-review-id>/notes/
   # → 404 (not 403 — id-enumeration guard)
   ```

---

## Test 10 — SkippedTasks today-aware filtering

**Pre-state**: today's schedule has both past-window and future-window
uncompleted blocks (e.g. one that ends at 09:00 and one that starts at
14:00).

1. Visit `/analytics/<today>/` *before* 14:00 local.
2. The **Skipped** section lists only the past-window uncompleted block.
3. Wait until after the future block's end time, OR set your system
   clock forward.
4. The Skipped section now lists both. The component refreshes its
   internal `currentHHMM` once a minute, mirroring `Schedule.vue`'s
   `nowMinutes` cadence.
5. For a past day (not today), every uncompleted block shows up
   regardless of time.
6. When the filtered list would be empty, the entire **Skipped**
   section is hidden (no header, no whitespace).

---

## Test 11 — Status transitions full matrix

Quick smoke of the post-Phase-6 status flow:

1. Visit a fresh date → status = `draft` (auto-draft may fire).
2. Edit any block → status = `active` (`mark_active_on_edit` fires).
3. Visit `/analytics/<date>/`, click **Mark reviewed** →
   status = `reviewed`; analytics frozen.
4. Edit any block on `/schedule/<date>/` → status flips back to
   `active`; next analytics visit recomputes.
5. Re-mark reviewed → status = `reviewed`; analytics re-frozen with
   the new snapshot.

Verified via the shell query in Setup.
