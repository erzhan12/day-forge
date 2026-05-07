# 0007 Review — Multi-turn AI Chat Panel

## Findings

No blocking or actionable findings found in the current implementation.

## Notes

- The earlier review findings are addressed:
  - non-object JSON roots return 400 before schedule creation or rate-limit consumption.
  - the explanation cap is now documented as the canonical shared `LLM_MAX_EXPLANATION_CHARS`.
  - `ai.E001` documents all AI rate-limit buckets.
  - chat privacy/PII disclosure is present in `CLAUDE.md` and `.claude/rules/project.md`.
  - `ai-chat-clarifying-question.mjs` now asserts turn-2 apply behavior and DB persistence when turn 1 produced an `ask`.
  - `ai-chat-date-change-resets-thread.mjs` now uses same-document DateNavigator navigation and checks a reload marker.
- The forged-assistant Playwright script is explicitly moved out of PR A in the plan. The security invariant is covered by `backend/tests/test_ai_service_chat.py::TestUntrustedTranscript::test_assistant_role_never_forwarded`, which directly inspects the SDK `messages[]` passed to `client.chat.completions.create`.
- `ChatPanel.vue` / `useMediaQuery` remain intentionally out of scope for PR A.

## Verification

- `uv run pytest -q backend/tests/test_ai_service.py backend/tests/test_ai_service_chat.py backend/tests/test_ai_views_chat.py backend/tests/test_checks.py` — 67 passed.
- `cd frontend && npm test -- --run CommandBar.test.ts useChat.test.ts useAI.test.ts Schedule.test.ts` — 52 passed.
- `uv run ruff check backend/` — passed.
- `cd frontend && npx vue-tsc --noEmit` — passed.
