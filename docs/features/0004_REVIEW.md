# Phase 4 — Code Review: AI Command Bar

Originally reviewed against `docs/features/0004_PLAN.md` on 2026-04-18.
Re-reviewed on 2026-04-18 after the fix pass.

**Status:** ✅ All blocking and near-blocking findings have been addressed.
`uv run pytest backend/tests/ -q` → **141 passed**. `npx vitest run` → **25
passed**. `uv run ruff check backend/` and `npx vue-tsc --noEmit` are clean.

The first two sections summarise what was fixed and how. The original findings
follow for historical context.

---

## Fix verification (2026-04-18)

### Plan deviations

| # | Finding | Status | Evidence |
|---|---------|--------|----------|
| 1 | Structured Outputs (`json_schema` mode) not used | ✅ **Documented** — not adopted, but the trade-off is now explicit. `backend/ai/service.py:8-16` explains the `LLM_BASE_URL` rationale and that post-parse validation fills the gap. `backend/ai/schemas.py:2-10` updated to match. |
| 2 | Validation primitives re-implemented instead of reused | ✅ **Extracted**. New `backend/schedules/http.py` (173 lines) owns `parse_time`, `parse_time_or_error`, `validate_block_times`, `validate_five_minute_or_error`, `validate_time_range`, `validate_sort_order`, `block_to_dict`, `reject_oversized_body`, `times_overlap`, `is_plain_int`, `VALID_CATEGORIES`. `schedules/api.py` re-exports via private aliases for backward compat; `ai/views.py` imports the public names directly. |
| 3 | `_apply_action` is a monolithic branch | ✅ **Refactored**. Split into `_apply_add`, `_apply_remove`, `_apply_move_or_resize`, plus a `_compute_move_resize_times` helper and a `_ACTION_DISPATCH` dict (`backend/ai/views.py:112-243`). |
| 4 | No Russian-command test | ✅ **Added**. `TestBilingual::test_russian_command_round_trips` in `backend/tests/test_ai_views.py:267-299` asserts Cyrillic survives the round trip in both the command body and the `explanation`, and shows up intact in the `AIInteraction.user_command`. |

### Bugs

| # | Finding | Status | Evidence |
|---|---------|--------|----------|
| 2.1 | Duration-preserving `move` wraps past midnight silently | ✅ **Fixed**. `_compute_move_resize_times` detects `new_end <= new_start` post-wrap and returns a `wrapped=True` flag; `_apply_move_or_resize` returns the explicit `"moved block would extend past midnight"` 400. Covered by `TestMidnightWrap` (`test_ai_views.py:447-478`). |
| 2.2 | `_log_interaction` logging policy ambiguous | ✅ **Documented**. Docstring on `_log_interaction` (`views.py:52-62`) now explicitly states "forensic fidelity" is the intent — pre-trim, pre-validation command text is preserved on purpose, with response truncation as the only safety net. |
| 2.3 | `Schedule.get_or_create` runs before the LLM-availability check | ⚪ **Accepted as-is**. Matches the pattern in `create_block` / `restore_blocks`; not fixed, flagged earlier as consistent-with-codebase. Non-destructive. |
| 2.4 | `add` tolerates missing `category` | ✅ **Fixed**. `_REQUIRED_FIELDS["add"]` now includes `"category"` (`ai/schemas.py:20-25`); the view's `.get("category", "other")` is kept as defence-in-depth and explicitly commented (`views.py:114-117`). |
| 2.5 | `move` / `resize` with only `task_id` silently no-op | ✅ **Fixed**. `validate_action_shape` now rejects these at the schema layer with `"{action_type} action requires at least one of 'start_time' or 'end_time'"` (`schemas.py:61-70`). Covered by `test_ai_service.py::test_move_without_time_field_raises` and `test_resize_without_time_field_raises`. |
| 2.6 | `_AI_ERROR_STATUS[type(e)]` would `KeyError` on a subclass | ✅ **Fixed**. Replaced with an MRO-walking lookup that falls back to 500: `next((s for cls, s in _AI_ERROR_STATUS.items() if isinstance(e, cls)), 500)` (`views.py:284-289`), with a comment explaining why. |
| 2.7 | `useAI` treated 200-with-empty-body as an error | ✅ **Fixed**. Both `useAI.ts` and `useSchedule.ts` now delegate to a shared `requestJson` in `frontend/src/composables/useHttp.ts`, which reads `resp.text()` first and only parses non-empty bodies. |
| 2.8 | Module-level state in `useAI.ts` foreshadows a bug if a second consumer appears | ✅ **Documented**. Both `useAI.ts:9-13` and `CommandBar.vue:2-6` spell out the assumption and the migration path ("if a second consumer is ever added, move state back into `useAI()`"). |

### Test coverage

| # | Gap | Status | Evidence |
|---|-----|--------|----------|
| B1 | Russian-language command | ✅ Added (see above). |
| B2 | View-level `AIParseError` → 502 + raw text logged | ✅ `TestParseErrorLogging::test_parse_error_returns_502_and_logs_raw` (`test_ai_views.py:302-316`). |
| B3 | `add` overlap rejection path | ✅ `TestAddOverlapRejection::test_add_rejected_when_overlapping_existing_block` (`test_ai_views.py:319-352`). |
| B4 | 5-minute granularity for `move` / `resize` | ✅ `TestGranularity` with both start- and end-time cases (`test_ai_views.py:355-406`). |
| B5 | Oversized user-command → 400 (not 413) | ✅ `TestOversizedCommand::test_oversized_command_returns_400` (`test_ai_views.py:409-425`), uses the `settings` fixture to set `LLM_API_KEY`. |
| B6 | `_MAX_AI_RESPONSE_LOG_LEN` truncation | ✅ `TestInteractionTruncation::test_log_truncates_oversized_response` (`test_ai_views.py:428-444`) — 50 KB in, exactly 10 KB stored. |
| F1 | `lastExplanation` happy path | ✅ `useAI.test.ts:77-85` "records explanation on success". |
| F2 | `clearError()` fires on user input | ✅ `CommandBar.test.ts:152-161` "clears the error when the user edits the input". |
| F3 | Escape clears the input | ✅ `CommandBar.test.ts:163-171` "clears input and error when Escape is pressed". |
| F4 | `setInterval` leak between tests | ✅ `CommandBar.test.ts:28, 52-55` — `afterEach` unmounts the wrapper and the comment explains why. |

### Style / API nits

| # | Nit | Status |
|---|-----|--------|
| 5.1 | `from typing import Any` unused in `service.py` | ✅ Removed; `parsed` is untyped at the call site and narrowed by the validator. |
| 5.2 | `AIParseError.__init__` default `raw_response_text=""` was dead code | ✅ Made required (`service.py:64`); every call site already passes it. |
| 5.3 | `schemas.py` docstring contradicted the plan | ✅ Rewritten to describe the `json_object` choice and point readers at `ai/service.py` for the rationale. |
| 5.4 | Placeholder text has a stray double space | ✅ Fixed — `'  (press / to focus)'` → `' (press / to focus)'` (`CommandBar.vue:110`). |
| 5.5 | Error row has no keyboard affordance | ✅ Added `role="alert" tabindex="0" @keydown.enter="clearError" @keydown.space.prevent="clearError"` (`CommandBar.vue:119-128`). |
| 5.6 | "Reuse category-color tokens" in `app.css` | ⚪ **Withdrawn**. Verified there are no category-color CSS custom properties in `frontend/src/app.css`; the plan's instruction referenced tokens that don't exist yet. Current raw hex values stay until those tokens are introduced in a later phase. |

### File-size snapshot after the fix pass

- `backend/schedules/api.py`: 795 → **655 lines** (helpers moved out).
- `backend/schedules/http.py`: **173 lines** (new).
- `backend/ai/views.py`: 253 → **320 lines** — grew slightly because the
  monolithic `_apply_action` was split into four focused helpers. The extra
  lines are docstrings and dispatch scaffolding, not new logic.

---

## Summary

The original review flagged 2 plan-alignment gaps, 8 bugs (1 accepted-by-convention, 7 requiring fixes), 10 test-coverage gaps, and 6 style nits. After the fix pass:

- 2 / 2 plan gaps addressed (Structured Outputs decision documented;
  helpers extracted and reused).
- 7 / 7 actionable bugs fixed.
- 10 / 10 test gaps closed. Total test count rose by 13 (23 → 36 backend AI
  tests, plus ~3 new frontend cases).
- 5 / 6 nits fixed; the remaining one (category-color tokens) was retracted
  as the referenced tokens don't exist.

No new issues were introduced. The feature is ready for the phase-5 work to
build on top of it.

---

## Original review (historical, for context)

## 1. Plan alignment

Overall the feature is implemented end-to-end and the architecture matches the
plan: prompt builders are pure, service is a thin SDK wrapper, view layers
validation → LLM → intent log → atomic apply, frontend bar is fixed-bottom,
status-dotted, undo-integrated. The test suites exist at roughly the scope the
plan asked for. The pieces below deviate from the plan — some deliberately,
some worth a second look.

### 1.1 Deliberate deviations (fine, but undocumented trade-offs)

- **Env var naming: `LLM_*` instead of `OPENAI_*`.** The plan called for
  `OPENAI_API_KEY`, `OPENAI_COMMAND_MODEL`, `OPENAI_REQUEST_TIMEOUT_SECONDS`,
  `OPENAI_MAX_COMMAND_CHARS`. The implementation uses a provider-agnostic
  `LLM_API_KEY` / `LLM_BASE_URL` / `LLM_MODEL` / `LLM_REQUEST_TIMEOUT` /
  `LLM_MAX_COMMAND_CHARS` naming scheme (`backend/day_forge/settings.py:120`).
  That's a reasonable change — `LLM_BASE_URL` lets OpenRouter / self-hosted
  proxies slot in without a rename later — but it should be explicitly noted
  somewhere. `.claude/rules/project.md` documents the new names, so this is
  only a plan-doc vs implementation rename, not a bug.

- **No `OPENAI_COMMAND_MODEL` / `OPENAI_DRAFT_MODEL` split.** The plan wanted
  a separate command-model setting so Phase 5 could pick a different draft
  model. The implementation uses a single `LLM_MODEL`. Easy to add later;
  non-blocking for Phase 4.

- **No shared `apiFetch` extraction.** The plan said `useAI.ts` should use
  `apiFetch` from `useSchedule.ts`, but `apiFetch` is local to `useSchedule.ts`
  and was not exported. `useAI.ts` reimplements `getCsrfToken` + `fetch`
  wrapping (`frontend/src/composables/useAI.ts:5-10, 42-92`). Behaviour is
  equivalent but the duplication guarantees the two will drift. A 20-line
  extract to a shared `http.ts` module would close the issue; see §4.

### 1.2 Questionable deviations (call out before next phase)

- **Structured Outputs not used.** The plan was explicit:
  > `response_format={"type": "json_schema", "json_schema": COMMAND_RESPONSE_JSON_SCHEMA}` … `strict: true` enabled on the outer schema.
  …and expected `COMMAND_RESPONSE_JSON_SCHEMA` exported from `ai/schemas.py`.
  Instead, `ai/service.py:115` uses `response_format={"type": "json_object"}`
  and the schema is only described in the system prompt.
  `validate_response_envelope` / `validate_action_shape` catch the shape
  post-parse. The runtime validators are fine, but OpenAI Structured Outputs
  would reject non-conforming responses at the provider, shortening the error
  path (no `AIParseError` for schema mismatches at all). If the `LLM_BASE_URL`
  flexibility is what motivated the deviation, that trade-off should be
  explicit in a comment on `_get_client()` — not every OpenAI-compatible
  provider supports `json_schema` mode. Worth documenting explicitly.

- **Validation and overlap primitives are re-implemented, not reused.** The
  plan said:
  > All four action types reduce to existing validated primitives already used by `create_block`, `block_detail` (PATCH / DELETE), and the domain invariants enforced inside `transaction.atomic()`. **Reuse, do not reimplement.**
  `_apply_action` in `backend/ai/views.py:86-180` re-implements parse-time,
  5-minute granularity, range, and overlap checks inline, despite
  `schedules/api.py` already exposing `_parse_time`, `_parse_time_or_error`,
  `_validate_five_minute_or_error`, `_validate_time_range`, and
  `_validate_block_times`. As a result there are now two parallel
  implementations of the same rules (e.g. overlap is checked three different
  ways across `create_block`, `reorder_blocks`, and `_apply_action`). Either
  extract those helpers into a shared module (as the plan hinted —
  `backend/schedules/http.py`) or thread them through. The current
  duplication is a maintenance hazard: a future change to the 5-min rule or
  overlap semantics will only be applied in one place. Non-blocking but
  should be cleaned up in Phase 5 before more AI actions are added.

- **No explicit Russian-command test.** Plan §Test Coverage explicitly
  called for:
  > `ai_command` bilingual: Russian command returns the same shape (parsing is the model's job; mock a canned JSON response).
  `test_ai_views.py` has no Russian-language test case. Trivial to add
  (canned `AICommandResult`, assert 200 with Russian `explanation` pass-through
  and `user_command` containing Cyrillic bytes).

---

## 2. Bugs and subtle issues

### 2.1 Duration-preserving `move` can wrap past midnight silently

```145:157:backend/ai/views.py
    new_start = _parse_time(action["start_time"]) if "start_time" in action else block.start_time
    new_end = _parse_time(action["end_time"]) if "end_time" in action else block.end_time

    if kind == "move" and "end_time" not in action:
        original = (
            datetime.datetime.combine(datetime.date.min, block.end_time)
            - datetime.datetime.combine(datetime.date.min, block.start_time)
        )
        new_end = (
            datetime.datetime.combine(datetime.date.min, new_start) + original
        ).time()
```

If a user says `"move gym to 23:00"` and gym is `22:00–23:30` (90 min), the
duration-preserving arithmetic produces `new_end = 00:30`. `.time()` silently
wraps; `new_start (23:00) >= new_end (00:30)` so the call returns a 400
`"start_time must be < end_time"`. User-visible behaviour is correct (refuses
the action) but the error message is confusing. Either:

- detect the wrap (`new_end <= new_start`) and return a clearer
  `"moved block would extend past midnight"` error, or
- clamp `new_end` to `DAY_END` and let the prompt rules' day-window
  enforcement take over.

Low severity, but easy to misdiagnose as a validator bug.

### 2.2 `_log_interaction` writes pre-trim, pre-validated user input

`ai_command` logs on every failure path:

```218:222:backend/ai/views.py
    except AIError as e:
        raw = getattr(e, "raw_response_text", "") or str(e)
        _log_interaction(schedule, command, raw, [])
```

`command` here is the raw body value, not `command.strip()`. So a payload with
`"command": "   "` triggers `AIInvalidInputError` inside `run_command` and then
`_log_interaction` persists 3 whitespace chars as `user_command`. Same for a
100 KB oversized-but-valid string (body is capped to 100 KB but that's still a
lot of whitespace in `AIInteraction.user_command`).

This is defensible (we want to know exactly what the client sent) but should
be a conscious choice. If the intent is "log the normalised command the LLM
actually saw", strip before logging. If the intent is forensic fidelity,
document it in the function docstring.

### 2.3 `Schedule` row is always created before the LLM check

`Schedule.objects.get_or_create(...)` runs *before* `run_command`
(`ai_command:204`). That means even a 503 ("no API key") creates an empty
`Schedule` row on disk if none existed for that date. A user who spams the
command bar with `LLM_API_KEY` unset will silently create many empty
schedules. Non-destructive, but surprising — other mutation endpoints
(`create_block`, `restore_blocks`) also `get_or_create`, so this is at least
consistent with the rest of the codebase.

### 2.4 `schemas.validate_action_shape`: `add` doesn't require `category`

`_REQUIRED_FIELDS["add"] = {"title", "start_time", "end_time"}` — `category`
is not in the required set, so `validate_action_shape` lets `{"type":"add", …}`
through without one. The view then falls back to `"other"` at
`views.py:97`. The plan and `SYSTEM_PROMPT` both declare `category` as a
required field for `add`. The current behaviour (tolerant default) is arguably
kinder to the model, but it disagrees with the stated contract. Either:

- add `"category"` to `_REQUIRED_FIELDS["add"]` (strict), or
- update the docstring / plan wording to match the "default to `other`"
  system-prompt rule.

### 2.5 Empty-op `move` / `resize` are silently accepted

`_REQUIRED_FIELDS["move"] = {"task_id"}` and the view branches default
`new_start` / `new_end` to the block's current values. Result: a model that
emits `{"type":"move","task_id":5}` with no time fields produces a no-op that
still counts as a successful action. Same for `resize`. Cosmetic (the action
rolls through the DB as an unchanged `.save()`), but it means the AI can
"succeed" while not doing what the user asked. Minimum bar: require at least
one of `start_time` / `end_time` for `move` and `resize` in
`validate_action_shape`.

### 2.6 `AIError` taxonomy is matched by exact `type(e)`

```221:222:backend/ai/views.py
        status = _AI_ERROR_STATUS[type(e)]
        return JsonResponse({"errors": {"detail": str(e)}}, status=status)
```

All five concrete classes are in `_AI_ERROR_STATUS`, so this works today. If
anyone introduces a further subclass (e.g. `AIRateLimitError(AIProviderError)`)
the `KeyError` at runtime will 500 instead of 502. Use
`next((status for cls, status in _AI_ERROR_STATUS.items() if isinstance(e, cls)), 500)`
or walk `type(e).__mro__`. Tiny robustness issue.

### 2.7 `useAI`: 200-with-empty-body is treated as failure

```61:73:frontend/src/composables/useAI.ts
    if (resp.ok) {
      let data: Record<string, unknown> | undefined
      try {
        data = await resp.json()
      } catch {
        lastError.value = "Invalid server response."
        return { ok: false, errors: { detail: lastError.value } }
      }
      …
      router.reload({ only: ["blocks"] })
      return { ok: true, data }
    }
```

`resp.json()` on a 200 with empty body throws, flipping the UI into an
error state even though the server said OK. Current backend always returns
`{blocks, explanation}` so this is latent; still, `useSchedule.ts:39-45`
handles the empty case correctly with `resp.text()` + conditional parse. It
would be nice to match that pattern and avoid a divergence.

### 2.8 `useAI` module-level state survives across mounts

```17:23:frontend/src/composables/useAI.ts
// Single module-level state: the command bar is rendered once, so we don't
// need per-instance refs. This also lets the status dot share state across
// components without prop drilling.
const isProcessing = ref(false)
const lastError = ref<string | null>(null)
const lastExplanation = ref<string | null>(null)
const apiHealthy = ref(true)
```

Deliberate and clearly commented. The one gotcha is tests: `useAI.test.ts`
resets state in `beforeEach` to avoid cross-test leakage, which works but
foreshadows a pain point. If a second `useAI()` consumer is ever needed (e.g.
a chat drawer), the shared state will cause bugs. Worth adding a one-line
comment on the CommandBar component that it's the unique consumer.

---

## 3. Test coverage

### 3.1 Backend

**Good:**
- Every `AIError` subclass → HTTP status mapping is exercised
  (`test_ai_views.py:173-220` covers 503 / 504 / 502 / 400-cross-user).
- `run_command` input validation, provider-error mapping, parse failures, and
  success-path prompt wiring are all covered in `test_ai_service.py`.
- Atomicity: `test_mid_batch_failure_rolls_back` is the exact scenario the
  plan called out and it verifies both DB rollback and the interaction row
  surviving (`test_ai_views.py:224-256`).
- Cross-user `task_id` 400 + no side-effect (`:196-221`).

**Gaps (ordered by importance):**

1. **No Russian-language command test.** Plan called this out explicitly.
2. **No view-level `AIParseError` test.** The service covers parse failures,
   but there's no integration test that a 502 from `AIParseError` logs the
   raw response text to `AIInteraction.ai_response` — the plan's "invalid
   JSON from model → 502 + logged with raw text" requirement.
3. **No test for the `add` action overlap-rejection path.** Happy-path
   `test_add_action` adds to an empty schedule; the view's overlap check in
   `_apply_action` is only covered implicitly by `test_mid_batch_failure_rolls_back`
   (which is an add-vs-add overlap). No test for `"add X at 09:00–10:00"`
   rejected because a pre-existing block is already there.
4. **No test that `move`/`resize` respect 5-minute granularity.** The view
   enforces it, and the catch in `_apply_action` differs from the shared
   helper (`e.message` vs `e.message_dict`). Worth a direct test.
5. **No test for oversized user-command input (not body) → 400.** The plan's
   test list includes "oversized input → 400"; currently only the service
   unit test covers `AIInvalidInputError`, and the view turns it into a 400
   but no integration test asserts the status code + `AIInteraction` row.
6. **`_log_interaction` truncation** (`_MAX_AI_RESPONSE_LOG_LEN`) has no
   regression test. A 50 KB provider response should produce a 10 KB
   `ai_response` field. Important because TextField has no DB cap and the
   comment promises protection.

### 3.2 Frontend

**Good:**
- `useAI.test.ts` exercises CSRF header, JSON body, `isProcessing` toggle,
  `apiHealthy` flips on 503/502, recovery on next 200, 400-doesn't-flip, and
  network error.
- `CommandBar.test.ts` covers Enter submit, success `pushUndo` payload,
  failure-keeps-input, ignored empty submits, ignored during
  `isProcessing`, `/` focus behaviour including the editable-field guard,
  the DataCloneError snapshot regression, and the unhealthy dot rendering.

**Gaps:**

1. **No test for the `lastExplanation` happy path.** `useAI.test.ts` never
   asserts `lastExplanation.value === "ok"` after a 200. Given the
   explanation row is user-visible, this is worth an explicit assertion.
2. **No test for `clearError()` being called on input.** The CommandBar
   calls it from `handleInput`; trivial to verify with a `setValue` after
   an error is set.
3. **No test for Escape clearing the input.** `handleKeydown` covers it;
   easy regression magnet.
4. **Placeholder rotation timer.** Not high-value to test, but the current
   setup leaks a `setInterval` if a test unmounts via `attachTo` and relies
   on GC. `mountBar()` in several tests *doesn't* call `wrapper.unmount()`
   (lines 53, 74 in `CommandBar.test.ts` use `mount(...)` directly, return
   value never unmounted). Two of the seven tests explicitly call
   `wrapper.unmount()`; the rest leak. Minor: tests run fast enough that
   no one notices, but `afterEach(() => wrapper?.unmount())` would be
   hygienic.

---

## 4. Over-engineering and refactor opportunities

- **`backend/schedules/api.py` is now 795 lines** and houses helpers that
  three other modules want (`_block_to_dict`, `_reject_oversized_body`,
  `VALID_CATEGORIES`, `_parse_time*`, `_validate_*`). It's time to extract a
  `backend/schedules/http.py` (the plan even suggested it) so `ai/views.py`
  doesn't have to reach into underscored names in another app's module.
  Importing `_block_to_dict` / `_reject_oversized_body` across apps is a
  yellow flag per Python convention.

- **`_apply_action` is ~95 lines of single-function branching** on
  `kind in {"add","move","remove","resize"}`. It reads fine today but will
  grow if Phase 5 adds more actions (e.g. `toggle_complete`, `reorder`).
  Factor each action into a small function with a signature like
  `apply_add(schedule, blocks_by_id, action, index) -> JsonResponse | None`
  and dispatch via a dict. Also sets you up to share the
  `_parse_time_or_error` / `_validate_block_times` helpers mentioned above.

- **Double import of `TimeBlock` in `service.py`** (module-level via
  `ai.schemas` → unused there, then local inside `run_command`). One
  module-level import suffices.

- **`useAI.ts` duplicates `apiFetch` logic** — extract. Low effort, high
  long-term hygiene.

- **`ai/prompts.py` embeds a reference to the frontend time constants via
  string duplication.** That's fine, but the lone TODO comment on Phase 5
  context is a better place to also note "update both sides if the day
  window changes." Already present at top of file — acceptable.

---

## 5. Style / consistency nits

- **Unused `from typing import Any` + `parsed: Any = json.loads(raw)`** in
  `service.py`. `Any` is redundant here; `parsed` is narrowed by the
  envelope validator one line later.

- **`AIParseError.__init__` defaults `raw_response_text=""`.** Every raise
  site passes `raw_response_text=raw`. The default is dead code.

- **`schemas.py` header comment is stale.** It says the service uses
  `response_format={"type":"json_object"}` — which is currently true but
  contradicts the plan. If you revisit §1.2 and switch to `json_schema`
  mode, update this comment.

- **`CommandBar.vue` focus shortcut doc.** The placeholder text hardcodes
  `"  (press / to focus)"`. It doesn't respect the user's keyboard locale,
  and the extra double-space inside the placeholder is unusual. Trivial.

- **`error-row` is clickable but has no keyboard affordance.** Users on
  keyboard-only navigation can't dismiss an error. Add
  `role="alert" tabindex="0" @keydown.enter="clearError" @keydown.space.prevent="clearError"`.
  A11y nit.

- **Inline styles in `CommandBar.vue`** use raw hex values (`#10b981`, `#ef4444`,
  `#60a5fa`, …) rather than the category color tokens the plan says already
  exist in `app.css` ("Reuse category-color tokens already defined"). Not
  functionally wrong, but misses the stated reuse. Worth a pass with the
  tokens you already have.

---

## 6. Summary

Functionally complete and the hard parts (atomic mutation, logging before
apply, error taxonomy, undo integration, DataCloneError avoidance) are all
correct. The top things worth addressing before Phase 5 starts:

1. Decide on Structured Outputs (§1.2) and either adopt them or update
   `schemas.py`'s header comment so future readers don't chase the plan.
2. Extract the shared schedules helpers (`backend/schedules/http.py`) and
   stop re-implementing validation primitives in `_apply_action` (§1.2, §4).
3. Add the Russian-command test + `AIParseError` integration test + explicit
   `add`-overlap test (§3.1).
4. Fix duration-preserving-move midnight wrap messaging (§2.1).
5. Require at least one time field for `move` / `resize` in
   `validate_action_shape` (§2.5) so the AI can't emit a silent no-op.

Everything else in this document is a nit or a documentation tweak.
