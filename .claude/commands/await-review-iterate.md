Run the PR review iteration loop on the current branch's open PR: push → wait `claude-review` → triage → fix valid P0/P1 / push back on false-positives / defer P2/P3 → push fixes → repeat → STOP at the merge boundary.

This is the **iterate-and-fix** variant of the read-only triage skill `grid-bot-validation/.claude/commands/await-review.md`. Same parsing logic for the bot's comment, but here we actually push commits and loop. The merge step is **never** automatic — see RULES.md § "PR review iteration loop (AI-driven changes)" for the rationale.

## Step 1 — Push if there is anything to push

Run in parallel:
- `git status --porcelain` — must be clean (no uncommitted local changes). If dirty, **stop** and tell the user; do NOT auto-stage.
- `git rev-parse --abbrev-ref HEAD` — current branch. If it is `main` (or `master`), **stop** and ask the user to switch to the feature branch first.
- `git rev-list --count @{u}..HEAD 2>/dev/null` — commits ahead of upstream. If the upstream is missing (`fatal: no upstream configured`), the branch has never been pushed.

If commits ahead > 0: `git push`. If no upstream: `git push -u origin <branch>`. If commits ahead == 0 and upstream exists: skip push, log "Branch already up-to-date with origin".

Capture the current `HEAD` SHA — `git rev-parse HEAD` — for filtering review comments later.

## Step 2 — Locate the PR

`gh pr view --json number,headRefOid,url,headRefName`.

**If a PR exists**: capture its number / URL and proceed to Step 3.

**If no PR exists**: draft a title + body and ask the user to confirm before creating. Never auto-create without confirmation.

- **Title** (≤ 70 chars): mirror the commit subject if there's a single coherent commit, otherwise summarise the branch's intent. Match the project's prefix conventions (`feat(...)`, `fix(...)`, `test(...)`, `docs(...)`, etc., visible in `git log`).
- **Body** template:

  ```markdown
  ## Summary
  <2-4 bullet points covering the main changes>

  ## Test plan
  <Markdown checklist of how the changes were verified — tie back to commits / scripts / manual tests run>

  🤖 Generated with [Claude Code](https://claude.com/claude-code)
  ```

- Present the drafted title + body to the user inline. Wait for explicit confirmation (`yes`, `ok`, `create`, or a corrected version). Edits from the user override the draft verbatim.
- On confirmation, run `gh pr create --title "<title>" --body "$(cat <<'EOF' ... EOF)"` — heredoc so multiline body renders correctly.
- Re-run `gh pr view --json ...` to capture the new PR's metadata, then continue to Step 3.

If `headRefOid` does not match the local HEAD SHA after a push, wait ~5 s and re-query — GitHub may still be processing the push.

## Step 3 — Wait for the `claude-review` workflow

Use the Monitor tool with a poll loop on `gh pr checks <PR_NUM>`. Pseudocode:

```
prev=""
while true; do
  cur=$(gh pr checks <PR_NUM> --json name,state,bucket 2>/dev/null) || { sleep 5; continue; }
  state=$(echo "$cur" | jq -r '.[0].state // "unknown"')
  bucket=$(echo "$cur" | jq -r '.[0].bucket // "unknown"')
  if [ "$state" != "$prev" ]; then echo "claude-review: state=$state bucket=$bucket"; prev=$state; fi
  if [ "$bucket" != "pending" ] && [ "$bucket" != "unknown" ] && [ -n "$bucket" ]; then
    echo "FINAL: $bucket"
    break
  fi
  sleep 15
done
```

`timeout_ms: 420000`, `persistent: false`. Don't poll manually outside the Monitor tool.

If the workflow conclusion is `failure` / `cancelled`, surface the run URL and **stop** — no comment to parse.

## Step 4 — Fetch the bot's review comment for THIS push

```
gh pr view <PR_NUM> --json comments --jq '.comments[-1].body'
```

Verify the comment body starts with `## Code Review Summary` and contains `## Actionable Fixes`. If multiple comments exist, the latest one applies to the latest push.

If no matching comment exists even after the workflow reports success, wait ~10 s once and retry. If still missing, **stop** and surface the run URL — the bot may have skipped commenting (e.g., "No actionable fixes required" → that's a clean exit, treat as zero-finding).

## Step 5 — Parse priority items

The "Actionable Fixes" section is a numbered Markdown list. Match each line with this regex:

```
^\s*\d+\.\s+\*\*\[(P[0-3])\]\s+\[([A-Z]+)\]\*\*\s+(.+?):\s*(.+)$
```

Capture: priority, category tag (SECURITY/BUG/PERFORMANCE/QUALITY/TESTING/DOCS), location, instruction.

Bucket by priority. Also extract `## Merge Verdict` (APPROVED / CHANGES REQUESTED) — informational only; **does not authorize merge**.

## Step 6 — Triage by **severity AND validity**

For each P0 / P1 finding, decide one of three verdicts (read the cited file, cross-check against `RULES.md` and `CLAUDE.md`):

- **valid** — real bug / measurable issue / missing test for new logic. Apply.
- **disputable** — kernel of truth but contextual. Apply if cheap (≤ 15 min); otherwise note in PR comment + defer.
- **false-positive** — bot misread / repeating a previously rejected finding / contradicts project conventions.

**Before deciding "valid"**, check the false-positive catalogue in `RULES.md` § "Recurring claude-review false-positives in this project":
- env-var-for-fixture credentials
- DB-size "production-detection" guards
- Replacing idempotent Django shell snippets with `createsuperuser`
- `refresh_from_db()` immediately after `select_for_update().get()`
- Adding indexes Django already creates by default
- Defensive try/except for impossible races
- Template-literal "command injection" when interpolated values are hardcoded module-level constants

If a finding matches one of these patterns, treat as **false-positive** by default and require strong evidence to override.

For P2 / P3: don't analyze in depth. Either:
- **Apply inline** if cheap (≤ 5 min, no API change) — magic-number extraction, single-line tooltip, comment additions.
- **Defer** to `tasks/todo.md` § "Follow-ups" — anything that touches multiple files, requires design decisions, or could be its own PR.

## Step 7 — Act on the triage

1. **Valid P0 / P1** → fix in code. Run the relevant tests (`uv run pytest backend/tests/` and/or `cd frontend && npm test`) before pushing.
2. **False-positive P0 / P1** → post a single PR comment via `gh pr comment <PR_NUM> --body "..."` enumerating the rejections with one-paragraph rationale each. Reference earlier rejections by URL when the bot is reposting.
3. **P2 / P3 to defer** → append to `tasks/todo.md` § "Follow-ups" (existing section near the bottom). Use the format already present (heading + 1-paragraph body).
4. **P2 / P3 to apply inline** → small commit, no extra ceremony.

If anything was committed, push as a **stacked follow-up commit** (don't force-push unless amending a single still-pending top commit).

## Step 8 — Loop control

After pushing fixes (or deciding nothing needs pushing):

- **If new commits were pushed** → loop back to Step 3 (wait for the next `claude-review` cycle on the new HEAD).
- **If no new commits and findings are only P2/P3 (or none)** → exit loop. Proceed to Step 9.
- **Hard cap: 3 iterations.** If still seeing valid P0/P1 after 3 cycles, exit and report — something is off, escalate to the user.

## Step 9 — Report and STOP at the merge boundary

Print a status report:

```
# Iteration loop terminated — PR #<N>

**Iterations**: M (max 3)
**CI**: green / red
**Merge verdict from bot**: APPROVED / CHANGES REQUESTED

**Findings:**
- Valid P0/P1 fixed: X
- False-positives rejected with rationale on PR: Y
- P2/P3 deferred to tasks/todo.md: Z
- P2/P3 applied inline: W

**Status**: ready for merge / blocked

Awaiting explicit `merge` / `ok merge` from the user before running `gh pr merge <N> --merge`.
```

**Do NOT call `gh pr merge` here**, regardless of:
- The bot's APPROVED verdict
- All-green CI
- The user having said "fix the review" or "apply the suggestions" earlier — those authorize code changes only

The user retains the merge decision. See RULES.md § "PR review iteration loop (AI-driven changes) → The merge step is NOT in the loop" and the project memory file `~/.claude/projects/-Users-erzhan-DATA-PROJ-day-forge/memory/feedback_pr_merge.md`.

## Constraints

- **Never run `gh pr merge`** without an explicit user command for THIS PR.
- **Never `git push --force`** unless amending the most recent commit on a one-commit PR. Stacked follow-ups are the default.
- **Never auto-stage with `git add -A` / `git add .`** — list files explicitly to avoid pulling in `.env` or other secrets.
- **Don't loop more than 3 iterations** without escalating.
- **Don't trust the bot's verdict line as authorization for anything.** It's informational. The user decides.
- **All bot rejections must be posted to the PR**, not silently ignored. The audit trail itself is part of the workflow.

## Edge cases

- **Dirty working tree at Step 1.** Stop, list the untracked / modified files, ask the user to commit / stash. Don't act.
- **Branch is `main` / `master`.** Stop. The skill is for feature branches with open PRs.
- **No PR for the branch.** Draft title + body per the Step 2 template, present to the user, await explicit confirmation, then `gh pr create`. Never auto-create without confirmation.
- **`headRefOid` lags after push.** Wait ~5 s, re-query once. If still mismatched, surface and stop.
- **Workflow ran but no comment posted.** Treat as "no findings" — exit loop, report, wait for merge approval.
- **Workflow conclusion is `failure` / `cancelled`.** Surface the run URL. Stop. Don't try to parse a missing comment.
- **Bot reposts a previously rejected finding.** Reject again, citing the prior rejection comment URL. Do not silently re-apply.
- **Tests fail after a fix.** Don't push the broken fix. Either keep iterating to make tests pass OR back out the change and report.
- **Iteration cap hit (3) with valid P0/P1 still open.** Stop, post a status comment on the PR summarising what's been applied and what remains, escalate to the user.
