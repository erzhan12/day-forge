# 0059 — External code review trail

Feature: configurable AI quick-input suggestions (issue #154). Branch
`feature/0059-chat-suggestions`, reviewed vs `main` (`git diff main...HEAD`,
26 files, +1785/-70).

## Local staged review (/review-fix-loop-staged)

5 parallel category reviewers (code-quality, security, performance, testing,
documentation) over the branch diff. **0 CRITICAL, 0 WARNING**, 1 INFO
(`ChatSuggestionsEditor.vue` `moveRow` clears only `statusMessage` — cosmetic).
All plan invariants verified in code (single `normalize_chat_suggestions`
serialization path, DTO tuple-copy, `isinstance(list)` guard, read-side
trim-drop, runtime `?.` in `useChatSuggestions`, stable editor row-IDs vs chip
index-keys, `autosize` after `nextTick`, `onFinish`-clears-busy, server-side
caps, XSS-safe text interpolation, per-user isolation, additive nullable
migration). Result: ready.

## External review (/ext-code-review)

Engines: codex (gpt-5.6-sol) + cursor agent, read-only, over `git diff
main...HEAD` in the worktree. Criteria: `commands/code_review.md`. 1 iteration.

### Cursor — NO P1/P2
Full verification log: every plan claim MATCH (snake_case/flat `{theme,
chat_suggestions}` payload aligned end-to-end, no `{data:{}}` nesting). 5 P3s,
all non-blocking:
- RULES new-page example still inlines the payload dict instead of calling
  `ui_preferences_payload(prefs)`.
- PATCH response uses a parallel `_prefs_to_dict` rather than DTO +
  `ui_preferences_payload` (same keys today).
- first-access `get_or_create` test did not pin `chat_suggestions is None`.
- lone walrus `:=` in the trim-drop comprehension (`preferences.py:69`).
- `aria-label` "Move suggestion up 1" wording.

### Codex — 1 P2, 3 P3
- **P2 (REJECTED on verification)** — `ChatSuggestionsEditor.vue:42-50,134-138`:
  claimed the save watcher ignores refreshed server props then `onSuccess`
  installs the pre-reload payload, showing stale values on a concurrent
  update. Verdict: `onSuccess` deliberately installs the acting user's *own
  just-saved `payload`* — last-write-wins for the user whose PATCH is the
  latest committed write; the reload refreshes shared `page.props` so chips
  render server truth. The only masked case is a concurrent session writing in
  the millisecond window between this PATCH commit and the reload GET, showing
  the user their own saved value in the editor rows — the identical benign
  TOCTOU accepted for `DesignSelector`'s theme save and documented benign in
  `0059_PLAN.md` (§ reload note). Not data loss; a page reload shows truth.
- P3 (accepted gap) — no unmount guard on the post-await `router.reload`
  (mirrors existing `DesignSelector`; late completion after navigation issues a
  harmless `only:["ui_preferences"]` reload).
- P3 (accepted gap) — editor tests don't unmount, watchers persist across tests
  (suites green, 95/95).
- **P3 (FIXED)** — backend lacked an accepted 120-code-point emoji boundary
  test opposite the `"x"*121` rejection.

### Fixes applied (both cheap + clearly right)
- `backend/tests/test_user_preferences_api.py`: added
  `test_patch_accepts_120_code_point_emoji_boundary` (120 astral emoji = 120
  code points accepted, pinning Python code-point semantics vs UTF-16); pinned
  `chat_suggestions is None` on the first-access `get_or_create` row.

### Accepted non-blocking gaps (P3, not fixed)
Cursor's 5 P3s and Codex's 2 remaining P3s above — style/DRY/test-isolation
nits that mirror existing accepted patterns; none block merge.

## Verification (worktree)
- backend: `pytest backend/tests/test_user_preferences_api.py` → 71 passed;
  `ruff check backend/` → clean.
- frontend: `vitest run` (7 suites) → 95 passed; `vue-tsc --noEmit` → clean.

Result: SUCCESS — zero valid P1/P2, tests + lint green.
