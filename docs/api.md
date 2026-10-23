# Day Forge API

Current wire contracts after R00–R12. Architecture and implementation owners: [ARCHITECTURE.md](ARCHITECTURE.md). Feature plans describe historical implementations; they do not override this reference or contract tests.

## Conventions

- Base URL: Django (`http://localhost:8006` in development). Vite serves assets and proxies application routes on `:5173`.
- Authentication: Django session cookie. Unauthenticated protected views redirect to `/accounts/login/`. Unsafe `/api/` requests carrying a mismatched `X-Schedule-User` account ID return `401` with `code: session_invalid` before the view. This header supplements session authentication.
- Frontend release: production JSON API calls send `X-Frontend-Version` from the running build (also exposed in the initial HTML meta). A mismatch returns HTTP 409 with `code: frontend_outdated` before the view. Unsafe `/api/` calls without the header are also refused; headerless reads remain compatible. Reload the page and let the user repeat the action; never replay a write automatically. Development/HMR uses `development` without this gate. This supplements authentication, CSRF and schedule revision checks.
- CSRF: obtain `XSRF-TOKEN` from the login or schedule GET; send `X-XSRF-TOKEN` on unsafe requests. Missing or invalid CSRF returns 403.
- JSON request bodies must be objects. Shared parsing rejects malformed roots with 400 and bodies over 100 KB with 413 where that parser applies. Error envelopes use `errors`, optionally a stable `code` and metadata. Middleware errors may use Django's HTML response.
- Dates use `YYYY-MM-DD`, block times use `HH:MM`, intervals are `[start, end)`. The saved user IANA `time_zone` defines civil time, viewed-day scope, AI placement and integration queries. Browser and project default zones do not override it.
- Manual changed times require five-minute increments. Imported events permit arbitrary minutes; unchanged imported times can survive metadata edits and reorder. Restore accepts those previously valid intervals. Supported writes use domain validation rather than per-row `full_clean()`.

## Schedule mutation contract

Block create, from-event create, PATCH, DELETE, reorder, restore, AI chat and draft require JSON `expected_revision`, a plain integer from 0 through `2**63 - 1`. Use the revision of the canonical schedule currently shown. An absent day starts at revision 0. The active mark-reviewed path has the same requirement; its reviewed retry exception is documented under Analytics. Category, rule, template, preference and settings mutations have their own contracts, not this field.

Missing, invalid or obsolete revision returns 409 with `code: schedule_changed`. Temporary exhausted SQLite write contention can return the same conflict. These failures do not apply a partial write. The client reconciles the canonical schedule before another mutation; it does not blindly replay the request.

Successful mutation responses include a canonical snapshot captured inside the transaction:

```json
{
  "schedule": {"id": 12, "date": "2026-10-11", "status": "active", "revision": 8},
  "blocks": [{"id": 42, "title": "Standup", "start_time": "09:00", "end_time": "09:15", "category": "work", "is_completed": false, "sort_order": 0}],
  "revision": 8
}
```

Create/PATCH retain the changed block fields at the top level; DELETE retains `ok: true`. Reorder/restore return the snapshot directly. AI replies add their documented action/ask/outcome fields. Do not replace state from an obsolete response or from another account/date. A successful no-op retains revision; accepted block or status changes advance it once. Forward edits promote draft/reviewed to active. Restore preserves status, and draft generation stays draft.

Each serialized block also carries an opaque signed `restore_proof`. Keep it with the block snapshot for Undo; do not construct or modify it. The server owns stored origin, which is not a writable API field. Calendar-import and legacy/unverified block titles are masked in AI schedule context and draft history; scheduling times, category and completion remain available. Matching protected titles are masked in the provider-bound chat transcript. User-written rules, templates and copied text remain separate AI inputs; see `/privacy/`.

All supported day writes lock User → Schedule → TimeBlock and validate the complete candidate state. On SQLite the executor reserves the writer before reading and retries the whole transaction on bounded busy errors. On PostgreSQL the same ordering uses row locks. SQLite still serializes writes across users and can return contention conflicts. This contract protects supported application writers; direct ORM edits bypass it. See [R04](REFACTORING_R04.md), [R05](REFACTORING_R05.md), and [R07](REFACTORING_R07.md).

### Schedule page reads

GET `/schedule/{date}/` captures an existing fully bootstrapped day, ordered blocks and page policies in one read transaction without reserving the SQLite writer. An absent day or missing first-use rows use the shared User writer lock; the creation flag and response snapshot are captured before commit. `auto_draft_pending` can be true only for the request that created Schedule, with a matching template and configured AI key. Restoring missing policies for an existing day does not emit that signal.

Exhausted first-use contention or SQLite locked/busy errors inside this view return 503 with `Retry-After: 1` and a plain-text retry message. They do not return the mutation `409 schedule_changed` envelope. This response contract does not cover authentication middleware failures before the view.

The frontend app-root coordinator retains pending writes and confirmed revision floors across page remounts. A returning account/date waits for settlement and accepts a sufficiently current snapshot or performs a scoped GET reload. Failed or older reconciliation keeps writes blocked. Navigation does not replay POST, and a departed day's settlement does not reload another day. See [A02/A03](AUDIT_FIXES_A02_A03.md).

## Category catalog

`GET /api/user/categories/` returns `{"categories": [...]}` in catalog order and bootstraps Work (`work`, default), Personal (`personal`), Health (`health`) and Other (`other`, sink) on first access. Slugs are immutable and user scoped. Labels are trimmed and case-insensitively unique. Palette IDs: `blue`, `violet`, `emerald`, `gray`, `amber`, `rose`, `cyan`, `indigo`. At most eight categories.

| Method and path | Request | Result |
|---|---|---|
| POST `/api/user/categories/` | `label`, `color_id` | Create category, 201 |
| PATCH `/api/user/categories/{id}/` | `label`, `color_id`, or `is_new_block_default: true` | Update mutable fields or promote default, 200 |
| POST `/api/user/categories/swap/` | Distinct plain-integer `a`, `b` | Swap order, 200 |
| DELETE `/api/user/categories/{id}/` | No mutation revision required | Refuse sink deletion; remap deleted slug to sink in blocks, templates, travel rules and review maps, 200 |

Malformed fields return 400; unknown/foreign IDs return 404. Four write operations share `CATEGORY_MUTATION_RATE_LIMIT_PER_HOUR` (default 60). Exceeded budget returns 429, `Retry-After: 3600`, `errors.detail: Rate limit exceeded. Try again later.` GET is uncounted. Category maintenance locks the user and advances affected day revisions when block state changes.

Category deletion advances each affected schedule revision once. If a reviewed snapshot was current before the remap, its tag advances to that revision in the same transaction; frozen counts, notes and timestamps stay unchanged. Category-minute maps move to the sink. Previously stale snapshots remain stale. A repeated delete returns 404 without another revision change.

## Block endpoints

### `POST /api/schedules/{date}/blocks/`

Create a user-owned block, creating the day only on an accepted write. Body: `expected_revision`, nonempty trimmed `title` (1–255 characters), `start_time`, `end_time`, optional category slug. An omitted category uses the catalog's new-block default. Manual times require the five-minute grid and start < end. A partially outside interval is clamped to the day window; a wholly outside interval returns 422 with `skipped: true`, `code: outside_window` and `window`. Overlap returns 400 with `errors.time`.

Success: 201, changed block fields plus the canonical mutation snapshot. Invalid body/date/fields/category/interval returns 400; oversized body returns 413; revision/contention returns 409.

### `POST /api/schedules/{date}/blocks/from-event/`

Same revision, title, interval, ownership and response contract as manual create, with arbitrary minute boundaries and the sink as omitted category. The frontend converts the event to the saved user timezone and applies travel overrides before submitting the local interval. The backend validates the resulting interval and clamps it to the saved day window. Free-slot re-adds are permitted; this endpoint has no event deduplication key.

### `PATCH /api/blocks/{id}/`

Body: `expected_revision` plus any of `title`, `start_time`, `end_time`, `category`, `is_completed`, `sort_order`. Completion is a boolean; sort order is a plain integer 0–10000. Only changed time boundaries enforce the grid and window. Metadata-only edits tolerate unchanged imported times and blocks outside a subsequently narrowed window. Candidate overlap or invalid interval returns 400. Unknown or foreign ID returns 404.

Success: 200, changed block fields and mutation snapshot. Identical values do not advance revision or change draft/reviewed status.

### `DELETE /api/blocks/{id}/`

Send JSON `{"expected_revision": 8}` with CSRF. The block must belong to the authenticated user; unknown/foreign ID returns 404. Success: 200, `ok: true` plus mutation snapshot. An empty body has no valid revision and returns 409.

### `POST /api/blocks/reorder/`

Body: `expected_revision` and a nonempty `updates` list, at most 100 items. Each item has distinct plain-integer `id`, `start_time`, `end_time`, and `sort_order` (0–10000). All IDs must belong to one owned schedule. Changed boundaries enforce the grid and day window; unchanged imported boundaries remain valid.

The planner validates the entire final schedule, so an atomic swap can succeed although an intermediate sequential update would overlap. Success: 200 mutation snapshot. Bad shape, duplicate IDs, mixed days, invalid interval/order or final overlap returns 400; missing/foreign IDs return 404. Failure changes no rows.

### `POST /api/schedules/{date}/blocks/restore/`

Body: `expected_revision`, `blocks` array (may be empty). Every block supplies `title`, `start_time`, `end_time`; optional `category`, `is_completed` (default false), `sort_order` (default 0). Send the original `id` and `restore_proof` from the accepted snapshot to preserve server-owned origin. Proofs are bound to schedule, original block ID, title and origin; IDs must be positive, plain integers and distinct when proofs are supplied. Invalid proofs return 400 without writes. Missing proofs are accepted conservatively with `unknown` origin; client-supplied origin flags cannot override it. IDs without proofs do not restore identity.

A changed restore replaces rows with fresh IDs and proofs; an authenticated identical restore retains current IDs and revision. Provenance is part of snapshot equality, so a restore without proof can change origin even when visible fields match. Unknown or deleted category slugs map to the current sink.

Restore validates the complete replacement for shape, intervals and overlap. It accepts arbitrary minutes and preserved intervals outside the current day window. It preserves current schedule status, ignores historical status/revision supplied by the client, and advances revision once if the persisted block state changes. Success: 200 mutation snapshot. Invalid shape/interval/overlap returns 400; oversized body returns 413; stale/missing revision returns 409. Rejection leaves current data unchanged.

Undo is a local snapshot stack bound to date, account and revision. It is not a durable server journal and cannot replace changes accepted since its snapshot. See [R05](REFACTORING_R05.md).

---

### `POST /api/ai/schedules/{date}/chat/`

Multi-turn natural-language assistant for the command bar (feature 0007). Each request carries the full client-side transcript; the server validates it, calls the LLM for the latest user turn, and either applies schedule mutations, asks a clarifying question, or returns chit-chat with no mutations. Active server-side Rules are injected into the trusted schedule-context message in the User-locked `ai.views._load_ai_context_sync` capture (same as draft). Provider attempts are logged to `AIInteraction` on a best-effort basis; rejected preconditions need not create a row, and audit success is not a commit receipt.

**Privacy:** fresh commands send the client transcript as untrusted context. Bound continuations send the latest user turn and a server-built pending summary instead of the prior transcript. Imported titles are masked in both paths, including the pending summary. Completed identical request replays return the saved result without a provider call. An unresolved HTTP request keeps its original body in this tab's account/date-scoped session storage across reloads until recovery; Logout/Login or account changes clear those client copies. Resolve an uncertain request before clearing the thread or starting a new one.

A latest turn with no explicit instruction (no command verb, not a question, not a short reply or greeting, not an answer to a pending clarifying ask, not a retry after an error bubble) is interpreted as an add: the server prefixes the copy sent to the LLM with `add ` (or `добавь ` for Cyrillic text) before the call, while the stored transcript and audit log keep the original text (feature 0083 Addendum D — see `backend/ai/implicit_add.py`).

Provider turns require `LLM_API_KEY`; when unset they return `503`. Explicit pending-intent cancellation and completed request replays require no provider.

**Path params**

| Name | Type | Notes |
|------|------|-------|
| `date` | string | `YYYY-MM-DD`. Invalid format → `400`. Schedule is created if missing (only after message validation passes). |

**Request body**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `request_id` | UUID string | yes | Canonical lowercase UUID generated once per new user turn. Transport retries reuse this ID and the complete original body. Missing/invalid returns 400 without admission. |
| `expected_revision` | integer | yes | Revision from the canonical day snapshot; missing/invalid returns 409. A completed identical replay is resolved before checking whether this revision is stale. A fresh stale request returns 409 before the provider call. |
| `messages` | array | yes | Non-empty list of `{role, content}` turns. Roles strictly alternate `user` / `assistant`, starting with `user`. Last turn must be `user`. `1 ≤ len ≤ LLM_CHAT_MAX_TURNS` (default 40). Each `content` contains non-whitespace text and is 1–`LLM_MAX_COMMAND_CHARS` (default 500) chars. Sum of all `content` lengths ≤ `LLM_CHAT_MAX_TOTAL_CHARS` (default 4000). |
| `pending_intent_id` | UUID string | for continuation/cancel | Canonical opaque server UUID, bound to authenticated owner and this Schedule/date. Must be paired with version. |
| `pending_intent_version` | integer | with intent ID | Positive plain integer for the exact pending version being answered. Ask-only turns also advance it. |
| `intent_action` | string | no | `new`, `continue`, `cancel`. Defaults to `continue` with an ID, otherwise `new`. Continue/cancel require ID/version. Explicit cancel makes no provider call. |
| `messages[].is_ask` | boolean | no | **Assistant turns only** (feature 0083). The client marks an assistant turn `is_ask: true` when its `ask` was non-null on the wire — a correctness aid for the replay guard, not a security control. A client that forges this flag only disables the guard for its own turn, no more than it could already do by typing the replayed title directly. Non-boolean, or present on a `user` turn, → `400`. |
| `messages[].is_error` | boolean | no | **Assistant turns only** (feature 0083). Definite rejected turns use synthetic `is_error: true` bubbles. Unknown network/proxy outcomes retain the original request instead; they must not become a new `try again` turn. The replay guard still handles semantic replays across distinct request IDs. Same non-boolean / assistant-only validation as `is_ask`. |

Assistant asks may also include `applied_add_block_ids`, a list of positive plain-integer block IDs (maximum 100). It identifies adds accepted in that partial turn for replay handling; it is not a server-owned authorization claim.

Malformed `messages` (including non-object JSON roots) return `400` **before** `Schedule.get_or_create` and **before** the rate-limit counter is consumed. Prompt time and untimed-add placement use the user's persisted schedule `time_zone`; legacy `client_tz` fields are ignored.

**Durable request contract**

The identity namespace is authenticated owner + civil date + chat endpoint. The hash covers the complete parsed JSON object, including messages, markers, expected revision and additional fields; object key order is insignificant. An identical completed request returns its stored HTTP status and JSON bytes without another provider call, rate-limit token or schedule write. A valid different body for the same identity returns `409 request_id_conflict`.

Concurrent identical requests get `409 request_in_progress` with `Retry-After: 2` while the owner holds its lease. The default lease lasts `max(120, LLM_REQUEST_TIMEOUT * 4 + 30)` seconds. A later retry may take over an expired lease with a new token; the previous worker cannot apply after takeover. Provider calls run outside database write locks. The terminal result and any schedule mutation commit together under the User lock. Provider errors are terminal for that ID; an intentional retry after a known error needs a new ID. Temporary identity-store contention returns `503 request_unavailable`, retaining the same client ID/body.

Every admitted terminal JSON response adds `request_id` and `request_completed: true`, including error and ask/no-op results. Pre-admission validation, identity conflicts, in-progress and unavailable responses do not include that terminal marker. Responses may describe an older snapshot on replay; clients must reconcile rather than overwrite a newer canonical revision. Frontend performs one immediate retry for an unknown transport result, then offers **Recover previous AI request**. Recovery shows the original latest message and may finish an uncompleted request. It blocks new AI turns and thread clearing until the outcome is known. Manual schedule edits remain available after ordinary reconciliation.

`ChatRequest` rows, including their response snapshots, remain until the owning account is deleted. They are not tied to the lifetime of a Schedule row and must not be pruned/reaccepted under the same UUID scope. No automatic cleanup is provided. A future retention change must preserve uniqueness with durable tombstones. Draft requests are outside this protocol.

**Server-owned pending intent**

A successful chat result adds `pending_intent: null` or `{id, version, expires_at, ask}`. The private executable scope stays on the server. One open record per owner/Schedule stores unresolved actions, known/missing fields, permitted target IDs, real accepted block IDs, revision and the post-write policy fingerprint. Its 15-minute expiry does not slide. Completion/cancellation closes the row; Schedule/account deletion cascades it. Rows are otherwise retained, including their private source message and scope.

Continuation checks owner, Schedule/date, state, expiry, version, revision and context before the provider and fences them again when applying. Stale preconditions return `409 pending_intent_stale`; a schedule/policy change during the network call can return `409 schedule_changed`. Scope expansion returns `409 pending_intent_scope` without committing the plan. Each old permission can cover only one action or refined question. Accepted siblings cannot be replayed, and unanswered siblings remain pending. Explicit cancel still checks identity/version/expiry, but can close an intent after a policy change using the current revision. These terminal errors are also durable for their request ID.

The provider returns `intent_decision` (`new`, `continue`, `cancel`, `read`) and structured `pending_actions` for questions. Continue is mandatory for applying a saved scope. Cancel/read discard mutations; free-text classification still depends on the model. A new command detected during continuation is reinterpreted with only the latest turn and no pending summary. Old-format questions have no executable scope and require cancelling/clearing before a restated command. Clear/date/account/session boundaries drop the client reference; uncertain transport recovery retains the frozen ID/version/body. See [the contract](AI_PENDING_INTENT.md) and [verification](AI_PENDING_INTENT_VERIFICATION.md).

**Success — apply turn — `200 OK`**

Returned when the model parsed one or more mutations and at least one field was
applied. Application is **partial**, not all-or-nothing: only structurally
malformed actions abort the whole turn (see Errors). Policy failures
(window / grid / interval / overlap) skip just the offending block's time work
while independent metadata on the same or other blocks still persists; each
per-action result is reported via `outcomes`.

```json
{
  "blocks": [
    { "id": 42, "title": "Standup", "start_time": "10:00", "end_time": "10:15", "category": "work", "is_completed": false, "sort_order": 0 }
  ],
  "explanation": "Added standup at 10:00 for 15 minutes.",
  "ask": null,
  "applied": true,
  "partial": false,
  "outcomes": [
    {
      "action_index": 0,
      "task_id": 42,
      "status": "applied",
      "applied_fields": ["start_time", "end_time"],
      "skipped_fields": [],
      "reason_code": null,
      "conflicting_task_ids": [],
      "attempted_direction": null,
      "suggestion": null
    }
  ]
}
```

`blocks` is the full schedule after apply.

**Untimed (auto-placed) adds, chat only (features 0067, 0086).** A chat `add`
may omit **both** `start_time` and `end_time`; the backend then places the block
on the 5-minute grid with a **25-minute default duration**. The forward floor
is unchanged: current local time rounded up to the grid for today, or the
day-window start for another date. An optional `duration_minutes` (a positive
multiple of 5) overrides the default length; supplying only one time field is
rejected.

The backend searches forward with a preferred **10-minute gap** on both sides
of neighbouring blocks. If that result fits in the initial window,
it keeps the result unchanged. Otherwise it retries only that initial window
with symmetric **5-minute, then zero-minute gaps**. Each retry checks one
right-aligned placement: the latest grid-aligned end that is no later than the
next block's start minus the trial gap (so with a zero gap the block may touch
the next block), minus the full duration. Placement never starts before the
forward floor. An off-grid neighbour is respected by rounding the candidate end down.
If no block follows, the window ends at the day-window end, with no gap required
from that boundary. A block covering or starting at the floor makes the initial
window empty. Each accepted add contributes its raw interval to the next add's
occupancy.

For example, at **10:03**, with `Standup` at **10:30–10:55**, an untimed
`Write report` uses **10:05–10:30**, touching `Standup` with zero gap. If no
retry fits the initial window, the original full-gap forward-search result is
used; later windows retain the full 10-minute gap. If neither the initial-window
retries nor the full-gap fallback fit inside the day window, the create is
**skipped** with `reason_code="no_slot"` (see the outcomes table), and the response
carries a server-owned `ask` suggesting a shorter duration or a specific free
time. Explicit adds (both times supplied) are unchanged and are never
auto-relocated. **The `generate-draft` endpoint is unaffected: draft `add`s still
require explicit HH:MM start/end for every block and are never auto-placed.**

**Duration resize — chat only (feature 0068).** A `resize` action must use
exactly one mode: boundary mode (`start_time` and/or `end_time`), absolute
duration mode (`duration_minutes`, a positive multiple of 5), or relative
duration mode (`duration_delta_minutes`, a non-zero signed multiple of 5).
Duration modes omit both time fields and preserve the block's effective start.
`duration_minutes` means the target total duration; `duration_delta_minutes`
extends (positive) or shortens (negative) the current effective duration. The
backend derives the end in integer-minute space, validates the window/grid and
checks conflicts. A derived end beyond the working-day end (or midnight) is
**rejected, never clamped**; no neighbouring block is shifted or shortened.

New envelope fields (feature 0054):

| Field | Type | Notes |
|-------|------|-------|
| `partial` | boolean | `true` when at least one action partially applied — some fields applied, some skipped. `false` when every action fully applied (or fully skipped). |
| `outcomes` | array | One per-action outcome object. See below. |

Each `outcomes[]` entry:

| Key | Type | Notes |
|-----|------|-------|
| `action_index` | int | Zero-based index into the post-normalisation `parsed_actions` (the list stored in `actions_json`) — see the `unresolved_categories` note below for how a dropped `update` makes this list differ from the model's own `actions`. |
| `task_id` | int \| null | DB primary key of the affected block, or `null` for a create that never persisted. |
| `status` | string | `"applied"` (all requested fields landed), `"partial"` (some fields landed, some skipped), or `"skipped"` (nothing landed for this action). |
| `applied_fields` | array | Field names that persisted (e.g. `title`, `category`, `start_time`, `end_time`). For `remove` actions this is always `[]` — the action's effect is the deletion of the block itself, not a field change. |
| `skipped_fields` | array | Field names rejected by a policy check. For `remove` actions this is always `[]` (see `applied_fields`). |
| `reason_code` | string \| null | Why the skip happened (e.g. `out_of_window`, `unresolved_conflict`, `no_slot`, `replay_guard`). `null` when nothing was skipped. `interval` also covers a computed duration below the 5-minute floor; duration ends beyond the day window are `out_of_window` and are rejected rather than truncated. `no_slot` (features 0067, 0086) means an **untimed** chat `add` found no fit after the initial-window gap retries and the full-gap forward fallback in the day window; `task_id` is `null` and `suggestion`/`attempted_direction`/`conflicting_task_ids` are empty. For a `no_slot` skip, `skipped_fields` lists the fields that would have been written had a slot been found (`["title", "category", "start_time", "end_time"]`). `replay_guard` (feature 0083) means the whole turn's actions were skipped because the server-side replay guard flagged an `add` as replayed from an earlier turn — see the replay-guard success variant above. |
| `conflicting_task_ids` | array | Block ids that the skipped time work collided with. |
| `attempted_direction` | string \| null | `"earlier"` / `"later"` when a directional free-slot search was attempted and found nothing, else `null`. |
| `suggestion` | object \| null | `null`, or `{ "start_time", "end_time", "direction" }` (a concrete free slot to offer), or `{ "direction_required": true }` (the model must ask the user which direction to search). |

`applied`, `partial`, and `ask` can all be non-default simultaneously: a turn can
apply some work (`applied: true`), report that a block only partially landed
(`partial: true`), **and** carry a server-owned follow-up question about the
skipped time work (`ask` non-null) — the partial-apply case.

An explicit add rejected as `out_of_window` asks for a time within the user's
day window before the generic skipped-create fallback. Concrete suggestions,
direction/conflict questions, and `no_slot` advice retain higher priority.
If a duration resize conflicts and is followed by a title/category update on the
same block, metadata may apply while `end_time` remains skipped. The response
retains the conflict and follow-up question; it must not report timing as applied
just because the later action changed only metadata.

**Success — clarifying question — `200 OK`**

```json
{
  "blocks": null,
  "explanation": "What time should gym start?",
  "ask": "What time?",
  "applied": false,
  "partial": false,
  "outcomes": []
}
```

No mutations; `Schedule.status` is unchanged. Append the assistant's `explanation`/`ask` to the client transcript and send the user's answer on the next turn.

**Success — replay guard — `200 OK`** (feature 0083, issue #219)

The guard's `ask` and `explanation` are server-owned English strings regardless of the user's language (unlike model-generated asks, which follow the user's language); clients that render `ask` verbatim should expect English.

Returned when the server-side replay guard determines that an `add` action
in the model's output was replayed from an earlier, already-handled turn
rather than derived from the latest one (e.g. a "same name → add `[N]`" Rule
firing against a stale title). **All-or-nothing:** every parsed action from
the turn is skipped, not just the offending add(s).

```json
{
  "blocks": null,
  "explanation": "Nothing was changed.",
  "ask": "I did not change the schedule: \"Momentum[2]\" is not something you asked for in your last message. What would you like to add?",
  "applied": false,
  "partial": false,
  "outcomes": [
    {
      "action_index": 0,
      "task_id": null,
      "status": "skipped",
      "applied_fields": [],
      "skipped_fields": ["title", "category", "start_time", "end_time"],
      "reason_code": "replay_guard",
      "conflicting_task_ids": [],
      "attempted_direction": null,
      "suggestion": null
    }
  ]
}
```

No mutations; `Schedule.status` is unchanged. This ask is server-owned English
(like every `_build_resolution_ask` string), regardless of the user's
language. The client should send `is_ask: true` on this assistant turn on
the next request so a legitimate answer isn't guarded again.

**Success — unresolved category — `200 OK`** (feature 0084, issue #209)

A category value the model emitted (a label, or the user's own wording in
any language, e.g. Russian "рабочая" for "work") could not be resolved to a
slug — see `ai/category_resolution.py`. On an `add`, an unresolvable value
silently falls back to the sink category instead (never surfaced here). On
an `update`, it is dropped instead of quietly recategorising the block, and
the response always carries a server-owned `ask` naming the block and
listing the available category labels: `Which category should "<title>"
use: <Label>, <Label>, …?` — English-only, like every other server-built
ask.

Two shapes, depending on whether anything ELSE in the turn applied:

*Nothing left to apply* — the only action was an `update` whose sole change
was the unresolved category. This is the clarifying-question shape:
`outcomes` is empty (a dropped update has no entry in it) and `explanation`
is the fixed server string, never the model's (which could claim a category
change that never happened):

```json
{
  "blocks": null,
  "explanation": "Nothing was changed.",
  "ask": "Which category should \"Gym\" use: Work, Personal, Health, Other?",
  "applied": false,
  "partial": false,
  "outcomes": []
}
```

*Applied plus ask* — a sibling change (or a different action in the same
turn) applied while the category-only update was dropped. This is
`docs/api.md`'s standard partial-apply shape (`applied: true` alongside a
non-null `ask`); the dropped update contributes no `outcomes` entry, only
the ones for whatever did apply. This is the issue #209 repro exactly: a
time change applies, and the response carries the category ask:

```json
{
  "blocks": [ { "id": 42, "title": "Gym", "start_time": "14:00", "end_time": "15:00", "category": "personal", "is_completed": false, "sort_order": 0 } ],
  "explanation": "Moved to 14:00.",
  "ask": "Which category should \"Gym\" use: Work, Personal, Health, Other?",
  "applied": true,
  "partial": false,
  "outcomes": [
    {
      "action_index": 0,
      "task_id": 42,
      "status": "applied",
      "applied_fields": ["start_time", "end_time"],
      "skipped_fields": [],
      "reason_code": null,
      "conflicting_task_ids": [],
      "attempted_direction": null,
      "suggestion": null
    }
  ]
}
```

If a skipped-time-work resolution ask (see the apply-turn section above) is
also pending in the same turn, that ask wins — the user can answer only one
question per turn.

The audit row carries a parallel `unresolved_categories` array (see the
Audit row note below) so a dropped update is never silently lost even
though it has no `outcomes` entry.

**Success — chit-chat / no-op — `200 OK`**

```json
{
  "blocks": null,
  "explanation": "You're welcome!",
  "ask": null,
  "applied": false,
  "partial": false,
  "outcomes": []
}
```

Empty `parsed_actions` with `ask: null`. No mutations; status unchanged.

Provider chat replies with null ask require a nonblank explanation, including no-op and action replies. A supplied ask must contain non-whitespace text; its explanation may be blank because the client uses ask as assistant content. The selected `ask ?? explanation` must also fit `LLM_MAX_COMMAND_CHARS`, independently of the output field caps. Invalid replies return the fixed parse-error 502 before action processing. Incoming blank or whitespace-only transcript content returns 400 before the provider call. These chat-history rules do not change draft validation.

**Envelope uniformity:** `partial` and `outcomes` are **always present on every `200` response** — the apply, clarifying-question, and chit-chat turns alike. On non-apply turns they default to `false` and `[]` respectively, so a client can read them unconditionally without branching on the response variant. The replay-guard variant above is the one non-apply case where `outcomes` is non-empty — its entries carry `reason_code: "replay_guard"` rather than describing a real per-action policy outcome.

**Errors**

| Status | `errors` key | Meaning |
|--------|--------------|---------|
| `400` | `messages` / `date` / `body` | Transcript shape invalid, path date bad, or body not a JSON object. Also covers a non-boolean `messages[].is_ask` / `is_error`, or either flag present on a `user` turn (feature 0083). |
| `400` | `action_index` + `detail` | `action_index` indexes the post-normalisation `parsed_actions` (`actions_json`), the same space as `outcomes`. An action was **structurally** malformed at apply time (unknown block ID, unparseable/missing required field). Only these abort the whole turn — the entire batch is rolled back. Policy failures (window / grid / interval / overlap) do **not** 400; they skip just that block's time work and are reported via `outcomes` on a `200`. |
| `403` | `detail` | CSRF token missing/invalid. |
| `409` | `detail` | `schedule_changed` — the concurrent-edit fingerprint guard (feature 0030); only when `parsed_actions` is non-empty and the replay guard did not trip. |
| `413` | `body` | Request body exceeds 100 KB. |
| `429` | `detail` | Per-user chat rate limit (`LLM_CHAT_RATE_LIMIT_PER_HOUR`, default 60/hr) exceeded. Counter is independent from the draft bucket. Validation failures do not consume the budget. |
| `502` | `detail` | LLM provider returned an error, or response failed JSON / schema validation. On any JSON / envelope / schema-validation failure (`AIParseError`) `detail` is the fixed generic string `AI_PARSE_ERROR_DETAIL` ("The assistant's reply couldn't be applied. Try rephrasing.") — the real validation message (which can echo model-supplied text, e.g. an unresolved category label or an unknown JSON key) is never sent to the client; it survives only in the audit row's `error_detail` (feature 0084) — its `action[i]` refers to the model's own `actions` index in `raw`, the same index space as `unresolved_categories`' `original_index`, not the post-normalisation `actions_json`. |
| `503` | `detail` | `LLM_API_KEY` is not configured. |
| `504` | `detail` | LLM provider timed out (>`LLM_REQUEST_TIMEOUT` seconds). |

Atomicity: the accepted subset of a turn is applied within a single transaction, so a partial apply is still atomic — either the whole accepted subset lands or (on a **structural** failure) the entire turn rolls back and returns `400`. Policy failures do not roll back the turn; they drop just the offending time work and are reported via `outcomes`. The `AIInteraction` row is written after a successful LLM call and before apply; a structural apply failure leaves `success=False` with `actions_json` reflecting the model's intent.

`actions_json` is the **post-normalisation** `parsed_actions` list: category labels / the user's own wording are already resolved to slugs, and a category-only `update` dropped for an unresolved category is **omitted** from it entirely (feature 0084). The model's verbatim output — including the unresolved value — stays in the audit row's `raw` field. A success row whose turn had any unresolved category also carries `"unresolved_categories": [{"original_index": int, "task_id": int, "dropped": bool}, …]`, inserted before `raw`; `original_index` is the position in the MODEL's own `actions` (a separate index space from `action_index` in `outcomes`/`actions_json`, since a dropped `update` has no entry there). The rejected value itself is never copied into `unresolved_categories` — only `raw` holds it. A failure row instead carries `error_detail` (the `AIParseError` message, capped at 2,000 chars) in the same before-`raw` position, present only for that error class.

A successful apply flips `Schedule.status` from `draft` to `active` **only when** at least one field was applied (including a partial apply). Clarifying-question, chit-chat, fully-skipped, and empty-action turns leave status untouched.

**Concurrent-edit guard:** fingerprint captured before the LLM call, re-checked under lock at apply time. Mismatch → `409 {"errors": {"detail": "schedule_changed"}}`. Unrelated to `generate-draft`'s empty-schedule `409`. Clients must refresh schedule state and retry explicitly; the server never auto-retries.

---

### `POST /api/ai/schedules/{date}/generate-draft/`

Generate a fresh draft schedule for an empty day from the user's
weekday/weekend template, the last `LLM_HISTORY_DAYS` (default 7) days of
history (excluding `draft`-status schedules), and active rules. Active
Rules are injected into the LLM prompt context via the same shared
`_format_rules_section` formatter the draft and chat endpoints use,
so both endpoints can't drift on rule rendering. The LLM fills the
day with `add` actions only — no `task_id`s exist on an empty schedule.
The draft does **not** flip `Schedule.status`; the badge stays `draft`
until the user makes a real edit.

**Path params**

| Name | Type | Notes |
|------|------|-------|
| `date` | string | `YYYY-MM-DD`. Invalid format → `400`. |

**Request body**: JSON object with required `expected_revision`. Draft prompt time uses the user's persisted schedule `time_zone`; any legacy `client_tz` field is ignored.

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
| `400` | `action_index`, `detail` | The returned draft failed schedule validation. For an out-of-window block, detail identifies its title, attempted interval and the configured day window, and explains that the draft was not saved. No blocks are applied and revision/status remain unchanged. |
| `403` | `detail` | CSRF token missing/invalid. |
| `409` | `detail` | Schedule already has blocks; delete them before regenerating. |
| `413` | `body` | Request body exceeds 100 KB. |
| `422` | `detail` | No template configured for this day's slot type. |
| `429` | `detail` | Draft rate limit (`LLM_DRAFT_RATE_LIMIT_PER_HOUR`, default 10/hr) exceeded. Counter is independent from the chat bucket. |
| `502` | `detail` | LLM provider returned an error, or response failed JSON / schema validation. On any JSON / envelope / schema-validation failure (`AIParseError`) `detail` is the fixed generic string `AI_PARSE_ERROR_DETAIL` ("The assistant's reply couldn't be applied. Try rephrasing.") — the real validation message (which can echo model-supplied text) goes only to the server log at `DEBUG` (a `WARNING` line logs that a draft parse failure happened, with no message text), never to the client (feature 0084). |
| `503` | `detail` | `LLM_API_KEY` is not configured. |
| `504` | `detail` | LLM provider timed out. |

The `409` and `422` checks both run before any LLM call, so neither burns the rate-limit budget. Revision, empty-day status and the prompt-context fingerprint are checked again under the shared mutation executor after the provider call. A conflict rejects the returned plan without applying it.

Draft provider attempts are logged on a best-effort basis with `kind="draft"`, `user_command="[DRAFT]"`, and `actions_json` reflecting post-normalisation parsed actions. Category labels are resolved to slugs; an unresolved add category falls back to the sink. The model's raw output stays in `ai_response`. Preconditions such as invalid revision, no template or rate limit can reject a request without an audit row. An audit write can fail independently of mutation commit. Draft accepts only add, so it has no chat-style `unresolved_categories` payload.

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

Returns the current user's rules ordered by `-priority`. After any create or
delete, priorities are contiguous from `0` to `N-1`, with the top rule holding
the highest value.

```json
{"rules": [{"id": 1, "text": "No meetings before 9", "is_active": true, "priority": 0}]}
```

### `POST /api/rules/`

**Body**

| Field | Type | Notes |
|-------|------|-------|
| `text` | string | 1–500 chars. |
| `is_active` | boolean | Optional. Default `true`. |
| `priority` | integer | Optional. When omitted, the new rule is placed at the top (highest priority). Priorities are compacted to `0..N-1` on every create and delete, so the stored and returned value may differ from an explicit priority sent by the client. Out-of-range values are still rejected with `400` before any compaction occurs. |

A user is capped at 100 rules; over-cap requests return `400`.

### `PATCH /api/rules/{pk}/`

Partial update of `text`, `is_active`, `priority`. Cross-user PK → `404`.

### `DELETE /api/rules/{pk}/`

Deletes the rule and compacts surviving priorities to `0..N-1`. Cross-user
PK → `404`.

### `POST /api/rules/swap/`

Atomically swaps the `priority` values of two rules owned by the current user.

```json
{"a": 12, "b": 13}
```

Success → `200 {"rules": [...]}` containing both swapped rows. A missing or
cross-user id returns `404`; non-integer ids (including booleans) or equal ids
return `400` with `errors.body`. The two writes occur in one transaction, so
they both commit or neither does.

---

## User Preferences

Per-user UI preferences (theme and AI quick-input suggestions). Each user has exactly one account-scoped preferences row, created on first authenticated access. Distinct from `/api/templates/` (schedule templates) despite the shared `templates_mgr` app.

All responses from `GET` and `PATCH` set `Cache-Control: private, no-store` — including 400/413 error responses, which is exercised by tests. Success bodies contain per-user state; error bodies contain fixed validation strings and do NOT echo client-supplied values. A misconfigured CDN/proxy must never cache any path regardless, so the helper applies the header uniformly. (The header is NOT attached to 405/302 responses produced by Django's `@require_http_methods` / `@login_required` decorators before the view runs; those bodies are empty or a redirect Location, with no per-user state leak surface.)

### `GET /api/user/preferences/`

Returns the current user's preferences. Creates a default row (theme `"classic"`, unset suggestions) if none exists. Unset or structurally malformed persisted suggestions resolve to the three defaults shown below without rewriting the row; a saved empty array remains empty.

```json
{
  "theme": "classic",
  "chat_suggestions": [
    "Plan my remaining day",
    "Add a focused work block",
    "Make room for a break"
  ]
}
```

`theme` is always one of `classic`, `strategic`, `light_premium`, or `dark_4a`. An invalid persisted value (e.g. retired theme id, fixture typo) is normalized to `classic` on read **without** rewriting the DB row.

### `PATCH /api/user/preferences/`

Partially updates theme and/or AI quick-input suggestions.

**Body**

| Field | Type | Notes |
|-------|------|-------|
| `theme` | string | `classic`, `strategic`, `light_premium`, or `dark_4a`. |
| `chat_suggestions` | array of strings | At most 8 entries. Each entry is trimmed, must remain non-empty, and may contain at most 120 Unicode code points. Order and duplicates are preserved. `[]` intentionally hides all suggestions; `null` is rejected. |

Unknown keys are silently ignored (forward-compatibility — matches the `/api/rules/{pk}/` PATCH pattern). A body containing zero recognized fields returns `400` with `errors.body = "No editable fields supplied."`; this is reserved for that case only — a PATCH with the same value as the persisted theme is a valid `200` no-op.

**Errors**

| Status | `errors` key | Meaning |
|--------|--------------|---------|
| `400` | `body` | Invalid JSON, non-object body, or no recognized fields supplied. |
| `400` | `theme` | Value is not one of the allowed theme ids. |
| `400` | `chat_suggestions` | Value is not an array, has more than 8 entries, or contains a non-string, empty-after-trim, or over-120-code-point entry. |
| `413` | `body` | Request body exceeds 100 KB. |

Unauthenticated requests follow the conventions header — Django's `@login_required` returns a `302` redirect to `/accounts/login/`, NOT a JSON `401`.

---

## Schedule Settings

Per-user schedule day window and IANA timezone. The timezone is the sole server-side source of user-local `now()` for AI draft, chat, and untimed placement. One row per user is created on first authenticated access with `06:00–23:00` and `UTC`. Lives in the `schedules` app, intentionally separate from UI preferences.

`GET` and `PATCH` set `Cache-Control: private, no-store` on every response, including error responses (same rationale as User Preferences).

### `GET /api/user/schedule-settings/`

Returns the current user's window. Creates the default row if none exists.

```json
{"day_start": "06:00", "day_end": "23:00", "time_zone": "UTC"}
```

### `PATCH /api/user/schedule-settings/`

Partial update over the coupled window and independent timezone. `day_start` and `day_end` must be supplied together; `time_zone` can be sent alone. An empty body or a lone window bound is invalid. On validation failure the stored row is unchanged.

**Body**

| Field | Type | Notes |
|-------|------|-------|
| `day_start` | string | `HH:MM`, 5-minute aligned. |
| `day_end` | string | `HH:MM`, 5-minute aligned, later than `day_start` (same calendar day — overnight windows are not supported). |
| `time_zone` | string | Optional IANA identifier, such as `Asia/Almaty`. Invalid values return the stable error below. |

**Errors**

| Status | `errors` key | Meaning |
|--------|--------------|---------|
| `400` | `body` | Invalid JSON or non-object body. |
| `400` | `day_start` / `day_end` | `"{field} is required."`, `"Use HH:MM format."`, `"Must align to 5-minute granularity."`, or (on `day_end`) `"Must be later than day_start; overnight windows are not supported."` |
| `400` | `time_zone` | `"Must be a valid IANA time zone."` when a present value is invalid. |
| `413` | `body` | Request body exceeds 100 KB. |

Unauthenticated requests return a `302` redirect (per the conventions header), not a JSON `401`.

**Note — window enforcement on block placement.** The saved window also constrains the schedule-mutation endpoints (manual create/PATCH, drag/reorder, AI, template, CalDAV/Google from-event). For manual/import writes, a new block/event **fully outside** the window is not created; these endpoints return `422` with a top-level skip envelope: `{"skipped": true, "code": "outside_window", "window": {"start": "HH:MM", "end": "HH:MM"}, "errors": {...}}` (`code`/`window` are top-level siblings, not nested under `errors`). Manual/import partially-outside intervals are clamped to the boundary. AI chat reports skipped actions through outcomes; draft/template validation rejects invalid intervals. Metadata-only edits preserve unchanged boundaries outside a narrowed window. Narrowing the window never mutates existing blocks.

---

## Analytics

### `GET /analytics/{date}/`

Render the Inertia analytics page for today or a past date. Compute current statistics in memory. Use a stored frozen snapshot only when status is `reviewed` and `reviewed_revision` equals the schedule revision. GET does not create or update `DailyReview`, including when a reviewed day has no valid snapshot.

The `review` prop retains counts, category minutes, completion rate and notes. `id`, `created_at` and `updated_at` are null before the first notes save or review. `snapshot_kind` is `current` or `frozen`; `reviewed_revision` is the stored snapshot tag or null. A stale tag can be returned with `snapshot_kind: current`; only the kind establishes the authority of the displayed aggregates.

Invalid or future dates return 400. A missing schedule returns 404; analytics never creates a schedule.

### `POST /api/analytics/schedules/{date}/mark-reviewed/`

Freeze an active day's statistics and change its status to reviewed in the shared User → Schedule → TimeBlock transaction. The schedule revision advances once, and `reviewed_revision` records that resulting revision.

| Field | Type | Requirement |
|-------|------|-------------|
| `expected_revision` | integer | Required on the active path. Missing, invalid or obsolete values return 409. |
| `notes` | string | Optional, at most 2000 characters. Omission preserves notes; an empty string clears them. |

Send `X-Schedule-User` with the captured account ID. Account mismatch returns 401 with `code: session_invalid`.

Success (200) returns review fields and the canonical `schedule`, `blocks` and `revision` mutation snapshot. For example:

```json
{
  "id": 7,
  "schedule_id": 42,
  "date": "2026-04-01",
  "status": "reviewed",
  "planned_count": 5,
  "completed_count": 4,
  "skipped_count": 1,
  "completion_rate": 0.8,
  "planned_minutes_by_category": {"work": 240, "personal": 30, "health": 60, "other": 0},
  "completed_minutes_by_category": {"work": 240, "personal": 0, "health": 60, "other": 0},
  "notes": "Felt focused.",
  "created_at": "...",
  "updated_at": "...",
  "snapshot_kind": "frozen",
  "reviewed_revision": 12,
  "schedule": {"id": 42, "date": "2026-04-01", "status": "reviewed", "revision": 12},
  "blocks": [],
  "revision": 12
}
```

`blocks` contains the day's canonical blocks; the empty array above abbreviates that part of the response.

A reviewed retry runs under the same lock before body parsing or revision validation. A valid snapshot is returned unchanged, including timestamps and revision. Retry notes are ignored. If the reviewed snapshot is missing or its tag is stale, this explicit POST rebuilds it at the existing revision and preserves notes. This is the recovery path for legacy or invalidated reviewed snapshots; GET serves current statistics until repair.

Analytics exposes this recovery as `Update reviewed summary` for a reviewed day without a current frozen snapshot. An up-to-date frozen review hides that button; category maintenance does not perform the explicit repair on the user's behalf.

| Status | Meaning |
|--------|---------|
| 400 | Draft schedule, invalid active-path JSON, or invalid notes. |
| 401 | Captured account does not match the current session. |
| 403 | CSRF validation failed. |
| 404 | No schedule belonging to this user. |
| 409 | Missing, invalid or obsolete active-path revision. |
| 413 | Body exceeds 100 KB, including reviewed retries. |

### `PATCH /api/analytics/schedules/{date}/notes/`

Save `{ "notes": "..." }` by date, with the captured `X-Schedule-User` account ID. Notes must be a string of at most 2000 characters; an empty string clears them. The first save lazily creates `DailyReview` for an existing schedule. The operation locks User then Schedule, preserves aggregates and `reviewed_revision`, and does not advance the schedule revision.

Success (200) returns the review shape described above, using current in-memory aggregates when no valid frozen snapshot exists. Notes storage can therefore exist with `snapshot_kind: current` and `reviewed_revision: null`.

Invalid date/body/notes return 400; account mismatch returns 401; failed CSRF returns 403; a missing or foreign schedule returns 404; an oversized body returns 413. Temporary SQLite contention can return 409; the client does not automatically replay writes.

### `PATCH /api/analytics/reviews/{pk}/notes/`

Compatibility route for an existing review ID. It uses the same validation and locked notes writer as the date route. A missing or foreign review returns 404. New frontend code uses the date route so autosave works before a review row exists.

---

## Example: revision-aware editing

Read the authenticated Inertia schedule props, including `auth_user_id` and the canonical schedule revision. Send `X-Schedule-User`, CSRF and JSON `expected_revision` with create/PATCH/DELETE. After each success use the returned revision and block ID for the next request. A 409 requires refreshing the day before deciding whether to submit a new edit. Reusing an old example's fixed ID or revision is unsafe.

## Integration resource state

Calendar event and external task list responses add `meta: {account_state, resource_state}` alongside `events` or `tasks`. Connected success uses `connected`/`ready`. Missing accounts use `disconnected`/`unavailable`; configuration errors identify the account/configuration problem. Resource failures include `errors.detail`, stable `code` and metadata. A stored-provider credential error uses `code: integration_credentials_error`; an unrelated 401 is a session failure. HTTP status alone does not establish account existence.

Google can return partial success with per-account errors while preserving events from successful accounts. Frontend same-date refresh errors retain prior rows and display the error. Disconnect, date, account or saved-zone changes invalidate old reads and pending optimistic task mutations. Wire helpers live in `backend/common/integration_response.py`.

## Calendar (CalDAV) — feature 0011

Read-only Apple Calendar integration via iCloud CalDAV. The user's
credentials are encrypted at rest with `cryptography.Fernet`
(`CALDAV_ENCRYPTION_KEY`); the service layer is the only code path
that decrypts them.

### `GET /api/calendar/account/`

Returns the calling user's CalDAV account status. Never returns a
password-shaped field.

**Success — `200 OK`**

```json
{
  "connected": true,
  "apple_id": "alice@example.com",
  "base_url": "https://caldav.icloud.com/",
  "last_verified_at": "2026-05-07T09:00:00+00:00",
  "default_base_url": "https://caldav.icloud.com/"
}
```

When disconnected:

```json
{
  "connected": false,
  "apple_id": null,
  "base_url": null,
  "last_verified_at": null,
  "default_base_url": "https://caldav.icloud.com/"
}
```

`default_base_url` echoes `settings.CALDAV_DEFAULT_BASE_URL` regardless
of `connected` so the Settings form populates its advanced field
without hardcoding the default on the frontend.

### `POST /api/calendar/account/`

Verify credentials with iCloud and upsert the per-user `CalDAVAccount`
row. Password is encrypted before persistence; `last_verified_at` is
set to `now()`; `updated_at` advances (rotates the events cache key).

**Request body**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `apple_id` | string | yes | Must be a valid email. |
| `password` | string | yes | App-specific password (never logged). |
| `base_url` | string | no | http/https only. Empty → `default_base_url`. |

**Responses**

- `200 OK` — same shape as `GET /api/calendar/account/`.
- `400` — malformed body, missing fields, bad email/URL format.
- `401` — `CalDAVAuthError` from iCloud.
- `502` — `CalDAVProviderError`.
- `504` — `CalDAVTimeoutError`.
- `429 Too Many Requests` — `CALDAV_CONNECT_RATE_LIMIT_PER_HOUR` budget
  exhausted;
  `{"errors": {"detail": "Rate limit exceeded. Try again later."}}`. The
  response carries a `Retry-After: 3600` header (worst-case wait in
  seconds).
- `500` — `Calendar service is misconfigured` (server-side
  encryption-key issue; ops-only). **Operator action**: confirm
  `CALDAV_ENCRYPTION_KEY` matches the value used when the
  `CalDAVAccount` row was last written. If the key rotated, see
  `.claude/rules/project.md` § "CalDAV key rotation note" for the
  re-encrypt or instruct-reconnect playbook.

All non-`2xx` use `{"errors": {"detail": "<message>", ...}}`.

### `DELETE /api/calendar/account/`

Idempotent delete. Versioned cache keys make stale entries
unreachable (no explicit cache enumeration).

**Success — `200 OK`** — shape identical to a disconnected
`GET /api/calendar/account/`.

### `GET /api/calendar/events/{date}/`

Fetch normalised events for one day. Server-side per-`(user, date,
account_version)` cache (TTL = `CALDAV_CACHE_TTL_SECONDS`, default
`300`). Date-range is single-day in V1.

**Path params**

| Name | Type | Notes |
|------|------|-------|
| `date` | string | `YYYY-MM-DD`. Invalid → `400`. |

**Query params**

| Name | Type | Notes |
|------|------|-------|
| `refresh` | string | Optional (feature 0031). Pass `1` to **bypass** the read cache and force a live provider re-fetch; the result still re-warms the cache, so a subsequent non-forced read is served from cache. Used by background polling (`EXTERNAL_TASKS_POLL_INTERVAL_SECONDS` > 0) via silent `refreshEvents`. |

**Success — `200 OK`**

```json
{
  "events": [
    {
      "title": "Lunch with Pat",
      "start": "2026-05-07T14:00:00+00:00",
      "end":   "2026-05-07T15:00:00+00:00",
      "calendar_name": "Personal",
      "all_day": false,
      "external_uid": "uid@example.com",
      "account_label": ""
    }
  ]
}
```

All-day events have `all_day: true`, original inclusive `start_date` and exclusive `end_date`. Their `start`/`end` instants represent local midnights in the saved user timezone converted to UTC; the range need not be 24 hours across DST. The provider query spans the same local-day UTC bounds. Recurring events return one entry per occurrence
inside the window; `external_uid` includes the `RECURRENCE-ID` so
each occurrence is unique. `account_label` (feature 0022) is the
connecting-account label, shared wire-compatibly with the Google path;
the Apple/CalDAV path always emits the empty-string sentinel (single
account, no label needed).

**Error responses**

| Status | Cause |
|--------|-------|
| `400` | Malformed `date` path param. |
| `401` | `CalDAVAuthError` — Apple rejected stored credentials. |
| `502` | `CalDAVProviderError` — iCloud DAV failure (incl. per-calendar `date_search` errors). |
| `503` | No `CalDAVAccount` configured for this user. |
| `504` | `CalDAVTimeoutError` — request exceeded `CALDAV_REQUEST_TIMEOUT`. |
| `500` | `Calendar service is misconfigured` — `CALDAV_ENCRYPTION_KEY` cannot decrypt the stored row (e.g. key rotation without re-write). **Operator action**: see `.claude/rules/project.md` § "CalDAV key rotation note". |

All non-`2xx` use `{"errors": {"detail": "<message>"}}`.

## Habitica — feature 0024

Habitica task integration via User ID + API token: read outstanding todos and
today's due dailies, mark todos/dailies complete with `score/up`, and force a
live refresh. Tokens are encrypted at rest with Fernet
(`HABITICA_ENCRYPTION_KEY`); service code owns the only decrypt call sites.
No OAuth, no task create/edit, no AI coupling.

Every Habitica provider request sends `x-api-user`, `x-api-key`, and
`x-client: {HABITICA_CLIENT_ID}-DayForge`. `HABITICA_CLIENT_ID` has no default
and is required for `DEBUG=0` boot.

### `GET /api/habitica/account/`

Returns connection status and the non-secret Habitica User ID. Never returns an
API token field.

```json
{
  "connected": true,
  "last_verified_at": "2026-07-22T09:00:00+00:00",
  "api_user_id": "habitica-user-id"
}
```

Disconnected shape:

```json
{ "connected": false, "last_verified_at": null, "api_user_id": null }
```

### `POST /api/habitica/account/`

Verifies credentials with Habitica and upserts the per-user account row.

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `api_user_id` | string | yes | Habitica User ID for `x-api-user`; plaintext and returned in status. |
| `api_token` | string | yes | Habitica API token; encrypted at rest and never returned. |

Errors: `400` validation, `401` invalid credentials, `502` provider failure,
`504` timeout, `429 Too Many Requests` when the
`HABITICA_CONNECT_RATE_LIMIT_PER_HOUR` budget is exhausted;
`{"errors": {"detail": "Rate limit exceeded. Try again later."}}` (the
response carries a `Retry-After: 3600` header, worst-case wait in seconds).
Non-`2xx` responses use `{"errors": {"detail": "<message>"}}`.

### `DELETE /api/habitica/account/`

Idempotent disconnect. Returns the disconnected status shape.

### `GET /api/habitica/tasks/{date}/`

Returns outstanding Habitica tasks for the selected schedule date. Results are
cached per `(user, account_version, time_zone, date, scope)` with
`HABITICA_CACHE_TTL_SECONDS`.

Filter rules:

- Dated todos match `date`; completed todos are excluded.
- On today in the saved user timezone, overdue unfinished todos
  (`due_date < date`) and undated todos are also included.
- On past/future dates, only todos due exactly on that date are included.
- Dailies are fetched only for today in the saved user timezone, using Habitica's
  `type=dailys` query value, and only returned when `isDue` is true.

Query params:

| Name | Notes |
|------|-------|
| `carry_overdue` | Legacy parameter is ignored; only the saved-zone local day establishes today. |
| `refresh=1` | Bypasses the read cache and re-warms it. Used by the sidebar refresh and `EXTERNAL_TASKS_POLL_INTERVAL_SECONDS`. |

Success:

```json
{
  "tasks": [
    {
      "id": "habitica-task-id",
      "title": "Morning routine",
      "type": "daily",
      "due_date": null,
      "completed": false
    }
  ]
}
```

Errors: `400` bad date, `401` invalid stored credentials, `502` provider
failure/malformed envelope, `503` no Habitica account, `504` timeout, `500`
misconfigured encryption key.

### `POST /api/habitica/tasks/{id}/complete/`

Scores up one Habitica todo or daily via `POST /tasks/{id}/score/up` with an
empty JSON body. This is one-way; un-complete is not supported. Habitica returns
`200` with XP/streak data, which Day Forge ignores and maps to:

```json
{ "ok": true }
```

Successful complete invalidates the Habitica task cache by bumping
`account.updated_at`.

## Travel-time rules — feature 0026

Per-user rules that prefill the "Add to schedule" dialog when adding an
external calendar event to the timeline. Keyword rules match a
case-insensitive substring of `keyword` in the event title; a keyword rule
can optionally be restricted to an exact (case-insensitive) source calendar
name. Calendar-only rules match the exact source calendar name. Matching is
client-side in ascending `order` within each class, and **keyword rules always
win before calendar-only rules**, regardless of their relative order.
Provider-agnostic (applies to CalDAV and Google events alike); owned by the
`calendar_sync` app. All routes are `@login_required`; validation mirrors the
templates_mgr rules endpoints.

**Serialised shape**

```json
{
  "id": 3,
  "keyword": "dentist",
  "calendar_name": "Work",
  "travel_there_minutes": 30,
  "travel_back_minutes": 30,
  "category": "",
  "order": 0
}
```

`category` is `""` (no override → block defaults to `other`) or one of
`work`, `personal`, `health`, `other`.

### `GET /api/calendar/travel-rules/`

Returns `{"travel_rules": [...]}` ordered by `(order, id)` ascending.

### `POST /api/calendar/travel-rules/`

Create a rule. Body fields:

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `keyword` | string | no* | 0–100 chars after `strip()`. |
| `calendar_name` | string | no* | 0–200 chars after `strip()`. Exact, case-insensitive source calendar-name match. |
| `travel_there_minutes` | integer | no | `0 ≤ n ≤ 600`. Default `0`. Booleans rejected. |
| `travel_back_minutes` | integer | no | Same bounds. Default `0`. |
| `category` | string | no | `""` or a valid category. Default `""`. |
| `order` | integer | no | `−1000000 ≤ n ≤ 1000000`. When omitted, assigned `(max order for the user) + 1` so new rows are born distinct and the up/down reorder swap always changes ordering. |

Per-user cap: **100 rules** (`400` beyond it). Body capped at 100 KB
(`413`). Success → `201` with the serialised rule.

\* At least one of `keyword` or `calendar_name` must be non-empty after
trimming. An empty `calendar_name` on a keyword rule means it matches any
calendar. Use the exact Google or Apple calendar name (for example, `Work`),
not the account email. Violations return `400 {"errors":
{"match_constraints": "At least one of keyword or calendar_name is
required."}}` — `match_constraints` is a non-field key (it belongs to neither
individual field), so clients parsing field-level errors should treat it as a
form-level error, not a model field.

### `PATCH /api/calendar/travel-rules/{pk}/`

Partial update; all fields are optional, but the merged rule must retain at
least one non-empty `keyword` or `calendar_name`. Success → `200` with the
serialised rule.

### `DELETE /api/calendar/travel-rules/{pk}/`

Success → `200 {"ok": true}`.

Cross-user `pk` access returns `404` (not `403`) on both `PATCH` and
`DELETE` — same id-enumeration convention as `PATCH /api/blocks/{pk}/`.

### `POST /api/calendar/travel-rules/swap/`

Atomically swaps the `order` values of two travel rules owned by the current
user.

```json
{"a": 3, "b": 4}
```

Success → `200 {"travel_rules": [...]}` containing both swapped rows. A
missing or cross-user id returns `404`; non-integer ids (including booleans)
or equal ids return `400` with `errors.body`. The two writes occur in one
transaction, so they both commit or neither does.

## Calendar (Google) — feature 0022

Read-only, **multi-account, multi-calendar** Google Calendar events via OAuth
2.0 (authorization-code flow, offline access + refresh tokens). Feeds the
**same** provider-agnostic `ExternalEventsPanel` as CalDAV — events merge into
one chronological list. Account credentials are encrypted at rest
(`GOOGLE_OAUTH_TOKEN_KEY`); the service layer is the only decryption surface.
All routes are `@login_required`.

### `GET /api/calendar/google/connect/`

Starts the OAuth flow. Generates a CSRF `state` (stored in the session) and
`302`-redirects (full-page) to Google's consent screen. Connecting (or
reconnecting) **always** shows the consent screen — `prompt=consent` is
intentional so a refresh token is guaranteed; this is expected, not an error.

### `GET /api/calendar/google/callback/?code=&state=`

OAuth callback. Validates `state` against the session value (CSRF guard;
popped so it can't be replayed), exchanges the `code` for tokens + account
identity (`sub`/`email` from a verified `id_token`), and upserts the
`GoogleCalendarAccount` (uniqueness `(user, google_account_id)` → reconnect is
idempotent). Always `302`-redirects to Settings:

| Redirect | When |
|----------|------|
| `/settings/?google=connected` | Success. |
| `/settings/?google=error&reason=state` | Missing/mismatched `state` (CSRF guard). Also the session-expired-mid-consent case (V1 limitation — retry Connect after signing in). |
| `/settings/?google=error&reason=denied` | Google returned `?error=` (user denied). |
| `/settings/?google=error&reason=missing_code` | Neither `code` nor `error` present. |
| `/settings/?google=error&reason=provider` | Token exchange / grant-probe failure. |

### `GET /api/calendar/google/accounts/`

Lists the calling user's connected Google accounts. **Never** returns a token
field.

```json
{ "accounts": [ { "id": 1, "email": "you@gmail.com", "last_verified_at": "2026-05-07T09:00:00+00:00" } ] }
```

### `DELETE /api/calendar/google/accounts/{account_id}/`

Disconnect one account. Scoped to `request.user` (IDOR guard); idempotent.
Returns the refreshed list in the same shape as `GET /accounts/`.

### `GET /api/calendar/google/events/{date}/`

`async` multi-account fetch (the deploy is ASGI/uvicorn). Fetches across every
connected account × selected calendar concurrently. Server-side per-`(user,
account, date, account_version, time_zone)` cache (TTL = `GOOGLE_CACHE_TTL_SECONDS`).

**Path params**

| Name | Type | Notes |
|------|------|-------|
| `date` | string | `YYYY-MM-DD`. Invalid → `400`. |

**Query params**

| Name | Type | Notes |
|------|------|-------|
| `refresh` | string | Optional (feature 0031). Pass `1` to **bypass** every connected account's read cache and force live re-fetches; each success still re-warms that account's cache. Used by background polling (`EXTERNAL_TASKS_POLL_INTERVAL_SECONDS` > 0) via silent `refreshEvents`. |

**Success — `200 OK`** (composite shape; `account_errors` is **always**
present, empty when all accounts loaded):

```json
{
  "events": [
    {
      "title": "Standup",
      "start": "2026-05-07T09:00:00+00:00",
      "end":   "2026-05-07T09:15:00+00:00",
      "calendar_name": "Team",
      "all_day": false,
      "external_uid": "abc123@google",
      "account_label": "you@gmail.com"
    }
  ],
  "account_errors": [
    { "account_id": 2, "email": "old@gmail.com", "error": "reconnect_required" }
  ]
}
```

**Partial success** is the core contract: one account's revoked grant becomes
an `account_errors[]` entry (`reconnect_required`) while the others' events
still load — a single bad account never blanks the panel. Transient
provider/timeout failures use `error: "unavailable"`. `external_uid` is
namespaced (`<id>@google`) so it can't collide with a CalDAV UID; cancelled
recurring instances are dropped.

The response also carries `meta.account_state: connected`. Its `resource_state` is `ready` if at least one account succeeded, including a successful empty account. If all accounts failed it is `provider_error` when any account is unavailable, otherwise `credentials_error`. All-failed retains HTTP 200, empty `events` and the current per-account errors.

The Google frontend adapter preserves last-good events for the active date/context on that all-failed response and shows a provider banner plus account errors. A successful empty `ready` response clears old events, even when another account failed; partial ready results replace them. Date, account/session context, saved-zone changes and disconnect clear retained rows. A first failure shows the error without events or a successful-empty-day message.

**Error responses** (whole-request, not per-account):

| Status | Cause |
|--------|-------|
| `400` | Malformed `date` path param. |
| `503` | No `GoogleCalendarAccount` configured for this user. |
| `500` | `Google Calendar service is misconfigured. Contact the administrator.` — `GOOGLE_OAUTH_TOKEN_KEY` cannot decrypt a stored row (server-wide; e.g. key rotation). **Operator action**: see `.claude/rules/project.md` § "Google Calendar token rotation note". |

All non-`2xx` use `{"errors": {"detail": "<message>"}}`.

## Todoist — features 0020, 0021

Todoist task integration via a personal API token: read the day's tasks,
mark a task complete (0021), and force a live refresh (0021). The token is
encrypted at rest with `cryptography.Fernet` (`TODOIST_ENCRYPTION_KEY`);
the service layer is the only code path that decrypts it (two call sites:
`fetch_tasks_for_date` + `complete_task`). No OAuth, no task
creation/editing/re-open, no AI coupling — task text is never sent to the
LLM provider.

### `GET /api/todoist/account/`

Returns the calling user's Todoist account status. Never returns a
token-shaped field.

**Success — `200 OK`**

```json
{
  "connected": true,
  "last_verified_at": "2026-06-17T09:00:00+00:00"
}
```

When disconnected:

```json
{
  "connected": false,
  "last_verified_at": null
}
```

### `POST /api/todoist/account/`

Verify the token with Todoist and upsert the per-user `TodoistAccount`
row. The token is encrypted before persistence; `last_verified_at` is set
to `now()`; `updated_at` advances (rotates the tasks cache key).

**Request body**

| Field | Type | Required | Notes |
|-------|------|----------|-------|
| `token` | string | yes | Todoist personal API token (never logged). Length cap 128. |

**Responses**

- `200 OK` — same shape as `GET /api/todoist/account/`.
- `400` — malformed body, missing/empty `token`, over length cap.
- `401` — `TodoistAuthError` (Todoist rejected the token).
- `502` — `TodoistProviderError`.
- `504` — `TodoistTimeoutError`.
- `429 Too Many Requests` — `TODOIST_CONNECT_RATE_LIMIT_PER_HOUR` budget
  exhausted;
  `{"errors": {"detail": "Rate limit exceeded. Try again later."}}`. The
  response carries a `Retry-After: 3600` header (worst-case wait in
  seconds).
- `500` — `Todoist service is misconfigured. Contact the administrator.`
  (server-side encryption-key issue; ops-only). **Operator action**: see
  `.claude/rules/project.md` § "Todoist token rotation note".

All non-`2xx` use `{"errors": {"detail": "<message>", ...}}`.

### `DELETE /api/todoist/account/`

Idempotent delete. Versioned cache keys make stale entries unreachable.

**Success — `200 OK`** — shape identical to a disconnected
`GET /api/todoist/account/`.

### `GET /api/todoist/tasks/{date}/`

Fetch normalised active (non-completed) tasks for one day. Server-side
per-`(user, date, account_version, time_zone)` cache (TTL = `TODOIST_CACHE_TTL_SECONDS`,
default `300`).

**Path params**

| Name | Type | Notes |
|------|------|-------|
| `date` | string | `YYYY-MM-DD`. Invalid → `400`. |

**Date → filter behavior:** today is computed in the saved user timezone. Today uses Todoist's date filter plus overdue carryover; other dates use the exact date filter. Tasks without a due date and completed tasks do not appear. The frontend does not supply a browser-time bridge.

| Query parameter | Effect |
|---|---|
| `carry_overdue` | Legacy parameter is ignored. |
| `refresh=1` | Bypass read cache and re-warm it after a successful provider fetch. |

The cache separates `exact` and `with_overdue` scope and includes the saved timezone, so midnight or timezone changes cannot reuse the wrong result.

**Success — `200 OK`**

```json
{
  "tasks": [
    {
      "id": "7654321",
      "title": "Submit quarterly report",
      "priority": 4,
      "ui_priority": "P1",
      "due_date": "2026-06-17"
    }
  ]
}
```

`priority` is the raw Todoist int (`4` = highest); `ui_priority` is the
inverted UI label (`4→P1 … 1→P4`). `due_date` is an ISO `YYYY-MM-DD`
string or `null` (the time component of timed tasks is dropped — date-only
display). Sorted by priority (highest first), then due date, title, id.

**Error responses**

| Status | Cause |
|--------|-------|
| `400` | Malformed `date` path param. |
| `401` | `TodoistAuthError` — Todoist rejected the stored token. |
| `502` | `TodoistProviderError` — Todoist API failure. |
| `503` | No `TodoistAccount` configured for this user. |
| `504` | `TodoistTimeoutError` — request exceeded `TODOIST_REQUEST_TIMEOUT`. |
| `500` | `Todoist service is misconfigured. Contact the administrator.` — `TODOIST_ENCRYPTION_KEY` cannot decrypt the stored row (e.g. key rotation without re-write). **Operator action**: see `.claude/rules/project.md` § "Todoist token rotation note". |

All non-`2xx` use `{"errors": {"detail": "<message>"}}`.

### `POST /api/todoist/tasks/{id}/complete/` — feature 0021

Close (complete) one Todoist task. CSRF-protected (Django session +
`X-XSRF-TOKEN`). Parses **no** request body — the task id is in the URL
path. On success the server invalidates this user's task cache (bumps
`account.updated_at`, rotating every `todoist_tasks:*` key) so the
just-closed task is not re-served from a stale cache.

> Completing a recurring task closes its **current occurrence** (Todoist
> `POST /tasks/{id}/close` semantics). Un-complete / re-open is **not**
> supported — the frontend's optimistic rollback is local UI only.

**Path params**

| Name | Type | Notes |
|------|------|-------|
| `id` | string | Opaque Todoist task id (alphanumeric, e.g. `6X7rfFVPjhvv84XG` — **not** numeric). Round-trips from `GET /api/todoist/tasks/{date}/`. |

**Success — `200 OK`**

```json
{ "ok": true }
```

A bare ack — the frontend already removed the row optimistically, so the
refreshed list is not returned (avoids a second provider round-trip).

**Error responses**

| Status | Cause |
|--------|-------|
| `401` | `TodoistAuthError` — Todoist rejected the stored token. |
| `502` | `TodoistProviderError` — Todoist API failure (incl. a stale/unknown id → provider `404`). |
| `503` | No `TodoistAccount` configured for this user. |
| `504` | `TodoistTimeoutError` — request exceeded `TODOIST_REQUEST_TIMEOUT`. |
| `500` | `Todoist service is misconfigured. Contact the administrator.` — `TODOIST_ENCRYPTION_KEY` cannot decrypt the stored row. **Operator action**: see `.claude/rules/project.md` § "Todoist token rotation note". |

All non-`2xx` use `{"errors": {"detail": "<message>"}}`.
