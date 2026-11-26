---
paths:
  - "openspec/**"
  - "docs/features/**"
  - "backend/scripts/check_spec_anchors.py"
  - "backend/tests/test_check_spec_anchors.py"
---

## Behavior specs (OpenSpec)

- `openspec/specs/<capability>/spec.md` records current behavior; 28 baseline specs cover the backend and the schedule, undo, focus-indicator, external-source and chat client code. A feature adds a change in `openspec/changes/NNNN-slug/` next to `docs/features/NNNN_PLAN.md` and runs `openspec archive NNNN-slug` on the feature branch before the fast-forward merge. Workflow: `docs/features/README.md`.
- `make spec-check` (part of `make check` and CI) runs strict validation and `backend/scripts/check_spec_anchors.py`. It needs the pinned CLI: `npm install -g @fission-ai/openspec@2.0.0`. Renaming or deleting a test or symbol that a spec cites fails it, so update the anchor in the same change.
- Pitfalls: a requirement body over 500 characters fails strict validation (put `Tests:` under scenarios); the anchor checker splits lists only on a comma followed by `path::`, resolves inherited pytest methods and names assigned inside module-level `if`/`try`; cite what actually enforces a rule, and record a gap in `docs/features/0099_SPEC_REVIEW.md` rather than writing an unenforced requirement. "Task and calendar text never reaches the LLM" has no spec for that reason: only block-title masking is enforced in `backend/ai`. A MODIFIED requirement must keep every scenario title of the baseline: a renamed scenario counts as omitted and fails validation, so change the scenario's text and keep its title.
- OpenSpec skills live in `.agents/skills/` (linked from `.claude/skills/`); refresh them with `openspec update`, not by hand. Where a spec and this file disagree, fix whichever is wrong and say which in the commit.
