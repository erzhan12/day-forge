# Feature 0012 — Manual Test: Rules in command + chat

Verifies the motivating LLM behavior end-to-end: the command bar and chat
endpoints should infer omitted defaults (duration, gap, start time) from
the user's active Rules instead of asking a clarifying question.

Automated tests cover **prompt wiring** (the rule strings reach the
provider). Whether the model **complies** with the rule on a given
turn is a real-LLM question and can only be checked manually — record
any model-output caveat below if it ignores the rule despite the prompt
being correctly wired.

## Setup

- [ ] Start the dev stack:
  - `uv run python backend/manage.py runserver 8006`
  - `cd frontend && npm run dev`
- [ ] Log in (use `createsuperuser` if no account exists).
- [ ] Open **Settings** and add an active Rule:
  > 25 min blocks, 10 min gap between blocks, start a new block 10 minutes after the latest block.
- [ ] Confirm the rule appears in the Settings list as `is_active=true`.
- [ ] On the target day, add at least one existing block (e.g. `09:00 — 09:25 work`) so the rule's "latest block" reference is non-empty.

> **UI routing note**: since feature 0007 the `CommandBar` UI posts to
> `POST /api/ai/schedules/<date>/chat/` (via `useChat`), NOT to the
> deprecated `/command/` endpoint. Test 1 (CommandBar) and Test 2 (chat
> panel) therefore both exercise `/chat/` end-to-end — they differ in UI
> layout, not in the backend path. The `/command/` endpoint's
> active-Rules wiring is covered by automated view/service tests; spot-
> check it manually with curl if you also need to verify the deprecated
> backward-compat surface (see "Test 4" below).

## Test 1 — Command bar with sparse command

- [ ] In the command bar, submit:
  > add standup and email
- [ ] **Expected**: the model returns two `add` actions with duration ≈ 25 minutes each and start times derived from the latest block + 10 minutes (then +10 minute gap between the two new blocks). No clarifying-question 200 with `actions: []`.
- [ ] **Wiring check**: tail the Django log; you should see `AIInteraction` logged with non-empty `actions_json`.
- [ ] **Caveat (record any failure here)**: if the LLM still asks for clarification despite the rule, capture the exact response.

## Test 2 — Chat with sparse request

- [ ] Open the chat panel (or refresh the page so the in-memory thread is empty).
- [ ] Send:
  > add standup and email
- [ ] **Expected**: same as Test 1 — actions applied with rule-derived durations/gaps; `ask` is `null` in the response payload.
- [ ] **Wiring check**: the response JSON should have `applied: true` and `blocks` populated.

## Test 3 — Negative: clarifying question still possible when rule does not cover the ambiguity

- [ ] Either disable the rule, or send a clearly off-rule request:
  > move my afternoon meeting
- [ ] **Expected**: a clarifying-question turn (`ask` non-null) is still allowed — the new behavior is "use rules when they apply", not "never ask for clarification".

## Test 4 — Backward-compat spot-check for the deprecated `/command/` endpoint (optional)

The UI no longer routes here, but external callers may. Verify rule
injection still works against `/command/` directly:

```bash
# Replace <sessionid> + <csrftoken> with values from your logged-in browser session.
curl -X POST http://localhost:8006/api/ai/schedules/$(date +%F)/command/ \
  -H 'Content-Type: application/json' \
  -H 'X-CSRFToken: <csrftoken>' \
  -b 'sessionid=<sessionid>; csrftoken=<csrftoken>' \
  -d '{"command":"add standup and email"}'
```

- [ ] **Expected**: `200` with `blocks` populated and `explanation`
  describing rule-derived defaults (25 min, 10 min gap). Behavior should
  match Test 1 since the rule-injection path is shared between the two
  endpoints via `_load_active_rules`.

## Wire-format spot-check (optional)

If you suspect a rendering bug, enable `LLM_DRAFT_CAPTURE_PROMPT_PATH`
for `generate-draft` to dump the rendered prompt to disk (see
`backend/ai/service.py`). The command and chat endpoints have no
equivalent capture switch; instead, temporarily add a log line in
`backend/ai/service.py` immediately after the `build_user_message(...)`
call (around line 219), e.g.:

```python
logger.info("Full prompt: %s", user_message)
```

Remove the line before committing — it dumps user PII to the dev log.
The trusted schedule-context message should contain:

```
Active rules (priority desc):
1. "25 min blocks, 10 min gap between blocks, start a new block 10 minutes after the latest block."
```

(JSON-encoded, `ensure_ascii=False`.) Russian rules render the same way
without Unicode escaping.

## Sign-off

- [ ] Test 1 passed
- [ ] Test 2 passed
- [ ] Test 3 passed (rule does not over-suppress clarifying questions)
- [ ] Test 4 passed (optional `/command/` backward-compat spot-check)
