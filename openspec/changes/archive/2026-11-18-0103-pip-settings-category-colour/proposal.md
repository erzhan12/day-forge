# 0103 — PiP category colour after a Settings edit

## Why

An open focus-indicator PiP kept the old category colour after the user changed it in Settings. The root owner copied the catalogue only when Schedule published, and Schedule is unmounted while Settings is open. See issue #213 and [docs/features/0103_PLAN.md](../../../../docs/features/0103_PLAN.md).

## What changes

- While a snapshot is retained, the app root copies a valid category catalogue from the current authenticated, non-Login page. The retained date, blocks and time zone are unchanged.
- A missing or malformed catalogue, a Login page, a missing user id, an uninitialized page component or the absence of a retained snapshot leaves the retained catalogue unchanged.
- Category reloads in Settings also request `auth_user_id`, so a new catalogue never arrives under a stale identity.
- Schedule's reactive and unmount publications are unchanged.

## Capabilities

- `frontend/focus-indicator`: ADDED "Retained category catalogue refresh".

## Impact

Frontend only: `useFocusIndicatorController.ts` and `useCategories.ts`. No API or backend production change; a backend test pins partial-reload identity.
