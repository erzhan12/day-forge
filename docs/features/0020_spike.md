# Feature 0020 — Phase 0 filter-query spike (manual)

**Status:** manual verification note (no committed live test — see why below).

## What this de-risks

`todoist_sync.service` maps the selected schedule date to a Todoist filter
`query` and fetches via `GET /api/v1/tasks/filter`:

- `selected_date == today` → `query = "today | overdue"`
- any other date → the **bare literal-date token** `query = "<YYYY-MM-DD>"`
  (Todoist `due:` semantics — NOT the `date:` keyword)

The unit tests (`backend/tests/test_todoist_sync_service.py`
`TestFilterQuerySelection`) pin the **generated** query strings, but they
mock the HTTP layer — they do **not** prove that Todoist *interprets* those
strings as intended. This is the one algorithm step with no `calendar_sync`
analog (CalDAV ran an equivalent parse spike,
`backend/tests/test_caldav_parse_spike.py`). Risk is low (the token form is
documented Todoist filter syntax) but unvalidated against the live API.

## Why no committed CI test

A live spike needs a real Todoist personal API token and burns provider
calls on every run. Gating it on an env token keeps token-less CI green but
adds a flaky external dependency for marginal value. We validate manually
during the connect smoke test instead.

## How to verify manually

With a real token connected in Settings → Todoist, on a running dev stack:

1. **Future/past exact date** — create a Todoist task due on a specific
   date `D` (e.g. tomorrow). Navigate the schedule to `D`. Confirm the task
   appears in the Todoist panel, and tasks due on *other* days do **not**.
   This exercises `query = "<YYYY-MM-DD>"`.
2. **Today + overdue** — ensure at least one task is due today and one is
   overdue (past due, not completed). Navigate to today. Confirm **both**
   appear (overdue carryover). This exercises `query = "today | overdue"`.
3. **No-due task** — a task with no due date must appear on **no** day (the
   panel is date-scoped by design). Confirm the empty-state copy reads
   "No tasks scheduled for this day." and does not imply zero Todoist tasks.

Or, against the API directly (replace `<TOKEN>` / `<DATE>`):

```bash
curl -s -H "Authorization: Bearer <TOKEN>" \
  "https://api.todoist.com/api/v1/tasks/filter?query=<DATE>&limit=200" | jq '.results | length'
curl -s -H "Authorization: Bearer <TOKEN>" \
  --data-urlencode "query=today | overdue" --get \
  "https://api.todoist.com/api/v1/tasks/filter?limit=200" | jq '.results | length'
```

If the literal-date token ever returns the wrong set, switch the generated
query in `service.py` (`_filter_query`) and update
`TestFilterQuerySelection` to match.
