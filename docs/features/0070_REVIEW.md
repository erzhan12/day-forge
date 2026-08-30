# 0070 — Per-Request Timezone for AI Placement/Prompt — Review Trail

Fix #182: AI server-side `now()` used UTC not the user's timezone, so untimed AI-chat adds landed in the past for non-UTC users. Fix = per-request `client_tz`.

## Local staged review (review-fix-loop-staged)

- Iterations: 1/3. Criticals: 0. Warnings: 0. Info: 0.
- Two reviewers (quality+security; perf+testing+docs) both clean. Verified untrusted `client_tz` cannot escape the safe fallback (no path traversal, no 500) and the tz-discriminating tests are genuinely fail-first.
- Result: Ready to commit ✅

## External review trail (ext-code-review)

- Engines: codex (gpt-5.6-sol) + cursor agent, read-only.
- Iterations: 1/10.
- Findings: raised 8 (all P3), accepted-for-fix 0, rejected 0 (P3s non-blocking), P3-ignored 8.
- Both engines returned **NO P1/P2 FINDINGS**. Cursor produced a full verification log — every plan invariant MATCH (resolver exception breadth + UTC last-resort; never-400/500; fresh-under-lock apply floor with only tz changed; `client_tz` threaded into `_apply_actions_sync`; snake_case wire field; fail-first tz tests).
- P3s recorded as accepted gaps (not fixed — non-blocking, tests already fail-first + green):
  1. Freshness test's `localtime` fake ignores args (re-localizing a stale prompt instant would still pass).
  2. Draft invalid-encoding test asserts 200 but does not capture `run_draft`'s `now` to lock the UTC fallback.
  3. Frontend chat tz test uses `objectContaining({client_tz})` and does not lock `messages` as a sibling.
  4. Draft test replaces `views.json` with a 2-attr `SimpleNamespace` (indirection).
  5. `raising=False` on the OSError-arm `ZoneInfo` patch (note: the patched fn explicitly raises `OSError`, so the arm IS exercised — cursor's concern here is inaccurate).
  6. Last-resort spelled `datetime.timezone.utc` while test asserts `is datetime.UTC` (same singleton on 3.14).
- Verification: backend focused 213 passed, full suite 1287 passed, ruff clean, frontend 1029 passed, vue-tsc clean (from implementation run; no code changed during review).
- Result: SUCCESS.

```
ext-code-review trace
  scope: 10 files
  engines: both (codex + cursor)
  iterations: 1/10
  findings: raised 8, accepted 0 (fixed 0), rejected 0, P3-ignored 8
  verification: 1287 backend + 1029 frontend passed, lint clean
  result: SUCCESS
```
