# Feature 0071 — Review Trail

Persist per-user IANA timezone in `UserScheduleSettings` as the sole source of
server-side `now()` for AI draft/chat/placement, plus a one-time dismissible
browser-timezone-mismatch prompt. Closes #183; supersedes the per-request
`client_tz` from feature 0070.

## Plan authoring & debate (codex-plan-debate-ext, 3 iterations)

- **Author:** Codex `gpt-5.6-sol` (xhigh) wrote the first plan → `0071_PLAN.md`.
- **Reviewers (blind panel, per iteration):** Claude Fable 5 subagent + Cursor CLI + fresh Codex CLI.
- **Iter 1:** ~14 findings. Accepted the substantive ones — retargeted phantom prop-assertion tests to the real homes (`test_schedule_view_props.py` / `test_analytics_views.py` / `test_user_preferences_api.py`); made PATCH a partial update so stale 2-field tabs and the timezone-only prompt path don't 400/clobber; corrected the corrupt-row fallback test to assert `datetime.UTC` by identity; split validation into a raising validator (model+API) vs a UTC-fallback safe resolver (AI runtime). Rejected: "fresh-user `get_or_create` rejects the `"UTC"` default" (verified `ZoneInfo("UTC")` always resolves via `tzdata`).
- **Iter 2:** partial-PATCH exposed two real issues — window-only PATCH on a corrupt stored tz, and the prompt Update clobbering a concurrently-changed window; resolved via timezone-only PATCH + descoping the corrupt-tz case (unreachable except via the `QuerySet.update()` the model already documents as unsupported). Fixed create-path `defaults`, message-ownership at the API layer, and moved ORM tests out of the ORM-free module.
- **Iter 3:** remaining P2s were self-contradictions introduced by prior edits (invalid `full_clean(exclude=)`, "exactly one lookup" vs two existing lookups, run-list omission, empty-`{}` vs existing test). All fixed. Converged.

## Implementation

Codex `gpt-5.6-terra` (high) implemented the plan TDD-first in an isolated
worktree. Verified green: backend pytest, ruff, `makemigrations --check`,
frontend vitest, `vue-tsc`, `vite build`.

## Post-implementation review (review-ship)

- **Local staged review:** one shape-consistency fix — `UserScheduleSettings.clean()`
  now stores `exc.messages[0]` (string) for the `time_zone` field error to match
  the sibling window fields and the API echo; added a create-path-with-tz test.
- **External review (codex + cursor), 2 passes:** first pass found **no production
  bugs**, only missing test coverage (several cases were plan-mandated RED steps the
  implementation skipped). Added that coverage across 11 test files — settings-API
  (non-UTC GET, combined window+tz errors, create-path, isolation), model
  (`save()`/`create()` rejection + isolation), chat (settings-lookup counts,
  400/429 no-provision, apply-time tz re-read), draft (two-lookup count,
  next-request persistence), and frontend (detection/list fallbacks, storage
  failure + in-memory isolation, prompt fail/retry + new-zone-after-dismiss,
  editor tz field-error revert, page prompt-prop assertions). Second pass:
  **NO P1/P2 FINDINGS** from either engine.

Final: backend 1323 passed, frontend 1047 passed; ruff, vue-tsc, build all green.
