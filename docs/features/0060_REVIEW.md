# Code Review — Issue #140: GitHub Actions SHA Pinning

Change surface: `.github/workflows/{claude-code-review,claude,deploy}.yml` — 13
`uses:` lines repinned from movable tags to 40-hex commit SHAs with `# vX.Y.Z`
comments. Plan: `docs/features/0060_PLAN.md`.

## Local verification (orchestrator)

- 13 `uses:` lines, all SHA-pinned; zero bare `@vN` tags remain.
- Repeat identity: 5× `actions/checkout` → identical `11d5960a…  # v4.4.0`;
  2× `anthropics/claude-code-action` → identical `c81e3bc6…  # v1.0.201`.
- **All 8 SHAs resolved via `gh api repos/<repo>/commits/<tag>` — every SHA
  matches its version comment** (no typosquat, no wrong pin).
- Diff scope: only `uses:` lines changed. No permissions/secrets/triggers/
  step-config touched; no non-workflow tracked files; no mode/create/delete;
  `git diff --check` clean.
- YAML valid for all three files.

## External review trail

- **Engines**: codex (`gpt-5.6-sol`, read-only) + cursor agent (`--mode ask`).
- **Rounds**: 1.
- **codex**: `NO P1/P2 FINDINGS`, no P3. Independently resolved all 8 SHAs to
  upstream release pages (web); confirmed action identity multiset unchanged
  HEAD↔worktree; diff numstat/raw scope clean (2/2/9 line swaps).
- **cursor**: `NO P1/P2 FINDINGS`, no P3. Network blocked in its Ask session;
  live-resolved 2 SHAs (setup-node v4.4.0, ssh-agent v0.9.0 — both MATCH),
  verified the other six by file inspection (no mismatch). Pin format, repeat
  identity, YAML shape, and syntax/style all PASS.
- **Findings raised**: 0. **Accepted/fixed**: 0. **Rejected**: 0. **P3-ignored**: 0.

## Result

SUCCESS — zero valid P1/P2 findings. No code changes required. Ready to commit.
