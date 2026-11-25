# Proposal

## Why

After Logout, an ungated Focus Indicator `publish` could restore the outgoing user’s schedule into the long-lived root PiP controller. That is a cross-session private-data leak (issue #212). See [docs/features/0111_pip_logout_snapshot_PLAN.md](../../../docs/features/0111_pip_logout_snapshot_PLAN.md).

## What Changes

- Remove the public ungated `publish` API from the PiP controller; retained writes go only through `publishIfGenerationMatches`.
- Refuse writes on definite Login or null `auth_user_id`, and return `false` when refused.
- Expose read-only `retainedSnapshot()` for privacy assertions.
- Cover Login / null-user / account-switch refusal and real Schedule under Host after Logout.

## Capabilities

### New Capabilities

None.

### Modified Capabilities

- `frontend/focus-indicator`: MODIFIED “Root ownership and publication generation” — generation-bound writes only; Login / null-user refuse apply; retained emptiness after Logout.

## Impact

Frontend PiP controller and Host/Schedule privacy tests only. No backend, API, or migration change.
