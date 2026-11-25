# 0111 — Stop Logout from repopulating the cleared PiP schedule snapshot (issue #212)

Technical plan for a privacy bug fix (issue #212). Investigation baseline: `main` @ `1d5ffc7` (issue reviewed an older tree at `a988537`).

## Brief

Issue #212: after Logout, outgoing schedule data can remain (or return) in the root Focus Indicator / PiP controller — a cross-session private-data leak. Priority is higher than ordinary UI bugs for that reason.

Similar boundary work already lives in `tasks/lessons.md` (PiP + Logout / session hygiene) and in RULES.md’s PiP ownership paragraph: Login / null-user / account-switch must clear retained data and reject stale publications.

## Current code (baseline)

Issue #212’s cited `Schedule.vue` path called ungated `publish(...)`. On current main that call site already uses `publishIfGenerationMatches` with a generation captured at Schedule setup (`Schedule.vue` ~184–201). The root session watcher in `useFocusIndicatorController.ts` (~163–175, `flush: "sync"`) bumps `publicationGeneration`, calls `clearSnapshot()`, and runs `focusIndicator.cleanup()` when `page.component === "Login"`, `auth_user_id === null`, or the user id changes.

Stub coverage in `FocusIndicatorHost.test.ts` already includes “does not restore the departing publisher snapshot after the root clears it for Login” and related generation tests, using a Schedule-like `Publisher` helper — **not** the real `Schedule.vue`. On this baseline, **both production Schedule publish paths already use `publishIfGenerationMatches`**, so Login teardown from Schedule is already generation-rejected. The remaining hole is an **exposed controller bypass**: public ungated `publish()` (only direct callers today are Host tests ~389, ~411, ~432) can restore a snapshot after Login or account-switch clear. Issue #212 still requires closing that bypass for any future caller and a real-Schedule Host acceptance test.

Remaining holes against the issue:

1. **Exposed ungated `publish()` on the controller.** It always writes `retainedDate` / blocks / categories (`useFocusIndicatorController.ts` ~135–142). After Login clear **or** account-switch clear, raw `publish` restores the outgoing snapshot. Issue #212 asks for a controller-level guard that protects every publishing entry point, not only Schedule’s generation path.
2. **Acceptance gap:** no integration test mounts the real `Schedule` under `FocusIndicatorHost`, transitions to `Login`, unmounts Schedule, and asserts retained state has **zero blocks and zero categories**, PiP closed, and further republication rejected.
3. Issue line numbers are stale; treat the behaviours above as the contract, not the old offsets.

Inertia’s Vue adapter updates the page object **before** unmounting the previous page component (already relied on by feature 0103 / Host tests). Logout therefore hits the sync Login watcher first; Schedule’s `onBeforeUnmount` runs second. Generation matching stays for that order. This change closes the raw-`publish` bypass (including account switch) and locks the contract with a real-Schedule Host test that inspects retained emptiness.

## Chosen approach

**Every retained write is generation-bound.** Session boundaries bump `publicationGeneration` and clear as today; no public API may write retained state without presenting the current generation.

Concrete rules inside `useFocusIndicatorController`:

1. Keep `publishIfGenerationMatches(generation, …): boolean` as the **only** public write API used by Schedule and by tests that seed a snapshot. Generation check stays first.
2. Replace the public ungated `publish(...)` write surface:
   - Either remove `publish` from the exported `FocusIndicatorController` interface and keep an internal `applySnapshot(...)` used only by `publishIfGenerationMatches`, **or**
   - Change `publish` so it is no longer callable as an ungated write (same effect: tests and production cannot bypass generation).
   Prefer the internal-`applySnapshot` shape so a future caller cannot reintroduce the hole.
3. Defense in depth on `applySnapshot` / the write body: no-op when `page.component === "Login"` **or** `page.props?.auth_user_id === null`. Do **not** treat an uninitialized / absent `component` as logout.
4. **`publishIfGenerationMatches` must return `false` when the write is refused** — generation mismatch **or** the session gate no-ops the apply. Today it calls `publish` then always `return true` (`useFocusIndicatorController.ts` ~158–160); after this change, a current-generation call on Login / null user must not report success. Capture generation *after* clear in the test that proves this.
5. Do not remove Schedule’s unmount canonical `publishIfGenerationMatches` for ordinary authenticated navigations (Settings / Analytics). Inertia has already moved `component` onto an authenticated page; generation is unchanged; the write must still apply the canonical snapshot.
6. Expose a **read-only** `retainedSnapshot()` (or equivalent) returning `{ date, blocks, categories }` (copies) so privacy tests can assert emptiness without relying only on `indicatorActive` / next-block. Production UI need not use it.
7. Do not change PiP open/close chrome, opacity, category-colour refresh (0103), or restore-intent rules beyond what `cleanup()` already does on Login / account switch.

Account switch: session watcher already bumps generation and clears. After the change, an old publisher’s generation is rejected; a **new** Schedule instance (or test publisher) that captures `publicationGeneration()` after the switch may publish again for the new user. Production logout→login remounts Schedule; an in-place `auth_user_id` change while Schedule stays mounted **fail-closes** (clear + refuse) until remount — do not auto-rebind the setup-time generation from props alone. `refreshSchedule()`’s `auth_user_id` in `only` is same-account identity freshness, not an account-switch protocol. Existing Host tests that call raw `publish` after switch/Login (~389, ~411, ~432) must be rewritten to assert rejection of the ungated/stale path, or to seed only via a post-boundary generation capture on a new publisher, without weakening the catalogue-on-Login proofs.

## Files and functions

Implementation only after the failing tests exist (TDD):

- `frontend/src/composables/useFocusIndicatorController.ts`
  - Remove or demote public ungated `publish`; add internal `applySnapshot`; keep `publishIfGenerationMatches` as the write API; make it return `false` when apply is refused; add Login / null-user gate inside apply; add read-only `retainedSnapshot()`.
  - Session watcher and catalogue watcher: keep sync flush, clear + `cleanup()` on Login / null user / user change; catalogue watcher still no-ops on Login / empty retained date.
- `frontend/src/pages/Schedule.vue`
  - Keep `publicationGeneration()` capture, reactive `publishIfGenerationMatches`, and `onBeforeUnmount` canonical publish. No production change expected; touch only if the real-Schedule Host test forces a wiring fix.
- `frontend/tests/FocusIndicatorHost.test.ts`
  - Add / extend cases under Tests. Rewrite post-clear raw `publish` seeds (~389, ~411, ~432) so they either assert rejection or seed only via `publishIfGenerationMatches` with a generation captured on an authenticated page after the boundary.
  - Real `Schedule` under Host for the Login+unmount privacy case (issue acceptance). Reuse fixtures from `scheduleFocusIndicator.test.ts` / `Schedule.test.ts` (catalog, `auth_user_id`, clock mocks, fake PiP). Prefer keeping this next to other Host privacy tests.
- `RULES.md` (PiP bullets ~110–111): retained writes go only through generation-matched publication; Login / null-user / account-switch clear and reject stale generations; apply also refuses Login / null user; privacy tests may use `retainedSnapshot()`.
- OpenSpec: after plan approval and feature branch creation, change `openspec/changes/0111-…` modifying `openspec/specs/frontend/focus-indicator/spec.md` so every publication entry point is generation-bound and Login / null-user refusal is specified. Archive with the PR as usual.

No backend, API, or migration changes.

## Algorithm (logout teardown)

1. User posts Logout → Inertia visits Login; SPA root (`FocusIndicatorHost`) stays mounted.
2. `usePage().component` becomes `"Login"` (and/or `auth_user_id` becomes `null`).
3. Session watcher (`flush: "sync"`): `publicationGeneration += 1`, `clearSnapshot()`, `focusIndicator.cleanup()` (PiP closes, restore intent cleared per existing Hide/Login rules).
4. Vue unmounts Schedule → `onBeforeUnmount` calls `publishIfGenerationMatches(oldGeneration, …)`.
5. Generation mismatch → return `false`; `retainedSnapshot()` stays `{ date: "", blocks: [], categories: [] }`. A same-generation call after clear that still hits Login / null user also returns `false` and does not write.
6. Login page shows neutral indicator derived state.

Authenticated Schedule → Settings teardown still succeeds at step 4 with unchanged generation and non-Login / non-null user.

## Tests (red → green → refactor)

Write failing tests first; implement the smallest controller change that turns them green; only then tidy.

**TDD note (baseline):** on current main, real Schedule’s Login unmount alone may already stay cleared (generation). The **required reds** before implementation use the **existing ungated `publish()` API** and **existing** derived signals (`indicatorActive`, next-block, rail colour) — they must not depend on `retainedSnapshot()` yet, or the red fails on a missing accessor before exercising the leak. After the controller gate and `retainedSnapshot()` land, strengthen the same cases with direct empty-snapshot assertions. Do not treat “Schedule unmount after Login” or “old generation returns false” alone as the sole red. After the fix, assert the ungated entry point is **gone from the public controller** (or permanently refuses), not merely unused.

1. **Real Schedule under Host + Login unmount (issue acceptance).** Mount `FocusIndicatorHost` with real `Schedule`. Establish a non-empty snapshot and **prove Schedule populated the Host controller** (non-empty blocks and categories via existing signals / post-fix `retainedSnapshot()`); **open fake PiP and assert it is open**. Set `page.component = "Login"` and `auth_user_id = null` (Logout shape), then unmount Schedule. Assert **immediately after unmount**, before any direct publication probes: exactly one PiP close and no second open request; `indicatorActive` false; next-block null; empty retained blocks/categories once `retainedSnapshot()` exists; `publishIfGenerationMatches(oldGeneration, …) === false`. **Baseline red (existing APIs only):** while still on Login, call ungated `publish(...)` with the outgoing snapshot and write the assertion as the desired privacy outcome (`expect(indicatorActive).toBe(false)` — and a signal that actually flips on leak for the fixture, e.g. rail/title; do not rely on `indicatorNextBlock`, which stays null for an active-block fixture even when the write leaks). That expectation fails on baseline because `publish` restores content. **Post-fix:** ungated public write is gone or refuses; `retainedSnapshot()` has empty `date`, **zero blocks, zero categories**.
2. **Ungated `publish` after account switch (required red).** After switching `auth_user_id` 1 → 2 (single props replace, as `FocusIndicatorHost.test.ts` ~400–415), assert clear + PiP close. **Baseline red:** call raw `controller.publish(...)` with user 1’s blocks and assert desired privacy (`indicatorActive` stays false / leak-sensitive signal); fails today because the write restores content. **Post-fix:** ungated path removed or refuses; old generation `publishIfGenerationMatches` is `false`; assert snapshot still empty **immediately after** that stale call (via `retainedSnapshot()` once available); a **new** publisher instance that captures the post-switch generation may publish again, and retained blocks/categories must be **only** that distinct user-2 snapshot (not user 1’s).
3. **`publishIfGenerationMatches` returns `false` when the session gate refuses — both boundaries, current generation.** For each isolated clear, capture `publicationGeneration()` **after** the clear, then call `publishIfGenerationMatches(thatGeneration, …)` and expect `false` plus empty retained state: (a) after `component === "Login"` with a previous numeric `auth_user_id` still present; (b) after `auth_user_id === null` on `Schedule`. A stale pre-clear generation must not be the only assertion — it can pass while the session gate is missing.
4. **Null-user session cleanup (not only write refusal).** Start with a populated snapshot and open PiP on `Schedule`, set **only** `auth_user_id = null` (leave component as `Schedule`), and assert generation advanced, PiP closed, and derived state cleared **before** the current-generation refusal in test 3b. Do not let the Login branch alone keep this green.
5. **Existing Host generation / Login / uninitialized-component tests stay green**, including “does not restore the departing publisher snapshot…” and “does not treat an uninitialized page component as logout”, after rewriting any raw post-clear `publish` seeds.
6. **Authenticated navigation still publishes on Schedule unmount.** Move to Settings / Analytics with generation unchanged; assert retained snapshot remains and PiP stay-open behaviour from existing tests is unchanged.

Browser smoke that needs a real Document PiP window stays out of scope (lessons.md); Host fake-PiP coverage is the required automated proof.

## Out of scope

- Changing Inertia history encryption / Login history-key clearing (separate lesson).
- PiP category-colour refresh (0103) beyond not breaking it; optional later hardening of catalogue-watcher tests so they fail if only the empty-date guard remains (deferred P2).
- Strengthening the authenticated-unmount test with a drag-preview vs canonical distinction (deferred P2; existing unmount publisher + Host coverage remain).
- Auto-rebinding Schedule’s setup-time `publicationGeneration` after an in-place `auth_user_id` change without remount. Fail-closed clear + refuse until remount is required; production account change goes Login → new Schedule mount. (`refreshSchedule` including `auth_user_id` is same-account reload freshness.)
- Auto-opening PiP after logout, or restore-intent behaviour on browser window close.
- Backend logout / session endpoints.
