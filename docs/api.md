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

The overlap check runs inside `transaction.atomic()` but is **not** race-safe against concurrent requests on SQLite (no row locks available). Phase 7 / multi-user deployments should move to Postgres and add a DB-level exclusion constraint.

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
| `403` | `detail` | Block belongs to another user, or CSRF token missing/invalid. |
| `404` | `detail` | No block with that `pk`. |

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
| `403` | `detail` | Block belongs to another user, or CSRF token missing/invalid. |
| `404` | `detail` | No block with that `pk`. |

---

### `POST /api/blocks/reorder/`

Batch-update the times and sort order of multiple blocks after a drag-and-drop operation. All blocks must belong to the same schedule owned by the authenticated user. The final schedule state (updated + unchanged blocks) is validated for overlaps.

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
| `400` | `updates` | Not a list, empty, duplicate IDs, or cross-schedule blocks. |
| `400` | `start_time` / `end_time` | Invalid format, non-5-minute, or `start >= end`. |
| `400` | `sort_order` | Not an integer or out of bounds. |
| `400` | `time` | Reorder would cause overlapping blocks (checked against full schedule). |
| `403` | `detail` | Blocks belong to another user, or CSRF token missing/invalid. |
| `404` | `detail` | One or more block IDs not found. |

All-or-nothing: if any update is invalid, no blocks are changed.

---

### `POST /api/schedules/{date}/blocks/restore/`

Atomically replace all blocks on a schedule with a provided snapshot. Used by the undo system to restore previous state. Incoming `id` fields are ignored — new rows are created with fresh IDs.

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

All-or-nothing: if any block is invalid, no changes are applied.

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
