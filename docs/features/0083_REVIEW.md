# 0083 — Code review (chat must not replay the previous request, issue #219)

## Local staged review (`/review-fix-loop-staged`)

1 iteration, 5 parallel reviewers (code quality, security, performance, testing,
documentation). **0 critical, 0 warnings, 0 info.** Security reviewer confirmed:
`is_ask` / `is_error` never reach the provider (`serialise_prior_turns` reads only
`role` / `content`), the implicit-add rewrite touches only the LLM-bound copy of
the latest turn, new regexes have no catastrophic-backtracking shape, and the
guard's warning log carries ids only (no titles or message text).

## External review trail (`/ext-code-review`, codex gpt-5.6-sol + cursor agent)

Criteria: `commands/code_review.md`. 4 iterations (max 4).

| Iter | Engine | Finding | Verdict | Fix |
|---|---|---|---|---|
| 1 | codex P1 / cursor P2 | `try again` after an error bubble became `add try again`, breaking the retry flow | ACCEPT | `implicit_add` skips when `messages[-2]` has `is_error`; retry words (`try`, `retry`, `repeat`, `повтор`, `again`, `ещё раз`) count as commands |
| 1 | codex P2 | `thanks!`, `What's next` (no `?`), `Good morning` got an `add` prefix | ACCEPT | edge-punctuation-insensitive short replies, greetings added, question starter = leading letter run |
| 1 | codex P3 / cursor P3 | guard warning log lacked user / schedule ids | ACCEPT | `_replay_guard_response` logs `user`, `schedule`, `interaction`, indices |
| 1 | cursor P3 | whole-turn abort test did not pin outcome details | ACCEPT | asserts `explanation`, `task_id`, `skipped_fields` for both outcomes |
| 1 | codex P3 | split `test_ai_views_chat.py` into a new module | REJECT | existing per-view test module pattern; file was already large before this change |
| 2 | codex P2 / cursor P3 | `putting`, `setting`, `tried`, `cancelled`, `made` not recognised as commands | ACCEPT | explicit `_EN_IRREGULAR_FORMS` list + test |
| 2 | cursor P3 | `docs/api.md` `is_error` note omitted 400 | ACCEPT | note lists every failure path |
| 3 | codex P2 | `reschedule` / `postpone` (and the default chip "Plan my remaining day") got an `add` prefix | ACCEPT | edit / planning verbs (EN + RU stems) + test covering the three default suggestion chips |
| 3 | cursor P3 | service test did not assert the latest turn stays out of the prior flatten | ACCEPT | `"Notes" not in prior_context` |
| 4 | codex P2 | read-only imperatives (`list today's blocks`, `покажи мои блоки`) became adds | ACCEPT | `list, show, tell, explain, summarize, describe` + `покаж, расскаж, объясн, напомн`; `check` / `review` deliberately excluded (common block titles) + test |
| 4 | cursor P3 | duplicated clause in `docs/api.md` `is_ask` row | ACCEPT | reworded |
| 4 | codex P3 | guard ask → correct answer fails → retry is flagged again (one extra ask) | ACCEPTED GAP | rare chain; same class as plan Risks R9 |

Totals: 14 raised, 12 accepted (12 fixed), 1 rejected, 1 accepted gap.

Accepted gap (not fixed): user-customised chat suggestion chips (up to 8, free
text) that contain no command verb are sent with an `add` prefix.

## Final verification

- `uv run pytest backend/tests/ -q` → 1528 passed
- `uv run ruff check backend/` → clean
- `cd frontend && npm test` → 1113 passed; `npx vue-tsc --noEmit` → clean (frontend unchanged since)
- Live browser test on the worktree with the real model: `add Momentum` → `Notes` adds `Notes` with no question and no `Momentum[2]`; `Обед` adds «Обед»; a repeat `add Momentum` adds `Momentum[2]` per the user's Rule.
