Review files changed in the last commit. Use `git diff HEAD~1 HEAD --name-only` to get the file list, then `git diff HEAD~1 HEAD` for the full diff.

For each category below, run a parallel subagent that reads the changed files and reports findings as a bullet list. Only report actual issues, not generic advice.

## 1. Code Quality
- Violations of DRY, single responsibility, or existing patterns in this codebase
- Missing error handling for failure paths that can actually occur
- Unclear variable names, deeply nested logic, or functions doing too much
- Check against `.claude/rules/` conventions

## 2. Security
- User input passed unsanitized to shell commands, DB queries, or HTML output
- Hardcoded secrets, tokens, or credentials
- Missing authentication/authorization checks on new endpoints or handlers
- Unsafe deserialization or file path handling

## 3. Performance
- N+1 queries or unbounded database fetches
- Missing cleanup of temp files, background tasks, or event listeners
- Blocking calls in async code paths
- Large allocations in hot loops

## 4. Testing
- New logic paths without corresponding tests
- Edge cases not covered (empty input, None, timeout, API failure)
- Tests that pass trivially or don't assert meaningful behavior

## 5. Documentation
- Public API changes without docstring updates
- New environment variables or config not documented in `rules/project.md`
- Breaking changes that need migration notes

After all subagents complete, compile a single summary:
- **Critical**: Must fix (security, data loss, crashes)
- **Warning**: Should fix (bugs, performance, missing tests)
- **Suggestion**: Nice to have (readability, minor improvements)

If no issues found in a category, omit it from the summary. Be specific — include file paths and line numbers.
