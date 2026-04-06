Review staged changes, automatically fix critical issues, and re-verify — up to 3 iterations.

## Step 1: Identify changed files

Run `git diff --staged --name-only` to get staged files. If nothing is staged, fall back to `git diff HEAD --name-only`. If still nothing, print "No changes to review" and stop.

Save the file list — it stays fixed for all iterations.

## Step 2: Review loop (max 3 iterations)

For each iteration:

### 2a. Run code review

For each category below, run a parallel subagent that reads the changed files and the full diff (`git diff --staged` or `git diff HEAD`, matching step 1). Only report actual issues, not generic advice.

**Categories:**

1. **Code Quality** — DRY violations, missing error handling for real failure paths, unclear names, functions doing too much, violations of `.claude/rules/` conventions
2. **Security** — unsanitized input to shell/DB/HTML, hardcoded secrets, missing auth checks, unsafe deserialization or file paths
3. **Performance** — N+1 queries, missing temp file cleanup, blocking calls in async code, unbounded fetches
4. **Testing** — new logic without tests, uncovered edge cases, trivially passing tests
5. **Documentation** — public API changes without docstring updates, new env vars not in `rules/project.md`

### 2b. Classify findings

After subagents complete, classify each finding:
- **CRITICAL**: Must fix — security vulnerabilities, data loss, crashes, broken functionality
- **WARNING**: Should fix — bugs, performance issues, missing tests
- **INFO**: Nice to have — readability, minor improvements

### 2c. Decision

- If **no CRITICAL issues**: break out of loop
- If **CRITICAL issues found** and iteration < 3: fix ALL critical issues in the code, then continue to next iteration (re-review the same file list)
- If **iteration 3 reached** and criticals remain: break out of loop and flag for manual review

## Step 3: Final summary

Print a structured summary:

```
## Review Summary

**Files reviewed:** (list files)
**Iterations:** N/3
**Criticals found:** N (N fixed, N remaining)
**Warnings:** (list each with file:line)
**Info:** (list each with file:line)

**Result:** Ready to commit ✅  /  Manual review needed ⚠️
```

Use "Ready to commit" if zero criticals remain. Use "Manual review needed" if criticals persist after 3 iterations.

Warnings and info items should be listed for awareness but do NOT block the result.
