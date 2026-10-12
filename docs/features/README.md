# Feature documents

The numbered `*_PLAN.md` files record a feature proposal at the time it was written. `*_REVIEW.md` files record a review of that implementation. Manual test files and handoffs record their own checks. Keep these documents as historical evidence; file names and examples may describe code that later changed.

Do not treat the absence of a review file as proof that a plan is still active. Some work was implemented or superseded without a matching review document. Check the current code and tests before using a plan as a specification.

For current work, start with [`tasks/todo.md`](../../tasks/todo.md) and the status in [`docs/REFACTORING_PLAN.md`](../REFACTORING_PLAN.md). For the implemented design, use [`docs/ARCHITECTURE.md`](../ARCHITECTURE.md), [`RULES.md`](../../RULES.md), and [`docs/api.md`](../api.md). [`PHASES.md`](../../PHASES.md) is the original roadmap. A feature plan remains useful for the decision and constraints it documents, but current contracts take precedence when they differ.

Examples of historical plans:

- [`0007_PLAN.md`](0007_PLAN.md) describes the chat rewrite. Later AI behavior is tracked in the R11 refactor report and current tests.
- [`0016_deploy_PLAN.md`](0016_deploy_PLAN.md) explains the production deployment design. The live runbook is [`deployment/README.md`](../../deployment/README.md).
- [`0020_PLAN.md`](0020_PLAN.md) and [`0020_REVIEW.md`](0020_REVIEW.md) show a plan and review pair. Current integration behavior is defined by the code and tests.
