# Feature documents

The numbered `*_PLAN.md` files record a feature proposal at the time it was written. `*_REVIEW.md` files record a review of that implementation. Manual test files and handoffs record their own checks. Keep these documents as historical evidence; file names and examples may describe code that later changed.

Do not treat the absence of a review file as proof that a plan is still active. Some work was implemented or superseded without a matching review document. Check the current code and tests before using a plan as a specification.

For current work, start with [`tasks/todo.md`](../../tasks/todo.md) and the status in [`docs/REFACTORING_PLAN.md`](../REFACTORING_PLAN.md). For the implemented design, use [`openspec/specs/`](../../openspec/specs/), [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md), [`RULES.md`](../../RULES.md), and [`docs/api.md`](../api.md). [`PHASES.md`](../../PHASES.md) is the original roadmap. A feature plan remains useful for the decision and constraints it documents, but current contracts take precedence when they differ.

Examples of historical plans:

- [`0007_PLAN.md`](0007_PLAN.md) describes the chat rewrite. Later AI behavior is tracked in the R11 refactor report and current tests.
- [`0016_deploy_PLAN.md`](0016_deploy_PLAN.md) explains the production deployment design. The live runbook is [`deployment/README.md`](../../deployment/README.md).
- [`0020_PLAN.md`](0020_PLAN.md) and [`0020_REVIEW.md`](0020_REVIEW.md) show a plan and review pair. Current integration behavior is defined by the code and tests.

## OpenSpec workflow (from feature 0098)

New features use [OpenSpec](https://github.com/Fission-AI/OpenSpec) alongside the numbered plans. The plan stays the design document. The OpenSpec change records what the feature does to the system's specified behavior. [`openspec/config.yaml`](../../openspec/config.yaml) carries the same rules for the OpenSpec skills.

| Artifact | Location | Holds |
| --- | --- | --- |
| Plan | `docs/features/NNNN_PLAN.md` | Design, trade-offs, review history |
| Change | `openspec/changes/NNNN-slug/` | `proposal.md` (why and what, linking to the plan), spec deltas under `specs/`, and `tasks.md` |
| Specs | `openspec/specs/<capability>/spec.md` | Current behavior, one file per capability, with `Enforced:` and `Tests:` anchors |

Steps for a feature:

1. Write and review `docs/features/NNNN_PLAN.md` as before.
2. After the plan is approved and the feature branch exists, create the change with `/openspec-propose` or `openspec new change NNNN-slug`. Its spec deltas use `## ADDED`, `## MODIFIED`, `## REMOVED` or `## RENAMED Requirements`. Skip `design.md` when the plan already records the design.
3. Track implementation in the change's `tasks.md`. `tasks/todo.md` keeps only open decisions that span features.
4. Before the fast-forward merge, run `openspec archive NNNN-slug` on the feature branch. It folds the deltas into `openspec/specs/` and moves the change to `openspec/changes/archive/`. Main is never edited directly, so archiving happens in the feature PR.
5. Run `make spec-check`. It runs `openspec validate --all --strict` and checks that every `Enforced:` and `Tests:` anchor still exists.

Renaming or deleting a test or symbol that a spec cites breaks `make spec-check`. Update the anchor in the same change, even when the change is a refactor that alters no behavior.

Spec-writing pitfalls:

- OpenSpec strict validation rejects a requirement body (the text between `### Requirement:` and the first `#### Scenario:`) longer than 500 characters. Put `Tests:` lines under scenarios and keep only the SHALL sentence and `Enforced:` in the body.
- Anchor lists are comma-separated, but a comma only splits when a new `path::` anchor follows, so Vitest titles that contain commas are cited verbatim.
- Python anchors resolve through the AST, including names assigned inside module-level `if`/`try` blocks and test methods inherited from a base class (cite them on the concrete class, as pytest runs them).
- Do not write a requirement whose `Enforced:` anchor does not actually enforce it. List the gap in the feature's review notes instead. [`0099_SPEC_REVIEW.md`](0099_SPEC_REVIEW.md) holds the open items from the baseline.

A change that alters no specified behavior, such as a refactor, docs edit or dependency bump, needs no OpenSpec change. Until the baseline specs absorb them, [`RULES.md`](../../RULES.md) and [`docs/api.md`](../api.md) remain authoritative where they disagree with a spec. Fix the spec in that case.
