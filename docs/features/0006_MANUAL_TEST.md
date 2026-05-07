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

- [x] Open http://localhost:5173/ and log in.
- [x] DevTools → **Network** (filter `Fetch/XHR`) and **Console**.
- [x] Have a shell ready to inspect rows:
  ```bash
  uv run python backend/manage.py shell -c "from analytics.models import DailyReview; [print(r.schedule.date, r.schedule.status, r.completed_count, r.planned_count, r.updated_at) for r in DailyReview.objects.order_by('-updated_at')[:10]]"
  ```

Endpoints to watch:
`GET /analytics/<date>/`,
`POST /api/analytics/schedules/<date>/mark-reviewed/`,
`PATCH /api/analytics/reviews/<pk>/notes/`.

- [x] Set up a past day with some completed/uncompleted blocks before starting
  (e.g. `/schedule/<yesterday>/`, add 4 blocks, check 2 of them).

---

## Test 1 — Analytics view recomputes on every visit while ACTIVE

**Pre-state**: a past schedule with `status=active` and a mix of
completed/uncompleted blocks.

- [x] Visit `/analytics/<that-date>/`.
- [x] **Network**: a single `GET /analytics/<date>/` (Inertia). No JSON
  round-trip for the panel data.
- [x] The page shows: CompletionBar with the right ratio, CategoryBreakdown
  with 4 rows (work/personal/health/other), StreakCounter, SkippedTasks
  list (uncompleted blocks listed; completed ones absent), Notes textarea.
- [x] Status badge reads **Active**; **Mark reviewed** button is visible.
- [x] In another tab, edit a block on `/schedule/<that-date>/` (toggle
  completion).
- [x] Refresh the analytics page. The CompletionBar reflects the change;
  `updated_at` advances (verify via the shell query above).

---

## Test 2 — Mark reviewed flips status and freezes the snapshot

- [x] From the analytics page (still ACTIVE, with notes empty or filled),
  click **Mark reviewed**.
- [x] **Network**: `POST /api/analytics/schedules/<date>/mark-reviewed/`
  → `200`. The response body is the persisted `DailyReview`.
- [x] The page reloads (Inertia partial: `["review", "schedule"]`). Status
  badge flips to **Reviewed**; the **Mark reviewed** button disappears.
- [x] Verify in shell: `Schedule.status == "reviewed"`,
  `DailyReview.notes == "<whatever was in the textarea>"`.
- [x] Click **Mark reviewed** again is impossible (button hidden). To test
  server-side idempotency, use curl:
  ```bash
  curl -s -X POST -b cookies.txt -H "X-XSRF-TOKEN: $CSRF" \
    -H "Content-Type: application/json" \
    http://localhost:8006/api/analytics/schedules/<date>/mark-reviewed/
  # → 200 with the same updated_at as the first call
  ```
- [x] Verify the second call's `updated_at` matches the first.

---

## Test 3 — Idempotent on already-reviewed: body is ignored entirely

- [x] Different notes value — must NOT overwrite the persisted notes:
  ```bash
  curl -s -X POST -b cookies.txt -H "X-XSRF-TOKEN: $CSRF" \
    -H "Content-Type: application/json" \
    -d '{"notes": "different"}' \
    http://localhost:8006/api/analytics/schedules/<date>/mark-reviewed/
  # → 200 with the ORIGINAL notes (not "different")
  ```
- [x] Malformed JSON — must NOT 400:
  ```bash
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

- [x] Navigate from `/analytics/<date>/` to `/schedule/<that-date>/` via
  the **← Back to schedule** link.
- [x] Toggle any block's completion checkbox.
- [x] **Network**: `PATCH /api/blocks/<id>/` → `200`. Inertia partial
  reloads `["blocks", "schedule"]`.
- [x] Status badge flips back to (no badge — the regular schedule view
  doesn't show the analytics-page badges).
- [x] Visit `/analytics/<date>/` again. Status badge is **Active**;
  **Mark reviewed** button is back; the panel reflects the edit
  (CompletionBar updated, `updated_at` advanced).
- [x] Repeat for the other forward-mutating endpoints to confirm the
  pattern: `+ Add Block`, drag-to-reorder, `× Delete`, AI command
  bar with a non-empty action.

The unfreezing comes from `mark_active_on_edit()` (the renamed
`mark_active_if_draft`), which is wired into every mutation endpoint.

---

## Test 5 — Notes auto-save (debounced)

- [X] Visit `/analytics/<date>/` (ACTIVE).
- [X] Type into the Notes textarea. The first keystroke does NOT fire a
  request.
- [X] Wait 1 second after the last keystroke. **Network**: `PATCH
  /api/analytics/reviews/<pk>/notes/` → `200`.
- [X] Continue typing — each batch of fast keystrokes results in exactly
  one PATCH after a 1s pause.
- [X] Refresh the page; the saved notes are preserved.
- [X] Mark reviewed. Notes still editable via the same PATCH endpoint
  (the textarea remains usable).

---

## Test 6 — Streak counter walks calendar days

**Pre-state**: at least 3 consecutive past days each with at least 80%
completion (the default `ANALYTICS_STREAK_THRESHOLD`).

- [x] Visit `/analytics/<today>/` (or any past day with a schedule).
- [x] The streak pill shows `🔥 N-day streak` where N matches the count
  of consecutive ≥80% days backward from yesterday.
- [x] Set up a "gap day" (a calendar day with NO `Schedule` row) somewhere
  in the streak.
- [x] Refresh — the streak count is now the days since today until the gap.
- [x] Replace the gap with a zero-block "rest day" Schedule
  (`Schedule.objects.create(user=..., date=..., status='active')` with
  no blocks). Refresh — the streak counts the 80% days *across* the
  rest day (rest days are skipped, not breaks).
- [x] Add a below-threshold day in the middle (e.g. 1/3 completed = 33%).
  Refresh — the streak count drops to the days between today and
  that below-threshold day.

---

## Test 7 — AI draft prompt includes per-day completion ratios

> 🤖 **Automated variant available.** For one-shot regression after a
> first manual run, prefer
> `frontend/scripts/playwright/draft-prompt-history-suffix.mjs` — it
> seeds inline, fires real auto-draft, captures the prompt via
> `LLM_DRAFT_CAPTURE_PROMPT_PATH`, and asserts the suffix invariants.
> One-time setup: add `LLM_DRAFT_CAPTURE_PROMPT_PATH=/tmp/draft_prompt_test7.txt`
> to `.env` and restart Django. 💸 ~$0.10 in LLM cost per run (`gpt-4o`).

**Pre-state**: at least one past day with a persisted `DailyReview`
(any day you've marked reviewed in earlier tests works).

- [x] Navigate to a fresh future weekday you have NEVER visited (e.g.
  `/schedule/<two-weeks-from-now>/`). Auto-draft will fire if you have
  a weekday template configured.
- [x] **Network**: `POST /api/ai/schedules/<date>/generate-draft/` → `200`.
- [x] Reconstruct the user message that was sent to the LLM. The prompt
  itself is **not persisted** — `AIInteraction` stores `user_command="[DRAFT]"`,
  `ai_response`, and `actions_json`, but never the rendered user message.
  Re-run the same query + `build_draft_user_message` (both pure functions
  of DB state) to render an identical user message:
  ```bash
  uv run python backend/manage.py shell -c "
  import datetime as dt
  from django.contrib.auth import get_user_model
  from django.utils import timezone
  from django.conf import settings
  from schedules.models import Schedule
  from templates_mgr.models import Template, Rule
  from ai.prompts import build_draft_user_message

  U = get_user_model()
  user = U.objects.get(username='<your-username>')
  target = dt.date(2026, 5, 18)  # ← the date visited in step 1

  template_type = 'weekday' if target.weekday() < 5 else 'weekend'
  template = Template.objects.filter(user=user, type=template_type).first()
  history_start = target - dt.timedelta(days=settings.LLM_HISTORY_DAYS)
  history = list(
      Schedule.objects.filter(
          user=user, date__lt=target, date__gte=history_start,
          status__in=[Schedule.Status.ACTIVE, Schedule.Status.REVIEWED],
      ).order_by('date').prefetch_related('time_blocks')
  )
  rules = list(Rule.objects.filter(user=user, is_active=True).order_by('-priority'))
  schedule = Schedule.objects.filter(user=user, date=target).first() or Schedule(user=user, date=target)
  print(build_draft_user_message(schedule, template, history, rules, timezone.localtime()))
  "
  ```
  This isn't a substitute for actually firing auto-draft (steps 1-2
  exercise the real view + LLM call). Reconstruction just exposes the
  prompt content, which the view doesn't write to disk.
- [x] In the printed `Recent history (last days):` section, the date
  header for a reviewed day MUST have a `(completed: X/Y)` suffix:
  ```
  # 2026-04-25 (Saturday) (completed: 5/7)
  ```
- [x] A history day **without** a `DailyReview` row MUST NOT have the
  suffix:
  ```
  # 2026-04-26 (Sunday)
  ```

The suffix only appears when `DailyReview.planned_count > 0`. Empty/zero
days are silently formatted without the suffix.

### Optional: true E2E with prompt capture

For end-to-end verification of the actually-sent prompt (not a
reconstruction), see `frontend/scripts/playwright/draft-prompt-history-suffix.mjs`.
It requires a temporary one-line patch in `backend/ai/service.py:run_draft`
that writes `user_message` to `/tmp/draft_prompt_test7.txt` immediately
before the LLM call (the script's header explains exactly what to add
and revert). **💸 One real `LLM_DRAFT_MODEL` call per run.**

---

## Test 8 — Future date 400, missing schedule 404

- [x] Future date returns 400:
  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" -b cookies.txt \
    http://localhost:8006/analytics/2099-12-31/
  # → 400
  ```
- [x] Missing schedule returns 404:
  ```bash
  curl -s -o /dev/null -w "%{http_code}\n" -b cookies.txt \
    http://localhost:8006/analytics/2026-01-01/
  # → 404 (assuming no schedule exists for 2026-01-01)
  ```

---

## Test 9 — Cross-user PK guard on notes PATCH

- [x] Create a second superuser; log in as them in a private window.
- [x] From the second user, attempt to PATCH the first user's notes:
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

- [x] Visit `/analytics/<today>/` *before* 14:00 local.
- [x] The **Skipped** section lists only the past-window uncompleted block.
- [x] Wait until after the future block's end time, OR set your system
  clock forward.
- [x] The Skipped section now lists both. The component refreshes its
  internal `currentHHMM` once a minute, mirroring `Schedule.vue`'s
  `nowMinutes` cadence.
- [x] For a past day (not today), every uncompleted block shows up
  regardless of time.
- [x] When the filtered list would be empty, the entire **Skipped**
  section is hidden (no header, no whitespace).

For an automated, deterministic version of this test (uses Playwright's
`page.clock` API to fake browser time, no system-clock changes needed),
see `frontend/scripts/playwright/skipped-tasks-today-aware.mjs`.

---

## Test 11 — Status transitions full matrix

Quick smoke of the post-Phase-6 status flow:

- [x] Visit a fresh date → status = `draft` (auto-draft may fire).
- [x] Edit any block → status = `active` (`mark_active_on_edit` fires).
- [x] Visit `/analytics/<date>/`, click **Mark reviewed** →
  status = `reviewed`; analytics frozen.
- [x] Edit any block on `/schedule/<date>/` → status flips back to
  `active`; next analytics visit recomputes.
- [x] Re-mark reviewed → status = `reviewed`; analytics re-frozen with
  the new snapshot.

**Pitfall:** the date you pick for this test must be **today or past**
(Django's `timezone.localdate()`), not future. Step 4-5 require
`GET /analytics/<date>/` to recompute, but the analytics view rejects
future dates with a 400. A future date will silently break the
recompute step and the matrix verdict can falsely PASS if it only
checks the final `reviewed` state.

Verified via the shell query in Setup.
