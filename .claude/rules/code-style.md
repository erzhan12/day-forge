# Code Style & Guardrails

## Workflow
1. Plan first — describe approach and wait for approval
2. If >3 files affected, break into smaller tasks
3. Track work in `tasks/todo.md` as checkable items
4. After writing code, list what could break and suggest tests
5. Bug fixes start with a reproducing test

## Safety Rules
- Never overwrite existing files without confirmation; create `.bak` backup if risky
- No `rm`, `del`, `rmdir`, or `rm -rf` without explicit approval
- Package installs: explain what, why, and impact before proceeding
- Database migrations: always confirm before running; never drop tables without approval
- When in doubt, explain the command in plain language and ask before running

## Self-Improvement Loop
- When I correct you, update `tasks/lessons.md` with pattern and prevention rule
- Review `tasks/lessons.md` at the start of every session
