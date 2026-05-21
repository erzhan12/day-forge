# Feature 0012 — Rules in AI Command and Chat Prompts

Issue: [#34](https://github.com/erzhan12/day-forge/issues/34), "AI command bar / chat ignore user-defined Rules (only \"Generate draft\" uses them)".

User-defined Rules from Settings are currently only included in the draft generation prompt. The one-shot command endpoint (`POST /api/ai/schedules/<date>/command/`) and multi-turn chat endpoint (`POST /api/ai/schedules/<date>/chat/`) should also load active rules and send them to the LLM so rules like "If I don't mention a new block duration, by default it is 25 minutes, and 10 minutes between them by default. If I don't mention a new block start time, start after 10 minutes of the latest block." can fill omitted duration, gap, and start-time defaults instead of forcing a clarifying question.

No frontend changes are required. The Rules CRUD UI already exists in Settings. No new env vars are required.

## Backend Prompt Changes

Update `backend/ai/prompts.py`.

- Add `_format_rules_section(rules) -> str`, a small shared formatter for active rules so command, draft, and chat render the same section:
  - Input: iterable of `templates_mgr.models.Rule`-like objects with `.text`.
  - Output header body lines matching the existing draft format:
    - Section header: `Active rules (priority desc):`
    - Items: `1. "<json-encoded rule text>"`
    - Empty state: `(no active rules)`
- Keep the existing JSON encoding with `ensure_ascii=False` so English and Russian rules remain readable while embedded quotes/newlines cannot reshape the prompt.
- Extend `build_user_message(schedule, blocks, now, user_command, rules)`:
  - Preserve the existing schedule date, current local time, existing blocks, and `User command:` sections.
  - Insert the rules section before `User command:` so the model sees defaults before interpreting the user's request.
- Extend `build_chat_user_message(schedule, blocks, now, rules)`:
  - Preserve the existing schedule date, current local time, and existing blocks sections.
  - Append the rules section to the schedule context before `service.run_chat` concatenates the untrusted transcript.
- Keep `build_draft_user_message(schedule, template, history_schedules, rules, now)` behavior unchanged from the caller's perspective, but route its rule rendering through the shared formatter to avoid drift.

Update the system prompts in `backend/ai/prompts.py`. Do not only append a new rule; revise the existing ambiguity rules so they do not contradict rule-default behavior.

- In `SYSTEM_PROMPT`, update the current ambiguity rule to clarify that missing details should produce zero actions only when active rules cannot supply the missing detail. The intended behavior is: `Respect every active rule. Use rules to fill in defaults (duration, gap, start time) the user omitted, instead of asking for clarification.`
- In `SYSTEM_PROMPT_CHAT`, update hard rule 2 so chat asks one clarifying question only when current blocks, prior transcript, latest user turn, and active rules still leave the intended mutation unresolved.
- Do not change `SYSTEM_PROMPT_DRAFT`; it already says "Respect every active rule" and explains priority precedence.

## Backend Service Changes

Update `backend/ai/service.py`.

- Change `run_command(user_command, schedule, blocks, now)` to accept `rules`:
  - Proposed signature shape: `run_command(user_command, schedule, blocks, rules, now)`.
  - Pass `rules` to `build_user_message`.
  - Leave input validation, provider call settings, response parsing, and action validation unchanged.
- Change `run_chat(messages, schedule, blocks, now)` to accept `rules`:
  - Proposed signature shape: `run_chat(messages, schedule, blocks, rules, now)`.
  - Pass `rules` to `build_chat_user_message`.
  - Keep the latest user turn as its own user-role message.
  - Keep prior transcript flattening via `serialise_prior_turns(messages[:-1])`; rules belong in the trusted server-built schedule-context message, not inside the client-supplied transcript.
- Leave `run_draft(schedule, template, history_schedules, rules, now)` unchanged except for any import/helper adjustments caused by prompt formatter extraction.

## Backend View Changes

Update `backend/ai/views.py`.

- Add an async helper in `backend/ai/views.py` to keep the three endpoint queries aligned:
  - `_load_active_rules(user)` returns `[r async for r in Rule.objects.filter(user=user, is_active=True).order_by("-priority")]`.
- In `ai_command`:
  - After resolving `user`, `schedule`, `current_blocks`, and `now`, load active rules with `_load_active_rules(user)`.
  - Pass the rules list into `run_command`.
  - Keep rate limiting, audit logging, action application, and `mark_active_on_edit` behavior unchanged.
- In `ai_chat`:
  - After resolving `user`, `schedule`, `current_blocks`, and `now`, load active rules with `_load_active_rules(user)`.
  - Pass the rules list into `run_chat`.
  - Keep validation order intact: malformed chat bodies must still return before schedule creation and before rate-limit consumption.
  - Keep rate-limit consumption before the LLM call, as it is today.
- In `ai_generate_draft`, replace the inline active-rule async query with `_load_active_rules(user)` and keep the existing ordering and filtering behavior unchanged.
- Do not query inactive rules.
- Do not load another user's rules.
- Do not add a migration.

## Tests

Update prompt tests. Prefer a new pure-function test file, `backend/tests/test_ai_prompts_command_chat.py`, for command/chat prompt coverage instead of scattering these assertions only through service tests.

- Add tests for `build_user_message` in `backend/tests/test_ai_prompts_command_chat.py`:
  - Assert the prompt includes `Active rules (priority desc):`.
  - Assert multiple rules render in priority order when the caller passes them in that order.
  - Assert inactive-rule filtering is handled by the view/query layer, not by the prompt builder.
  - Assert the JSON-encoded user command section still exists and remains after the rules section.
- Add tests for `build_chat_user_message` in `backend/tests/test_ai_prompts_command_chat.py`:
  - Assert the prompt includes `Active rules (priority desc):`.
  - Assert a rule appears in the schedule-context message that `run_chat` sends before the untrusted transcript.
- Extend `backend/tests/test_ai_prompts_draft.py` with a parity assertion for `_format_rules_section`, or a section snapshot asserting the draft prompt's `Active rules (priority desc):` output is unchanged by the helper extraction.

Update service tests.

- In `backend/tests/test_ai_service.py`, update every `run_command(...)` call for the new signature.
- Add a prompt-wiring assertion in the successful command test that a supplied rule appears in the provider's user message.
- In `backend/tests/test_ai_service_chat.py`, update every `run_chat(...)` call for the new signature.
- Add a prompt-wiring assertion that the provider receives the rule in the first user-role context message, while the latest user turn remains a separate final user-role message.

Update view tests.

- In `backend/tests/test_ai_views.py`, update monkeypatched `run_command` helpers to accept the new `rules` argument.
- Add an async view test that creates active and inactive `Rule` rows for the authenticated user, plus an active rule for another user, then asserts `ai_command` passes only the authenticated user's active rules ordered by `-priority`.
- In `backend/tests/test_ai_views_chat.py`, update monkeypatched `run_chat` helpers to accept the new `rules` argument.
- Add the same active/inactive/cross-user assertion for `ai_chat`.
- Existing draft tests should remain green; add no new draft behavior unless helper extraction requires small assertion updates.

## Documentation

- Update `RULES.md` to note that command, chat, and draft all inject active rules into their server-built prompt context, and that filtering active/user-owned rules stays in the view/query layer.
- Update `docs/api.md` command and chat endpoint descriptions to note that active Rules are applied server-side. This is a behavioral note, not a request/response contract change.
- Update module docstrings in `backend/ai/prompts.py` and `backend/ai/service.py` if their endpoint/signature descriptions still imply command/chat prompts only use schedule blocks and user text.

## Manual Verification

Create a short manual test document for the motivating LLM behavior, e.g. `docs/features/0012_MANUAL_TEST.md`.

- Configure an active rule: `25 min blocks, 10 min gap, start 10 min after latest block`.
- On a schedule with an existing latest block, use the command bar with a sparse command such as `add standup and email`.
- In chat, send the same sparse request.
- Expected behavior: the model infers default duration, gap, and start time from the active rule instead of asking a clarifying question.
- Record any real-LLM caveat if the model output is valid JSON but does not fully follow the rule, since automated tests prove prompt wiring but not model compliance.

## Verification

Run focused backend tests:

- `uv run pytest backend/tests/test_ai_prompts_draft.py backend/tests/test_ai_prompts_command_chat.py backend/tests/test_ai_service.py backend/tests/test_ai_service_chat.py backend/tests/test_ai_views.py backend/tests/test_ai_views_chat.py -v`

Run the backend lint:

- `uv run ruff check backend/`
