# Phase 5 — Templates, Rules & Drafts Manual Test Plan

Scope: the per-user `Template` + `Rule` CRUD at `/settings/`, the
`POST /api/ai/schedules/<date>/generate-draft/` endpoint, the auto-draft
trigger on a freshly opened day, the manual `Regenerate draft` button,
the draft badge, and the status-flow rules (`draft → active` on first
real edit).

---

## Setup

Two terminals (from **project root**):

```bash
# Terminal 1 — Django (:8006)
# Set LLM_API_KEY in .env before starting (drafts require it).
# Optionally tune LLM_DRAFT_MODEL / LLM_DRAFT_RATE_LIMIT_PER_HOUR / LLM_HISTORY_DAYS.
make run

# Terminal 2 — Vite (:5173)
make frontend-dev
```

1. Open http://localhost:5173/ and log in.
2. DevTools → **Network** (filter `Fetch/XHR`) and **Console**. Keep visible.
3. Inspect AIInteraction rows for drafts:
   ```bash
   uv run python backend/manage.py shell -c "from ai.models import AIInteraction; [print(i.id, i.kind, i.success, i.user_command[:30]) for i in AIInteraction.objects.order_by('-id')[:10]]"
   ```

Endpoints to watch: `POST /api/ai/schedules/<date>/generate-draft/`,
`GET/POST/PUT/DELETE /api/templates/...`,
`GET/POST/PATCH/DELETE /api/rules/...`.

---

## Test 1 — First-time setup: no template, no auto-draft

**Pre-state**: a fresh user account (no templates, no rules), no
`Schedule` row for today.

1. Run `uv run python backend/manage.py createsuperuser` if needed.
2. Visit `/schedule/<today>/`.

**Expected**:

- Page loads instantly (no spinner overlay).
- No `POST /generate-draft/` request fires.
- Schedule body shows the empty-day placeholder.
- The "Regenerate draft" pill is rendered next to the date — **disabled**
  with the inline message `No <weekday|weekend> template configured.`
- The gear icon next to the right-arrow nav links to `/settings/`.

---

## Test 2 — Settings page: create a weekday template

1. Click the gear icon → lands on `/settings/`.
2. Two empty slots are rendered: "No weekday template yet — Create" and
   "No weekend template yet — Create".
3. Click **Create template** under the weekday slot. The form appears.
4. Add three blocks (e.g. 07:00–07:30 health, 09:00–12:00 work,
   17:30–18:30 health) and click **Save**.
5. **Network**: `POST /api/templates/` → `201`.
6. The form re-renders in edit mode.
7. Try entering an overlap (09:30–10:00 inside the deep-work block) and
   save → **400** with an inline error.
8. Fix and save again → `200`.

---

## Test 3 — Settings page: rules CRUD

1. In the **Rules** section, type "No meetings before 9" and **Add rule**.
2. The row appears with priority `0`.
3. Click the row's text → inline edit appears. Change to "No meetings
   before 9 AM" and press Enter.
4. Click ▲ to bump priority. Backend `PATCH /api/rules/<id>/` → `200`.
5. Toggle the checkbox — the row fades / strikes through.
6. Click × → confirm dialog → `DELETE /api/rules/<id>/`.

---

## Test 4 — Auto-draft fires on next-day visit

1. Navigate via the date arrows to a future date you have NEVER visited
   (e.g. `/schedule/2026-05-11/`).
2. **Network**: page renders with `auto_draft_pending=true`, then
   `POST /api/ai/schedules/2026-05-11/generate-draft/` fires automatically.
3. The schedule body shows a centered spinner overlay reading
   "Generating draft…".
4. The command bar input is disabled. AddBlockForm and gap clicks are
   suppressed.
5. After ~5–10s, the draft renders. Each block has the expected category
   colour. Status badge near the date reads "Draft — edit to keep".
6. AIInteraction shell command shows a row with `kind=draft`,
   `success=True`.

---

## Test 5 — Manual regenerate

1. Delete every block individually (or via AI command "remove all"). The
   schedule body becomes empty again.
2. The **Regenerate draft** pill becomes active (no longer disabled).
3. Click it. Spinner overlay appears, draft regenerates, badge stays
   "Draft".

---

## Test 6 — Status flips on first real edit

Starting from a freshly drafted schedule (status = `draft`):

1. Click any block to inline-edit the title and press Enter.
2. **Network**: `PATCH /api/blocks/<id>/` → `200`. Inertia partial reload
   refreshes `["blocks", "schedule"]`.
3. The "Draft — edit to keep" badge disappears (status flipped to
   `active`).

Repeat from a fresh drafted schedule for each path:

- Toggle a checkbox (completion) → flips.
- Drag a block to a new slot → flips.
- Add a new block → flips.
- AI command bar with a real action ("add coffee at 10:00") → flips.

---

## Test 7 — AI command no-op does NOT flip status

1. Create a freshly drafted schedule.
2. In the command bar, type something the AI will refuse, e.g. "what's
   the weather like".
3. `POST /api/ai/schedules/<date>/command/` returns `200` with
   `actions: []` and an explanation.
4. Status badge stays "Draft".

---

## Test 8 — Undo a draft

1. From a freshly drafted day, press ⌘Z (or Ctrl+Z).
2. `POST /api/schedules/<date>/blocks/restore/` with `{"blocks": []}`.
3. Schedule becomes empty; status remains `draft`.
4. The **Regenerate draft** pill reappears, enabled.

---

## Test 9 — 409 when regenerating with existing blocks

Curl-only (the UI hides the button when blocks exist):

```bash
CSRF=$(grep XSRF-TOKEN cookies.txt | awk '{print $NF}')
curl -X POST -b cookies.txt -c cookies.txt \
  -H "X-XSRF-TOKEN: $CSRF" \
  http://localhost:8006/api/ai/schedules/<today>/generate-draft/
# → 409 {"errors":{"detail":"Schedule already has blocks; delete them before regenerating."}}
```

---

## Test 10 — Rate limit (separate counter)

1. Set `LLM_DRAFT_RATE_LIMIT_PER_HOUR=2` in `.env` and restart Django.
2. Trigger three drafts (delete blocks between calls).
3. The third call returns `429 {"errors":{"detail":"Rate limit exceeded..."}}`.
4. The command bar still works (separate counter; `LLM_RATE_LIMIT_PER_HOUR`
   was untouched).

---

## Test 11 — Multi-user isolation

1. Create a second superuser via `createsuperuser`.
2. As user A, create a weekday template "A weekday".
3. Log out, log in as user B. Visit `/settings/`.
4. The page shows two empty slots — A's template is invisible.
5. Visit `/schedule/<today>/`. The Regenerate button is disabled because
   user B has no template.
6. Confirm via shell:
   ```bash
   uv run python backend/manage.py shell -c "from templates_mgr.models import Template; [print(t.user.username, t.type) for t in Template.objects.all()]"
   ```

---

## Test 12 — 422 fallback (template deleted between page load and click)

1. Open `/schedule/<future-date>/` with the template present so the
   button is enabled.
2. In another tab, delete the template via the Settings page.
3. Click **Regenerate draft** in the original tab (without reloading).
4. `POST /generate-draft/` returns `422`.
5. The inline error reads "No template configured. Open Settings to
   create one." Manual editing still works.
