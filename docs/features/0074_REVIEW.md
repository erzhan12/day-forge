# 0074 — External code review trail

Feature: chat system prompt gains a "higher-priority rules take precedence on
conflict" clause (Hard rule 2) so a high-priority default rule beats a
lower-priority ask/clarify rule. Branch `feature/0074-chat-rule-precedence`.
Scope: `backend/ai/prompts.py` + `backend/tests/test_ai_prompts_command_chat.py`.

Engines: **codex** (`gpt-5.6-sol` — the model id passed to the local OpenAI Codex
CLI for this repo's review runs; read-only sandbox). **cursor** (`agent`) dropped —
empty output all session.

## Iteration 1 — codex: NO P1/P2 FINDINGS

| # | Sev | Finding | Verdict |
|---|-----|---------|---------|
| 1 | P3 | Precedence tests assert disconnected keywords but never that the *higher*-priority/earlier-listed rule wins — a reversed clause could still pass | **FIXED** — added directional assertions: `"obey the higher-priority"` and the contiguous `"higher-priority rule that supplies a default value"` + `"takes precedence and overrides a lower-priority"`. A reversed statement now fails. |

## Verification after fix

- `uv run pytest backend/tests/test_ai_prompts_command_chat.py -q` → 20 passed
- `uv run pytest backend/tests/ -q` → 1326 passed (pre-fix; this round only tightened test assertions in one already-passing file)
- `uv run ruff check backend/` → clean

## Trace

```
ext-code-review trace
  scope: 2 files (prompts.py + test)
  engines: codex (cursor dropped)
  iterations: 1/3
  findings: raised 1, accepted 1 (fixed 1), rejected 0, P3-ignored 0
  verification: 1326 backend passed, ruff clean
  result: SUCCESS (zero valid P1/P2)
```
