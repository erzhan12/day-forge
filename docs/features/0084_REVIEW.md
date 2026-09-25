# 0084 — Code review (resolve AI category labels to slugs, issue #209)

Scope: `git diff d17a363..HEAD` on `claude/modest-shannon-5e1jkx` (commits
`aaa9be1` + `60cf8e1`). Criteria: `commands/code_review.md` (plan conformance,
bugs, data alignment, over-engineering, style, tests). Reviewed against the
approved plan `docs/features/0084_PLAN.md`.

Severity scheme (same as 0083's trail): **P1** must fix before merge (behaviour
or security bug), **P2** should fix, **P3** nit / follow-up.

**0 P1, 2 P2, 9 P3.** No behaviour bug found in the shipped paths. Both P2s are
about debuggability and test strength around the two index spaces.

## Findings

| # | Sev | Location | Finding |
|---|---|---|---|
| 1 | P2 | `backend/ai/service.py:464-468` | `error_detail` indexes actions in neither `raw` nor `actions_json` |
| 2 | P2 | `backend/tests/test_ai_views_chat.py:663` (`TestCategoryAsk`) | The view tests never check the normalised vs original index spaces. The mixed-turn test passes trivially |
| 3 | P3 | `RULES.md:164`, `RULES.md:166` | Hard rule 12 is credited to the wrong feature, and the "fourth such string" sentence names the wrong string |
| 4 | P3 | `RULES.md:166`, `docs/api.md:453` | "always paired with the category ask" is too strong: the replay guard suppresses the ask |
| 5 | P3 | `docs/api.md:542`, `backend/ai/views.py:92-97`, `:1003-1005` | The echo example ("an unresolved category label") is wrong; `AIParseError` is described as schema-only |
| 6 | P3 | `backend/ai/category_resolution.py:159,174,189` | DEBUG logs write an unvalidated, model-supplied `task_id` with `%r` |
| 7 | P3 | `backend/ai/views.py:100-104` | The `_MAX_ERROR_DETAIL_LEN` comment says the cap "bounds" a 20-action error list. The worst case is 7,711 chars |
| 8 | P3 | `backend/ai/prompts.py:166-167` | Hard rule 4's "Default to other if unclear" still applies to `update`, which invites the recategorisation to the sink that decision 3 forbids |
| 9 | P3 | `backend/ai/category_resolution.py:1-22`, `service.py:202-215`, `views.py` | Comment and docstring bloat, `§` plan references in code, and a self-contradicting module docstring |
| 10 | P3 | `backend/ai/replay_guard.py:97-106` | `truncate_title(limit=...)` has no caller that uses `limit`, and the docstring has a broken RST literal |
| 11 | P3 | tests | Unit-test gaps: `_build_category_ask`, the draft envelope guard, the no-log-of-value rule, and a custom catalog through `run_chat` |

### 1 (P2): `error_detail` uses the normalised index, which appears nowhere in the audit row

`run_chat` validates `normalized_actions` and formats errors as
`action[{idx}]` using the **post-normalisation** index (`service.py:464-468`).
On failure, `_log_chat_failure` stores `actions_json = []` and `raw` in the
**model's** index space. When a category-only update is dropped ahead of an
invalid action, `error_detail` points at the wrong action in `raw`.

Evidence: a scratch test (`scratchpad/rev/test_rev0084.py::test_error_index_space`).
The model returned
`[{update task 7, changes: {category: "рабочая"}}, {add, category: "work"} /* no title */]`,
and the resulting `AIParseError` was
`AI chat response failed action validation: action[0]: add action requires 'title'`.
The invalid add is at `raw.actions[1]`. The plan's "one index space"
principle (§2) exists to prevent exactly this mix-up, and `error_detail`
exists only for debugging.

Fix: add `original_indices: tuple[int, ...]` to `NormalizeResult`, one entry
per returned action, and format as `action[{original_indices[idx]}]`. The
failure row has no normalised list, so the model's index is the right one.
Otherwise, state in `docs/api.md` that `error_detail` indices refer to the
post-normalisation list.

### 2 (P2): the index-space wiring between service and view has no test

Every `TestCategoryAsk` test mocks `ai.views.run_chat` with a hand-built
`AIChatResult`, so the service→view hand-off is never exercised. That
hand-off covers `parsed_actions` normalisation, `original_index` vs
`action_index`, and `actions_json` contents. In
`test_mixed_turn_add_applies_and_category_ask_shown` the dropped update sits at
`original_index=0` and the one surviving add at `action_index=0`, so both
index assertions would also pass if the two spaces were swapped or merged.

Evidence: a scratch end-to-end test (`scratchpad/rev/test_rev_views.py`) runs
the real `run_chat` against a fake provider returning
`[add "A" (label "Work"), category-only update "рабочая", add "B" ("рабочая")]`.
It confirms the current code is **correct**:

- outcomes `action_index` = `[0, 1]`;
- `actions_json` has 2 entries with `work` and `other`;
- the audit has `unresolved_categories = [{"original_index": 1, "dropped": true}]`;
- the ask names "Meeting".

Nothing in the repo pins this, though.

Fix: add one view test that patches `ai.service._get_client` rather than
`run_chat`. Put the dropped update in the middle of three actions and assert
`[o["action_index"] for o in outcomes] == [0, 1]`,
`len(actions_json) == 2` and `unresolved_categories[0]["original_index"] == 1`.

### 3 (P3): RULES.md credits Hard rule 12 to the wrong feature and garbles the string count

- `RULES.md:166`: "(feature **0083's** Hard rule 12 answers it by
  coreference)". Hard rule 12 was added by **0084** (this diff,
  `prompts.py:225`). Fix: "(Hard rule 12, feature 0084, answers it…)".
- `RULES.md:164`: the sentence keeps the guard `ask`/`explanation` as its
  subject and changes "the third such string" to "the fourth such string…
  alongside the feature 0084 category ask". That now calls the *guard*
  strings the fourth, when the category ask is. The plan (§6) said to name the
  category ask as the fourth. Fix, for example: "…the third such string; the
  feature 0084 category ask (`Which category should…`) is the fourth."

### 4 (P3): "always paired with the category ask" is too strong

`RULES.md:166` says "Either drop is **always** paired with the server-owned
category ask", and `docs/api.md:453` says "the response **always** carries a
server-owned `ask`". In the code (`views.py:1364-1372`), if a kept sibling
`add` trips the replay guard, `_replay_guard_response` returns the guard's ask
and no category ask. The plan (§4) accepts this. The RULES text mentions only
the losing-to-a-resolution-ask exception, and `docs/api.md:506-508` does the
same. Fix: add "…or the replay guard fires first" to both, with the audit
`unresolved_categories` as the durable record.

### 5 (P3): wrong echo example; `AIParseError` described as schema-only

- `docs/api.md:542`, the `views.py:92-97` comment and the draft comment at
  `views.py:1003-1005` all give "an unresolved category label" as an example
  of model text echoed in the validation message. It isn't one: the category
  errors (`schemas.py:158`, `:256`) print only the *allowed* set, never the
  rejected value. After 0084 an unresolved category no longer raises at all,
  except for a guard-failed category-only update, and its message still
  doesn't echo the value. The real echo sources are the `type` value
  (`schemas.py:94`) and unknown key names.
  Fix: use "e.g. an unknown action `type` or JSON key".
- `docs/api.md:542` and `:597` say "On a schema-validation failure
  (`AIParseError`)", but invalid JSON and envelope failures are also
  `AIParseError` and also get the generic detail. Fix: "On any JSON /
  envelope / schema-validation failure (`AIParseError`)".
- `docs/api.md:479` refers to itself: "This is `docs/api.md`'s standard
  partial-apply shape". Fix: "This is the standard partial-apply shape
  (see above)".

### 6 (P3): DEBUG logs can echo model-supplied text through `task_id`

`_normalize_update` logs `task_id=%r` on the rewritten and dropped-field
paths. Those paths run **before** any validation, so `task_id` can be any
model-supplied value. Evidence:
`scratchpad/rev/test_rev0084.py::test_debug_log_task_id_echo` captured
`AI category unresolved (type=update, task_id='user wording рабочая', outcome=dropped_field)`.
The logging is DEBUG-only, and the plan's rule concerns the category *value*,
so this is low risk. Still, it goes against the "no model-supplied text in
app logs" reasoning that §4 applies to the draft log. Fix: log
`task_id if is_plain_int(task_id) else "<invalid>"`. `is_plain_int` is
already in `ai.schemas`.

### 7 (P3): `_MAX_ERROR_DETAIL_LEN` does not bound a 20-action error list

The comment at `views.py:100-103` says 2,000 chars "bounds a worst-case
~20-action per-action error list". Evidence
(`scratchpad/errlen.py`): 20 updates, each with a bad category and an
off-grid time, against 8 categories with 32-char slugs
(`MAX_CATEGORIES`, `Category.slug max_length=32`), produce a 7,711-char
message. The cap is still a safe cap, but with the default catalog it also
cuts off the tail errors, which are the useful part. Fix: reword the comment
to "caps…; long lists are truncated". Optionally prefer a count plus the
first N errors.

### 8 (P3): Hard rule 4 still tells the model to default updates to `other`

Decision 3 is "never quietly recategorise an existing block to the sink", and
the server enforces it for *unresolvable* values. But Hard rule 4
(`prompts.py:163-167`) still ends with 'Default to "other" if unclear', and it
applies to `update` as well as `add`. A model that follows the rule on
`рабочая` and emits `"other"` gets a clean, silent recategorisation that the
normaliser cannot tell apart from a real request. This behaviour predates
0084, and the plan kept the sentence, so it's a follow-up rather than a
conformance gap. Fix (small prompt edit, append-only): "…Default to
"{sink_slug}" if unclear **on an add**; on an update, omit category (or ask)
rather than defaulting."

### 9 (P3): comment and docstring bloat, plan references in code

The change adds about 1,264 lines, and much of that is prose.

- `category_resolution.py` is 242 lines around roughly 90 lines of logic.
- The module docstring contradicts itself. It says "Pure module — no Django
  settings", then explains that it reads settings through `ai.schemas`. It
  also says an unresolved value "is silently normalised", but the feature's
  point is that unresolved updates are *not* silent.
- `_category_context` has a 12-line docstring for 3 lines of code.
- The `run_draft` block has 14 comment lines around one `if`.
- `views.py` grows from 1,316 to 1,434 lines, about 60 of them comments.
- Code comments cite plan sections ("§4", "§ below", "plan §2"). No other
  `backend/ai/*.py` module does this outside one-off mentions, and those
  references rot when the plan is edited.

Fix: cut the module docstring to purpose plus invariants, drop the `§`
references, and shorten the `_category_context` and `run_draft` comments to
one or two lines each.

### 10 (P3): `truncate_title` polish

- Every caller uses the default `limit`, so the parameter isn't needed yet.
- The docstring splits an RST literal across lines ("``\n    build_guard_ask``").

Fix: drop `limit` (or keep it and fix the literal), and write
`` ``build_guard_ask`` `` on one line.

### 11 (P3): unit-test gaps

- `_build_category_ask` is never tested directly, unlike
  `_build_resolution_ask`, which is imported and unit-tested. Missing cases:
  the `"that block"` fallback (unknown `task_id`), title truncation, first
  record only, and catalog-order labels for a custom catalog. The truncation
  path was checked only in a scratch test.
- The `run_draft` guard (`isinstance(parsed.get("actions"), list)`) has no
  test showing that a malformed envelope (`"actions": "x"` / missing) still
  raises the envelope `AIParseError` and not `AttributeError`.
- There is no `caplog` assertion that the unresolved value never reaches the
  logs (plan §1), and none that the draft WARNING line carries no detail
  (plan §4).
- There is no `run_chat` test with a real per-user catalog passed as
  `categories=`, for example `("work", "Работа")` with value `работа` →
  `work`. That would show `_category_context` feeds the prompt and the
  normaliser the same pairs.
- `test_issue_209_repro_time_and_category_update_no_longer_raises` does not
  pin `original_index`.

## Verified correct

- **§1 module.** `resolve_category` checks the exact slug, then a casefolded
  slug or stripped label, first catalog match wins, else `None`, and returns
  `None` for non-`str` input. `normalize_action_categories` is pure: it builds
  new dicts and never mutates the input (tested).
  - Add: absent or `null` category → sink; a non-str value is left untouched;
    add fallbacks are never recorded.
  - Update: resolved → rewritten; unresolved with other changes → key removed
    and a `dropped=False` record; category-only → dropped with a
    `dropped=True` record.
- **S4 drop guard.** The drop needs `validate_action_shape(action, allowed | {value}, allow_untimed_add=True) == []`
  and `task_id in known_task_ids`. Otherwise the action stays untouched and
  still fails with a 502. Also checked:
  - `True` and `7.0` task ids fail `is_plain_int` inside the guard, so the
    set-membership coercion cannot sneak them through.
  - `placement_direction` on a category-only update fails the guard and
    returns 502.
  - An unknown key inside `changes` takes the kept path and still fails
    validation.
- **The unresolved value never leaks.** It is not logged (the logs carry
  type, `task_id` and outcome, but see #6), and it does not appear in the
  category ask, the HTTP body or the audit `unresolved_categories` (asserted
  in the view test). It exists only in `raw`.
- **§2 service.**
  - `_category_context` is shared by the prompt and the normaliser. Passing
    `_DEFAULT_CATEGORIES` instead of `None` renders the same text, because
    `_category_text` does `categories or _DEFAULT_CATEGORIES`.
  - The `allowed_categories` check is unchanged.
  - `run_chat` validates and returns the normalised list, with
    `known_task_ids = {b.id for b in blocks}`.
  - `AIChatResult.unresolved_categories` defaults to `()`, so positional test
    construction still works.
  - The draft normalises behind the envelope guard, with an empty
    `known_task_ids`, and drops the records.
  - `raw_response_text` keeps the model's original wording.
- **§3 prompt.**
  - The `update` description has the slug sentence, and chat and draft rule 4
    both say "emit the SLUG".
  - Hard rule 12 is appended at line 225 with the "AND the latest user turn
    answers that question" scoping and the "map via labels" sentence.
  - Rules 1-11 have the same numbers as at `d17a363` (diffed).
  - The rule 2(iii) and rule 11(a) parentheticals were amended in place.
  - `(other than asking what to add)` still appears exactly 2 times.
- **§4 view.**
  - The all-dropped branch comes after `result.ask is not None`, before
    chit-chat and before the replay guard. It calls `_mark_success`, uses
    `GUARD_EXPLANATION`, sets `outcomes: []` and takes titles from the
    pre-apply `current_blocks`.
  - The apply branch uses `ask = _build_resolution_ask(...) or _build_category_ask(...)`
    with post-apply titles.
  - The audit payload key order is `transcript_sha256, turn_count, [unresolved_categories], [error_detail], raw, [error_class]`,
    so both new keys survive front truncation (tested).
  - Every value in the payload is a JSON int or bool.
  - `AIParseError` gets the generic `AI_PARSE_ERROR_DETAIL` with 502 in both
    chat and draft. Other `AIError` classes keep `str(e)`.
  - `error_detail` is set only for `AIParseError` and capped at 2,000 chars.
  - The draft logs a WARNING without detail and the full message at DEBUG only.
- **End to end** (scratch test through the real `run_chat` and view): the
  all-dropped turn returns 200 with `"Nothing was changed."`, the category
  ask, and the title truncated to 60 chars + `...`. The mixed three-action
  turn is described under #2.
- **Intended behaviour changes, per plan.** A chat or draft `add` without a
  `category` now defaults to the sink instead of returning 502. This is why
  one `TestParsing` parametrised case switched from "missing category" to
  "missing title". The schema layer is unchanged, so
  `test_ai_schemas_draft.py::test_update_invalid_category_rejected` stays.
- **§5.** No frontend or Playwright code asserts on the old 502 text (grep).
  `useChat.ts:211` sets `is_ask` from `ask !== null`, so the category-ask
  answer turn bypasses `implicit_add` and the replay guard as the plan
  intends.

## Verification

- `uv run pytest backend/tests/ -q` → 1571 passed (the 8 AI test modules this change touches: 352 passed).
- `uv run ruff check backend/` → clean.
- Scratch tests (outside the repo): `test_rev0084.py` (#1, #6),
  `test_rev_views.py` (the two end-to-end view cases), and `errlen.py` (#7).

## Verdict

**Approve with follow-ups.** The plan is implemented section by section with
no behaviour bugs. The S4 guard, the no-leak rules, the branch order, the ask
precedence, the audit key order and the generic 502 detail all match the plan.
Before merging, fix the two P2s: model-index `error_detail`, and one
end-to-end view test that separates the two index spaces. The doc fixes in
#3–#5 are one-line edits. The rest can be batched or left.
