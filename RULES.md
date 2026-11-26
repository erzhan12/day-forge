# Development rules

These are current implementation contracts and exceptions. The code is authoritative
when a rule and an implementation differ. The rules now live in
[`.claude/rules/`](.claude/rules/). Claude Code loads each file automatically when
you work on the paths in its `paths:` frontmatter; `workflow.md` has no `paths` and
is always loaded. Other tools (Codex, reviewers) should read the file for the area
they touch. Add new pitfalls to the matching file, not here.

Detailed decisions and old incidents are in
[the rules archive](docs/archive/RULES_HISTORY.md). The
[architecture](docs/ARCHITECTURE.md) maps current owners, and the
[refactoring plan and reports](docs/REFACTORING_PLAN.md) explain successive
changes. [R11 design](docs/REFACTORING_R11_DESIGN.md) separates the implemented
durable request identity from the proposed server-owned pending intent.

| File | Area |
| --- | --- |
| [workflow.md](.claude/rules/workflow.md) | Workflow, tooling, secrets, CI pins, merge gate, worktrees (always loaded) |
| [openspec.md](.claude/rules/openspec.md) | OpenSpec pitfalls, anchors, and archive-before-merge |
| [repo-deploy.md](.claude/rules/repo-deploy.md) | Production stack, Caddy routing, WhiteNoise, static assets |
| [schedule-writes.md](.claude/rules/schedule-writes.md) | Schedule mutations, revisions, and validation by source |
| [analytics.md](.claude/rules/analytics.md) | Analytics, review snapshots, notes, streak |
| [export.md](.claude/rules/export.md) | Daily export and the personal export token |
| [ai-safety.md](.claude/rules/ai-safety.md) | AI requests, pending intent, replay guard, privacy |
| [frontend-undo.md](.claude/rules/frontend-undo.md) | Page ownership, Undo, Inertia release, theme bootstrap |
| [integrations.md](.claude/rules/integrations.md) | Calendar, Google, Todoist, Habitica, WHOOP, external rail |
| [ui.md](.claude/rules/ui.md) | PiP, notifications, Dark 4a, Settings typography |
| [testing.md](.claude/rules/testing.md) | Playwright smoke, seeders, SQLite lock tests |
| [project.md](.claude/rules/project.md) | Environment variables, legal pages, key-rotation notes |
