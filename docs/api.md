# Day Forge API

JSON endpoints for managing schedules and time blocks. Page routes (`/`, `/schedule/<date>/`, `/accounts/login/`) render Inertia pages and are not covered here.

## Conventions

- **Base URL:** same host as Django (`http://localhost:8006` in dev; Vite dev server proxies `/api/*` to it).
- **Content type:** `application/json` for all request bodies.
- **Authentication:** session cookie. All endpoints require `@login_required`; unauthenticated requests receive `302` → `/accounts/login/`.
- **CSRF:** Django's CSRF middleware is active. Clients must:
  1. Obtain the `XSRF-TOKEN` cookie by hitting any `@ensure_csrf_cookie` view (e.g. `GET /accounts/login/` or `GET /schedule/<date>/`).
  2. Send the token back in the `X-XSRF-TOKEN` header on every unsafe request. Missing or mismatched token → `403`.
- **Time format:** `HH:MM`, 24-hour, 5-minute granularity (validated at the model layer).
- **Date format:** `YYYY-MM-DD`.
- **Errors:** non-`2xx` responses return `{"errors": {<field>: <message>}}`. Field is either a request field name or a logical key (`time`, `body`, `detail`).

## Endpoints

### `POST /api/schedules/{date}/blocks/`

Create a time block on the schedule for the given date, owned by the authenticated user. If the user has no schedule for that date, one is created.

**Path params**

| Name | Type | Notes |
|------|------|-------|
| `date` | string | `YYYY-MM-DD`. Invalid format → `400`. |

**Request body**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `title` | string | yes | 1–255 chars after `strip()`. |
| `start_time` | string | yes | `HH:MM`, 5-minute increments, `< end_time`. |
| `end_time` | string | yes | `HH:MM`, 5-minute increments, `> start_time`. |
| `category` | string | no | One of `work`, `personal`, `health`, `other`. Default `other`. |

**Success — `201 Created`**

```json
{
  "id": 42,
  "title": "Deep work",
  "start_time": "09:00",
  "end_time": "10:30",
  "category": "work",
  "is_completed": false,
  "sort_order": 0
}
```

**Errors — `400`**

| `errors` key | Meaning |
|--------------|---------|
| `body` | Request body is not valid JSON. |
| `date` | Path date is not `YYYY-MM-DD`. |
| `title` | Missing, empty after strip, or > 255 chars. |
| `start_time` / `end_time` | Missing or not in `HH:MM` format. |
| `category` | Not one of the allowed choices. |
| `time` | `start_time >= end_time`, or block overlaps an existing block on the same schedule. |

The overlap check runs inside `transaction.atomic()` but is **not** race-safe against concurrent requests on SQLite (no row locks available). Any production deployment that serves real concurrent users should move to PostgreSQL (where `select_for_update` actually takes row locks) and add a DB-level exclusion constraint on `(schedule, [start_time, end_time))` as defence-in-depth. The same caveat applies to `PATCH /api/blocks/{pk}/`, `POST /api/blocks/reorder/`, and `POST /api/schedules/{date}/blocks/restore/`.

---

### `PATCH /api/blocks/{pk}/`

Partially update a time block. Only fields present in the request body are modified. The block must be owned (via `schedule.user`) by the authenticated user.

**Path params**

| Name | Type | Notes |
|------|------|-------|
| `pk` | integer | TimeBlock primary key. |

**Request body** (all optional, but at least one field should be present)

| Field | Type | Notes |
|-------|------|-------|
| `title` | string | 1–255 chars after `strip()`. |
| `start_time` | string | `HH:MM`, 5-minute increments. If set, resulting `start < end` must still hold and no other block on the same schedule may overlap. |
| `end_time` | string | Same rules as `start_time`. |
| `category` | string | One of `work`, `personal`, `health`, `other`. |
| `is_completed` | boolean | — |
| `sort_order` | integer | `0 ≤ n ≤ 10000`. Booleans rejected. |

**Success — `200 OK`** — same shape as the `POST` response.

**Errors**

| Status | `errors` key | Meaning |
|--------|--------------|---------|
| `400` | `body` | Request body is not valid JSON. |
| `400` | `title` | Not a string, empty after strip, or > 255 chars. |
| `400` | `start_time` / `end_time` | Not in `HH:MM` format. |
| `400` | `category` | Not one of the allowed choices. |
| `400` | `sort_order` | Not an integer, or out of bounds. |
| `400` | `time` | Resulting `start >= end`, or overlaps another block. |
| `403` | `detail` | CSRF token missing/invalid. |
| `404` | `detail` | No block with that `pk`, **or** the block belongs to another user. Cross-user access deliberately returns 404 rather than 403 to avoid leaking the existence of block IDs outside the caller's own schedule. |

---

### `DELETE /api/blocks/{pk}/`

Delete a time block owned by the authenticated user.

**Success — `200 OK`**

```json
{"ok": true}
```

**Errors**

| Status | `errors` key | Meaning |
|--------|--------------|---------|
| `403` | `detail` | CSRF token missing/invalid. |
| `404` | `detail` | No block with that `pk`, **or** the block belongs to another user (see the PATCH section above for the rationale). |

---

### `POST /api/blocks/reorder/`

Batch-update the times and sort order of multiple blocks after a drag-and-drop operation. All blocks must belong to the same schedule owned by the authenticated user. The final schedule state (updated + unchanged blocks) is validated for overlaps.

**Limits**

- `updates` array is capped at **100 entries**. Larger payloads are rejected with `400 {"errors": {"updates": "Cannot update more than 100 blocks at once."}}`.
- The raw request body is capped at **100 KB**. Larger bodies are rejected with `413 {"errors": {"body": "Request body too large."}}` *before* JSON parsing, so malicious clients cannot force expensive parsing.

**Request body**

```json
{
  "updates": [
    {
      "id": 42,
      "start_time": "10:00",
      "end_time": "11:00",
      "sort_order": 0
    }
  ]
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `updates` | array | yes | Non-empty list of block updates. |
| `updates[].id` | integer | yes | TimeBlock primary key. No duplicates. |
| `updates[].start_time` | string | yes | `HH:MM`, 5-minute increments. |
| `updates[].end_time` | string | yes | `HH:MM`, 5-minute increments, `> start_time`. |
| `updates[].sort_order` | integer | yes | `0 ≤ n ≤ 10000`. |

**Success — `200 OK`**

```json
{
  "blocks": [
    { "id": 42, "title": "...", "start_time": "10:00", "end_time": "11:00", "category": "work", "is_completed": false, "sort_order": 0 }
  ]
}
```

Returns the full block list for the schedule, ordered by `start_time`, `sort_order`.

**Errors**

| Status | `errors` key | Meaning |
|--------|--------------|---------|
| `400` | `updates` | Not a list, empty, duplicate IDs, cross-schedule blocks, or more than 100 entries. |
| `400` | `start_time` / `end_time` | Invalid format, non-5-minute, or `start >= end`. |
| `400` | `sort_order` | Not an integer or out of bounds. |
| `400` | `time` | Reorder would cause overlapping blocks (checked against full schedule). |
| `403` | `detail` | CSRF token missing/invalid. |
| `404` | `detail` | One or more block IDs not found, **or** they belong to another user. Cross-user access deliberately returns 404 rather than 403 to avoid leaking block-ID existence. |
| `413` | `body` | Request body exceeds 100 KB (checked before JSON parsing). |

All-or-nothing: if any update is invalid, no blocks are changed.

---

### `POST /api/schedules/{date}/blocks/restore/`

Atomically replace all blocks on a schedule with a provided snapshot. Used by the undo system to restore previous state. Incoming `id` fields are ignored — new rows are created with fresh IDs.

**Limits**

- The raw request body is capped at **100 KB**. Larger bodies are rejected with `413 {"errors": {"body": "Request body too large."}}` *before* JSON parsing.

**Path params**

| Name | Type | Notes |
|------|------|-------|
| `date` | string | `YYYY-MM-DD`. If no schedule exists for this date, one is created. |

**Request body**

```json
{
  "blocks": [
    {
      "title": "Standup",
      "start_time": "09:00",
      "end_time": "09:15",
      "category": "work",
      "is_completed": false,
      "sort_order": 0
    }
  ]
}
```

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `blocks` | array | yes | May be empty (deletes all blocks). |
| `blocks[].title` | string | yes | 1–255 chars. |
| `blocks[].start_time` | string | yes | `HH:MM`, 5-minute increments. |
| `blocks[].end_time` | string | yes | `HH:MM`, 5-minute increments, `> start_time`. |
| `blocks[].category` | string | no | Default `other`. |
| `blocks[].is_completed` | boolean | no | Default `false`. |
| `blocks[].sort_order` | integer | no | Default `0`, `0 ≤ n ≤ 10000`. |

**Success — `200 OK`** — same shape as the reorder response (`{"blocks": [...]}`). Block IDs are new.

**Errors**

| Status | `errors` key | Meaning |
|--------|--------------|---------|
| `400` | `date` | Invalid date format. |
| `400` | `blocks` | Not a list. |
| `400` | `title` | Missing, empty, or > 255 chars. |
| `400` | `start_time` / `end_time` | Invalid format, non-5-minute, or `start >= end`. |
| `400` | `category` | Not one of the allowed choices. |
| `400` | `time` | Restored blocks would overlap. |
| `413` | `body` | Request body exceeds 100 KB (checked before JSON parsing). |

All-or-nothing: if any block is invalid, no changes are applied.

---

### `POST /api/ai/schedules/{date}/command/`

Translate a natural-language command (English or Russian) into schedule mutations via the configured LLM, apply them atomically, and return the updated block list. Every call is logged to `AIInteraction`, success or failure — PRD §6.5.

Requires `LLM_API_KEY` to be set. When unset, every call returns `503` so the frontend can show a degraded-mode indicator; manual editing is unaffected.

**Path params**

| Name | Type | Notes |
|------|------|-------|
| `date` | string | `YYYY-MM-DD`. Schedule is created if missing. |

**Request body**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `command` | string | yes | Up to `LLM_MAX_COMMAND_CHARS` (default 500) after trim. |

**Success — `200 OK`**

```json
{
  "blocks": [
    { "id": 42, "title": "Standup", "start_time": "10:00", "end_time": "10:15", "category": "work", "is_completed": false, "sort_order": 0 }
  ],
  "explanation": "Added standup at 10:00 for 15 minutes."
}
```

`blocks` is the full schedule after the AI's actions were applied. `explanation` is a short human-readable summary produced by the model (same language as the user's command).

**Errors**

| Status | `errors` key | Meaning |
|--------|--------------|---------|
| `400` | `command` / `date` / `body` | Request shape / command type invalid. |
| `400` | `action_index` + `detail` | AI action failed validation (overlap, bad time, unknown block ID). All prior actions in the batch are rolled back. |
| `403` | `detail` | CSRF token missing/invalid. |
| `413` | `body` | Request body exceeds 100 KB. |
| `429` | `detail` | Per-user rate limit (`LLM_RATE_LIMIT_PER_HOUR`, default 100/hr) exceeded. No `AIInteraction` row is written for rejected calls. |
| `502` | `detail` | LLM provider returned an error, or response failed JSON / schema validation. |
| `503` | `detail` | `LLM_API_KEY` is not configured. |
| `504` | `detail` | LLM provider timed out (>`LLM_REQUEST_TIMEOUT` seconds). |

Atomicity: mid-batch validation failure rolls back all DB mutations. The `AIInteraction` row for the request is written *before* mutations are applied, so failed requests still leave a log entry with `actions_json` reflecting the AI's intent.

A successful command flips `Schedule.status` from `draft` to `active` **only when** at least one action was applied. A 200 with `actions: []` (LLM ambiguity / out-of-window guard) leaves the status untouched, mirroring the no-undo-registration contract.

---

### `POST /api/ai/schedules/{date}/generate-draft/`

Generate a fresh draft schedule for an empty day from the user's
weekday/weekend template, the last `LLM_HISTORY_DAYS` (default 7) days of
history (excluding `draft`-status schedules), and active rules. The LLM
fills the day with `add` actions only — no `task_id`s exist on an empty
schedule. The draft does **not** flip `Schedule.status`; the badge stays
`draft` until the user makes a real edit.

**Path params**

| Name | Type | Notes |
|------|------|-------|
| `date` | string | `YYYY-MM-DD`. Invalid format → `400`. |

**Request body** — none.

**Success — `200 OK`**

```json
{
  "blocks": [
    {"id": 12, "title": "Deep work", "start_time": "09:00", "end_time": "12:00", "category": "work", "is_completed": false, "sort_order": 0}
  ],
  "explanation": "Generated draft from weekday template; gym shifted from 17:30 to 18:00 based on last week's pattern."
}
```

**Errors**

| Status | `errors` key | Meaning |
|--------|--------------|---------|
| `400` | `date` | Path date is not `YYYY-MM-DD`. |
| `403` | `detail` | CSRF token missing/invalid. |
| `409` | `detail` | Schedule already has blocks; delete them before regenerating. |
| `413` | `body` | Request body exceeds 100 KB. |
| `422` | `detail` | No template configured for this day's slot type. |
| `429` | `detail` | Draft rate limit (`LLM_DRAFT_RATE_LIMIT_PER_HOUR`, default 10/hr) exceeded. Counter is independent from the command-bar counter. |
| `502` | `detail` | LLM provider returned an error, or response failed JSON / schema validation. |
| `503` | `detail` | `LLM_API_KEY` is not configured. |
| `504` | `detail` | LLM provider timed out. |

The `409` and `422` checks both run before any LLM call, so neither burns the rate-limit budget. The `409` is re-checked under `select_for_update()` after the LLM call to close the race window with concurrent `create_block` requests.

Audit row: every call (success or failure) writes one `AIInteraction` row with `kind="draft"`, `user_command="[DRAFT]"`, and `actions_json` reflecting the LLM's parsed actions.

---

## Templates and Rules

Per-user CRUD for the templates and rules that shape draft generation.

### `GET /api/templates/`

Returns the current user's templates.

```json
{
  "templates": [
    {"id": 1, "name": "Default Weekday", "type": "weekday", "blocks": [...]},
    {"id": 2, "name": "Default Weekend", "type": "weekend", "blocks": [...]}
  ]
}
```

### `POST /api/templates/` / `PUT /api/templates/{pk}/`

Create or replace a template. The unique `(user, type)` constraint means each user has at most one weekday and one weekend template — a duplicate `type` returns `409` with `errors.type` describing the conflict.

**Body**

| Field | Type | Notes |
|-------|------|-------|
| `name` | string | 1–100 chars. |
| `type` | string | `"weekday"` or `"weekend"`. |
| `blocks` | array | Up to 50 entries. Each entry: `{title, start_time, end_time, category}`, validated against the same HH:MM regex, 5-minute granularity, day-window, no-overlap rules used by `_apply_add`. |

**Errors**: `400` for shape/validation issues; `404` for cross-user PK access on PUT (id enumeration guard); `409` on unique-constraint violation.

### `DELETE /api/templates/{pk}/`

Deletes the template. Returns `404` for cross-user PK access.

### `GET /api/rules/`

Returns the current user's rules ordered by `-priority`.

```json
{"rules": [{"id": 1, "text": "No meetings before 9", "is_active": true, "priority": 10}]}
```

### `POST /api/rules/`

**Body**

| Field | Type | Notes |
|-------|------|-------|
| `text` | string | 1–500 chars. |
| `is_active` | boolean | Optional. Default `true`. |
| `priority` | integer | Optional. Default `0`. |

A user is capped at 100 rules; over-cap requests return `400`.

### `PATCH /api/rules/{pk}/`

Partial update of `text`, `is_active`, `priority`. Cross-user PK → `404`.

### `DELETE /api/rules/{pk}/`

Deletes the rule. Cross-user PK → `404`.

---

## Example: create → update → delete (dev)

```bash
# 1. Log in (sets sessionid + XSRF-TOKEN cookies)
curl -c cookies.txt -b cookies.txt \
  -H "Content-Type: application/json" \
  -d '{"username":"me","password":"pw"}' \
  http://localhost:8006/accounts/login/

CSRF=$(grep XSRF-TOKEN cookies.txt | awk '{print $NF}')

# 2. Create a block
curl -c cookies.txt -b cookies.txt \
  -H "Content-Type: application/json" \
  -H "X-XSRF-TOKEN: $CSRF" \
  -d '{"title":"Standup","start_time":"09:00","end_time":"09:15","category":"work"}' \
  http://localhost:8006/api/schedules/2026-04-09/blocks/

# 3. Mark it complete
curl -c cookies.txt -b cookies.txt -X PATCH \
  -H "Content-Type: application/json" \
  -H "X-XSRF-TOKEN: $CSRF" \
  -d '{"is_completed": true}' \
  http://localhost:8006/api/blocks/1/

# 4. Delete it
curl -c cookies.txt -b cookies.txt -X DELETE \
  -H "X-XSRF-TOKEN: $CSRF" \
  http://localhost:8006/api/blocks/1/
```
