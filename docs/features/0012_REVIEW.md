---
name: "0012 rules in command and chat - implementation review"
description: Code review against docs/features/0012_RULES_IN_COMMAND_AND_CHAT_PLAN.md (final re-review)
date: 2026-05-21
---

# Feature 0012 — Code Review (final)

## Findings

No blocking or actionable issues remain.

The two cosmetic nits from the prior re-review are resolved:

- **`docs/api.md`** — Deprecation callout now names `POST /api/ai/schedules/{date}/chat/` directly instead of “endpoint below”; blockquote documents the feature-0007 chat-section gap and cross-references active-Rules injection via `_load_active_rules`.
- **`0012_MANUAL_TEST.md`** — Sign-off checklist now includes optional Test 4.

## Confirmed Good

### Plan implementation

- **`_format_rules_section`** shared across command, chat, and draft.
- **`build_user_message` / `build_chat_user_message`** inject rules in correct section order.
- **`SYSTEM_PROMPT` / `SYSTEM_PROMPT_CHAT`** ambiguity rules revised; **`SYSTEM_PROMPT_DRAFT`** untouched.
- **`run_command` / `run_chat`** accept `rules`; chat message-array shape unchanged.
- **`_load_active_rules(user)`** shared by all three AI views; filtering tested on command, chat, and draft view layers.
- **`RULES.md`**, **`docs/api.md`**, and **`0012_MANUAL_TEST.md`** all aligned with the implementation.

### Security / data alignment

- Active/user-owned filtering stays in the view layer; prompt builders render caller-supplied iterables without re-querying.
- Chat rules stay in the trusted schedule-context message, not the untrusted transcript.
- No request/response contract changes.

### Tests

| Area | Coverage |
|------|----------|
| `test_ai_prompts_command_chat.py` | Formatter, section order, unicode/quotes, empty rules |
| `test_ai_prompts_draft.py` | Shared formatter parity |
| `test_ai_service.py` | Rule in provider user message (command) |
| `test_ai_service_chat.py` | Rule in first user context message only |
| `test_ai_views.py` | Command view rule filtering |
| `test_ai_views_chat.py` | Chat view rule filtering |
| `test_ai_views_draft.py` | Draft view rule filtering |

## Verification Run

- `uv run pytest backend/tests/test_ai_prompts_draft.py backend/tests/test_ai_prompts_command_chat.py backend/tests/test_ai_service.py backend/tests/test_ai_service_chat.py backend/tests/test_ai_views.py backend/tests/test_ai_views_chat.py backend/tests/test_ai_views_draft.py -q` — **132 passed**
- `uv run ruff check backend/` — **passed**

## Manual verification status

Automated tests prove **prompt wiring**. **Model compliance** (inferring 25 min / 10 min gap from “add standup and email”) remains a real-LLM manual check per `0012_MANUAL_TEST.md`. Sign-off checkboxes are still open.

## Verdict

**Approve — ready to merge.** Implementation matches the plan; tests and lint are green; documentation and manual-test guidance are complete for this feature's scope. A full standalone `/chat/` section in `docs/api.md` remains a future feature-0007 follow-up, not a blocker for 0012.
