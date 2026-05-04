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

### A note on getting back to the "freshly drafted" state

Several tests below need a schedule with `status="draft"` and at least
one auto-generated block. The natural way to reach that state is to
visit a date you have NEVER visited before — `auto_draft_pending` is a
**one-shot** server prop that's only `true` on the request that *creates*
the `Schedule` row, so each scenario uses a different fresh date.

To reach `status="draft" && blocks=[]` (the state that re-shows the
Regenerate pill), press **⌘Z (or Ctrl+Z)** to undo the draft. The undo
goes through `restore_blocks([])` which deliberately does **not** flip
status — that's the only reliable way to clear blocks while keeping the
draft badge. Deleting blocks one by one in the UI flips
`status → active` on the first delete (because every forward-mutating
endpoint calls `mark_active_on_edit()` — renamed from
`mark_active_if_draft()` in Phase 6 to also cover `reviewed → active`),
so the Regenerate pill disappears.

---

## Test 1 — First-time setup: no template, no auto-draft

**Pre-state**: a fresh user account (no templates, no rules), no
`Schedule` row for today.

1. Run `uv run python backend/manage.py createsuperuser` if needed.
2. Visit `/schedule/<today>/`.

**Expected**:

- Page loads instantly (no spinner overlay).
- No `POST /generate-draft/` request fires.
- Schedule body shows a single empty-day gap (06:00–23:00).
- A "Regenerate draft" pill is rendered in the right-hand controls of
  the date navigator — visibly **disabled / muted** with the inline
  reason `No <weekday|weekend> template configured.` directly under it.
- The gear icon (⚙) sits between the pill and the right-arrow nav, and
  links to `/settings/`.

---

## Test 2 — Settings page: create a weekday template

1. Click the gear icon → lands on `/settings/`.
2. Two empty slots are rendered: `No weekday template yet.` and
   `No weekend template yet.`, each with a **Create template** button.
3. Click **Create template** under the weekday slot. The form appears
   with the slot type as a read-only tag.
4. Add three blocks (e.g. 07:00–07:30 health, 09:00–12:00 work,
   17:30–18:30 health) and click **Save**.
5. **Network**: `POST /api/templates/` → `201`.
6. The form re-renders in edit mode (the **Delete template** button now
   appears).
7. Try entering an overlap (09:30–10:00 inside the deep-work block) and
   save → **400** with the inline error list under the blocks table.
8. Fix the overlap and save again → `200`.

---

## Test 3 — Settings page: rules CRUD

1. In the **Rules** section, type "No meetings before 9" and click
   **Add rule**.
2. The row appears with priority `0`.
3. Click the row's text → it switches to an inline edit input. Change
   to "No meetings before 9 AM" and press Enter.
4. Click ▲ on the row to bump priority. Backend issues **one PATCH**
   (when the neighbour's priority differs, swaps the two values; when
   priorities tie, just bumps by ±1) — both produce `200`.
5. Toggle the checkbox → the row visually fades and the text gets a
   strikethrough (CSS `.inactive`).
6. Click × → confirm dialog → `DELETE /api/rules/<id>/` → row disappears.

---

## Test 4 — Auto-draft fires on next-day visit

**Pre-state**: weekday template exists (from Test 2), `LLM_API_KEY` set.

1. Navigate via the date arrows to a future weekday you have NEVER
   visited (e.g. `/schedule/2026-05-11/`, a Monday).
2. **Network**: page renders with `auto_draft_pending=true` in the
   Inertia props, then `POST /api/ai/schedules/2026-05-11/generate-draft/`
   fires automatically.
3. The schedule body shows a centered spinner overlay reading
   "Generating draft…".
4. While generating: the command bar input is disabled, the
   "+ Add Block" button is disabled, and gap-slot click-to-add is
   suppressed (cursor: not-allowed).
5. After ~5–10s, the draft renders. Each block has the expected
   category colour. The pill in the date navigator now reads
   "Draft — edit to keep" (the `DraftBadge`); the Regenerate pill is
   gone (it only renders when `blocks.length === 0`).
6. AIInteraction shell command shows a row with `kind=draft`,
   `success=True`.

---

## Test 5 — Status flips on first real edit

Starting from a freshly drafted schedule (Test 4 leaves you in this
state on date X — if X is consumed, navigate to a different fresh date
and let auto-draft fire).

1. Click any block to inline-edit the title and press Enter.
2. **Network**: `PATCH /api/blocks/<id>/` → `200`. Inertia partial
   reload requests `["blocks", "schedule"]`.
3. The "Draft — edit to keep" badge **disappears** (status flipped to
   `active` server-side and the partial reload picked it up).

For each of the variants below, navigate to a fresh date so auto-draft
runs again, then perform the action and confirm the badge disappears:

- Toggle a checkbox (completion) → flips.
- Drag a block to a new slot → flips.
- Add a new block via the "+ Add Block" form → flips.
- AI command bar with a real action ("add coffee at 10:00") → flips.

---

## Test 6 — AI command no-op does NOT flip status

**Pre-state**: a freshly drafted schedule (`status=draft`, blocks
present).

1. In the command bar, type something the AI will refuse, e.g. "what's
   the weather like".
2. `POST /api/ai/schedules/<date>/command/` returns `200` with
   `actions: []` and an explanation in the bar.
3. The "Draft — edit to keep" badge **stays**. (RULES.md: a 200 with
   zero actions is a successful no-op; status flip is gated on
   `len(parsed_actions) > 0`.)

---

## Test 7 — Undo a draft

**Pre-state**: a freshly drafted schedule.

1. Press ⌘Z (or Ctrl+Z).
2. **Network**: `POST /api/schedules/<date>/blocks/restore/` with
   `{"blocks": []}`.
3. Schedule becomes empty; the draft badge disappears (no blocks); the
   `status` stays `draft` (verify in the next step).
4. The **Regenerate draft** pill reappears in the date navigator,
   **enabled** (template still exists, `status=draft`, `blocks=0`).

Optional verify via shell:
```bash
uv run python backend/manage.py shell -c "from schedules.models import Schedule; s = Schedule.objects.get(date='2026-05-11'); print(s.status, s.time_blocks.count())"
# → draft 0
```

---

## Test 8 — Manual regenerate

**Pre-state**: an empty drafted schedule (the state Test 7 leaves you
in — `status=draft`, `blocks=[]`).

1. Click the **Regenerate draft** pill.
2. Spinner overlay appears; `POST /generate-draft/` fires.
3. Draft regenerates; the badge flips back to "Draft — edit to keep".

---

## Test 9 — 409 when regenerating with existing blocks

The UI hides the Regenerate button when blocks exist, so this is a
curl-only check that asserts the server-side guard.

```bash
# 1. Log in (sets sessionid + XSRF-TOKEN cookies). The login view
# accepts JSON when Content-Type is application/json.
curl -s -c cookies.txt -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"username":"<your-username>","password":"<your-password>"}' \
  http://localhost:8006/accounts/login/ > /dev/null

CSRF=$(grep XSRF-TOKEN cookies.txt | awk '{print $NF}')

# 2. Hit generate-draft on a date that has blocks.
curl -X POST -b cookies.txt \
  -H "X-XSRF-TOKEN: $CSRF" \
  -H "Content-Type: application/json" \
  http://localhost:8006/api/ai/schedules/<date-with-blocks>/generate-draft/
# → 409 {"errors":{"detail":"Schedule already has blocks; delete them before regenerating."}}
```

The 409 path does **not** consume the rate-limit budget (see Test 10).

---

## Test 10 — Rate limit (separate counter, preconditions don't burn budget)

### 10a. Burn the budget via real LLM calls

1. Set `LLM_DRAFT_RATE_LIMIT_PER_HOUR=2` in `.env` and restart Django.
2. Visit a fresh weekday date (e.g. `/schedule/2026-05-12/`) — auto-draft
   fires (counter = 1).
3. ⌘Z to undo (state: `status=draft`, `blocks=[]`).
4. Click **Regenerate draft** — runs (counter = 2).
5. ⌘Z again.
6. Click **Regenerate draft** → `429`. The inline error under the
   schedule body reads "Draft rate limit reached. Try again later."
7. Confirm the **command bar still works** (separate counter; an AI
   command on a different schedule should not 429).

### 10b. 409 / 422 / 413 / 400 must NOT consume budget

This pins down the regression we landed in this PR.

1. Reset the cache so the counter starts at 0:
   ```bash
   uv run python backend/manage.py shell -c "from django.core.cache import cache; cache.clear()"
   ```
   (FileBasedCache stores entries under `.cache/` — clearing the cache
   resets every counter atomically.)
2. With `LLM_DRAFT_RATE_LIMIT_PER_HOUR=2`, hit the endpoint 3 times via
   curl against a date that has blocks (forces 409 each time):
   ```bash
   for i in 1 2 3; do
     curl -s -o /dev/null -w "%{http_code}\n" \
       -X POST -b cookies.txt \
       -H "X-XSRF-TOKEN: $CSRF" \
       -H "Content-Type: application/json" \
       http://localhost:8006/api/ai/schedules/<date-with-blocks>/generate-draft/
   done
   # → 409 409 409  (NOT 409 409 429)
   ```
3. Inspect the counter: it should be missing entirely or be 0.
   ```bash
   uv run python backend/manage.py shell -c "from django.core.cache import cache; print(cache.get('ai_draft_rl:1'))"
   # → None
   ```

---

## Test 11 — Multi-user isolation

1. Create a second superuser via `createsuperuser`.
2. As user A, create a weekday template named "A weekday".
3. Log out, log in as user B. Visit `/settings/`.
4. The page shows two empty slots — A's template is invisible.
5. Visit `/schedule/<today>/`. The Regenerate button is **disabled**
   for user B because they have no template.
6. Confirm via shell:
   ```bash
   uv run python backend/manage.py shell -c "from templates_mgr.models import Template; [print(t.user.username, t.type) for t in Template.objects.all()]"
   ```
7. (Cross-user PK guard) As user B, try to PUT user A's template by id
   — server returns **404** (not 403):
   ```bash
   curl -X PUT -b cookies.txt -H "X-XSRF-TOKEN: $CSRF" \
     -H "Content-Type: application/json" \
     -d '{"name":"hacked","type":"weekday","blocks":[]}' \
     http://localhost:8006/api/templates/<user-A-template-id>/
   # → 404 {"errors":{"detail":"Not found."}}
   ```

---

## Test 12 — 422 fallback (template deleted between page load and click)

1. Open `/schedule/<future-weekday>/` with the weekday template present.
   Wait for auto-draft to finish, then ⌘Z to clear blocks. Now the
   Regenerate pill is visible and enabled.
2. In another browser tab, open `/settings/` and **delete** the weekday
   template.
3. Switch back to the schedule tab WITHOUT reloading and click
   **Regenerate draft**. Inertia's `has_template_for_type` prop is
   stale, so the button is still locally enabled.
4. **Network**: `POST /generate-draft/` → `422`.
5. The inline error reads "No template configured. Open Settings to
   create one." Manual editing (drag, edit, delete, +Add Block) still
   works.
6. After clicking the gear and re-creating the template, returning to
   the schedule re-renders with `has_template_for_type=true` and the
   button is enabled again.
