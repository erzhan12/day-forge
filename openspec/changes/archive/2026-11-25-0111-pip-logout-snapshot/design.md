# Design

Design and trade-offs live in [docs/features/0111_pip_logout_snapshot_PLAN.md](../../../docs/features/0111_pip_logout_snapshot_PLAN.md). Summary: demote ungated `publish` to internal `applySnapshot` behind `publishIfGenerationMatches`, refuse Login / null-user writes, expose `retainedSnapshot()` for tests.
