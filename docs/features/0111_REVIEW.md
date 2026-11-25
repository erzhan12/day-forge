# 0111 — PiP logout snapshot privacy: code review

**Reviewed:** working tree vs `main` (uncommitted) against `docs/features/0111_pip_logout_snapshot_PLAN.md`  
**Scope:** `useFocusIndicatorController.ts`, `FocusIndicatorHost.test.ts`, `scheduleFocusIndicatorLogoutPrivacy.test.ts`, `RULES.md`, `openspec/changes/0111-pip-logout-snapshot/`  
**Criteria:** `commands/code_review.md` (plan fidelity, bugs, data alignment, over-engineering, style, unit tests)  
**Verification:** `npx vitest run tests/FocusIndicatorHost.test.ts tests/scheduleFocusIndicatorLogoutPrivacy.test.ts` → 2 files / 25 tests passed

Severity: **P1** must fix before merge · **P2** should fix · **P3** nit / follow-up.

**0 P1, 0 P2, 5 P3.** Privacy contract is implemented correctly; no blocking bugs found.

## Verdict

**Approve** — ready to commit / open PR after the usual `make check` gate. Issue #212’s ungated `publish` bypass is closed; Login / null-user apply refusal returns `false`; real Schedule under Host proves empty retained state after Logout.

## Plan conformance

| Plan item | Status | Notes |
|-----------|--------|-------|
| Remove public ungated `publish`; internal `applySnapshot` | ✅ | Dropped from interface + return object; write body is `applySnapshot` only (`useFocusIndicatorController.ts:150-164`, `:226-239`) |
| `publishIfGenerationMatches` returns `false` on generation mismatch **or** session refuse | ✅ | `:187-189` |
| Login / null-user gate; do not treat uninitialized `component` as logout | ✅ | `sessionRefusesPublication` (`:141-146`); mirrors clear predicates; absent/`undefined` component still allows authenticated publish |
| `retainedSnapshot()` copies `{ date, blocks, categories }` | ✅ | `:173-179`; no nested `{ data: … }` |
| Schedule.vue production path unchanged | ✅ | Still setup-time generation + `publishIfGenerationMatches` / unmount canonical publish |
| Rewrite Host post-clear raw `publish` seeds | ✅ | Catalogue/Login/account-switch cases now refuse or seed via post-boundary generation |
| Real Schedule under Host Logout acceptance | ✅ | New `scheduleFocusIndicatorLogoutPrivacy.test.ts` |
| Host tests: ungated removal, account switch, post-clear current-gen refuse (Login + null-user), null-user cleanup | ✅ | New cases ~262–344 |
| RULES.md PiP bullet | ✅ | Generation-only writes, apply refuse, `retainedSnapshot()` |
| OpenSpec change `0111-pip-logout-snapshot` | ✅ | Delta scenarios for ungated removal, Login/null refuse, real Schedule Logout |
| Authenticated Schedule → Settings unmount still publishes | ✅ | Existing Host coverage left in place (`keeps one PiP open…`) |
| No PiP chrome / 0103 catalogue-refresh behaviour change beyond gate | ✅ | Catalogue watcher unchanged |

**Extras (not required by plan, fine):** Host assertions strengthened with `retainedSnapshot()` on several pre-existing Login/clear cases; leftover-catalogue-after-Login test explicitly restores `auth_user_id` before post-Login seed.

**Soft plan deviations (non-blocking):** see P3-1 and P3-2.

## Findings

| # | Sev | Location | Finding |
|---|-----|----------|---------|
| 1 | P3 | `FocusIndicatorHost.test.ts:491-521` | Account-switch “fresh publish” does not assert a **distinct user-2** snapshot |
| 2 | P3 | `FocusIndicatorHost.test.ts:461-488` | Catalogue-on-Login proof no longer seeds a retained snapshot on Login (plan tension / deferred P2) |
| 3 | P3 | `scheduleFocusIndicatorLogoutPrivacy.test.ts:307-309` | Acceptance omits `indicatorNextBlock === null` named in the plan |
| 4 | P3 | `FocusIndicatorHost.test.ts:485-487` | `railStyle(reopened).not.toContain(ROSE)` is vacuous when the snapshot is empty |
| 5 | P3 | `FocusIndicatorHost.test.ts` (~650 lines) | Host suite keeps growing; real-Schedule case correctly split out, but Host privacy cases are near-duplicates |

### 1 (P3): account-switch republish is not a distinct user-2 snapshot

Plan test 2: after refuse, a new publisher may publish again and retained blocks/categories must be **only that distinct user-2 snapshot (not user 1’s)**.

Current seed (`:512-515`) republishes the same `block()` (“Private focus” / `work`) with **categories omitted**, then asserts `categories === []` and rail blue-not-rose. That usefully proves the leftover rose **page** catalogue is not auto-adopted on publish-without-categories, but it does not pin a user-2–shaped title/slug/catalogue distinct from user 1.

Optional tighten: publish a different title/id (and optional user-2 catalogue) and assert `retainedSnapshot()` equals that payload only.

### 2 (P3): catalogue-on-Login proof weakened (acknowledged by plan)

Plan asked rewrites not to weaken catalogue-on-Login proofs; Out of scope also defers hardening so Login-guard tests fail if only the empty-date guard remains.

After removing ungated `publish`, `does not restore retained colours after Login when a new catalogue arrives` (`:461-488`) can no longer re-seed a snapshot **while** `component === "Login"`. It now asserts refuse + empty retained + rose catalogue does not paint. That is the right privacy outcome; the old “retained non-empty on Login → catalogue watcher must not copy” path is unreachable by design. Treat as the plan’s deferred P2, not a regression to reopen here.

### 3 (P3): real-Schedule acceptance missing next-block null

Plan acceptance checklist includes `indicatorNextBlock` null immediately after unmount. The new test asserts PiP close once, `indicatorActive` false, empty `retainedSnapshot()`, stale + current-gen refuse, no public `publish`, and no second open (`:307-319`). Adding `expect(controller!.indicatorNextBlock.value).toBeNull()` would match the plan text; behaviour is already implied by the empty snapshot for this fixture.

### 4 (P3): vacuous rail colour assert on empty Login reopen

After Login refuse, `reopenPip()` + `expect(railStyle(reopened)).not.toContain(ROSE)` (`:485-487`) passes even when `.fi-rail` is absent (`railStyle` returns `""`). Prefer asserting empty retained / `indicatorActive === false` only (already present), or assert the rail node is missing / neutral.

### 5 (P3): Host file size / overlapping Login refuse cases

`FocusIndicatorHost.test.ts` is ~650 lines. `refuses an ungated publish after Login` (`:262-280`) and `returns false from publishIfGenerationMatches after Login with the post-clear generation` (`:301-317`) largely overlap. Real Schedule acceptance correctly lives in its own file. No refactor required for merge; consider consolidating Host refuse cases if the suite grows again.

## Bugs / data alignment

- **No casing / envelope bugs.** Controller and tests use Inertia’s `auth_user_id` (snake_case) and flat `retainedSnapshot()` `{ date, blocks, categories }` — matches the plan, not a nested `{ data: … }` shape.
- **No public `publish` left** in production or tests (grep clean aside from the plan doc).
- **Session gate vs account switch:** refuse is Login / `auth_user_id === null` only; account switch continues to rely on generation bump + clear. Matches plan; fresh post-switch generation may publish again.
- **`undefined` auth_user_id** still does not clear or refuse (only `null`); consistent with existing “missing auth_user_id” catalogue tests and the uninitialized-component rule.
- **Schedule.vue** still captures generation once at setup and fail-closes across in-place identity change until remount — as required.

## Over-engineering / style

- Controller change is small and matches existing patterns (`copiedBlocks` / `copiedCategories`, sync session watcher). File ~247 lines — fine.
- New privacy test file duplicates Host’s Inertia/PiP/composable mocks (heavy but consistent with `scheduleFocusIndicator.test.ts`-style Schedule mounts). Acceptable for isolation; not worth sharing yet.
- OpenSpec proposal/design/tasks are lean and point at the plan — good.
- No weird syntax; TypeScript interface and runtime object stay aligned.

## Unit tests

| Plan red / case | Covered? | Where |
|-----------------|----------|--------|
| Real Schedule + Login unmount emptiness + refuse | ✅ | `scheduleFocusIndicatorLogoutPrivacy.test.ts:251` |
| Ungated `publish` gone after Login / account switch | ✅ | Host `:262`, `:283` (`"publish" in controller === false`) |
| Stale generation refuse after account switch; fresh may publish | ✅ | Host `:283`, `:491` |
| Current-gen refuse after Login (numeric id still present) | ✅ | Host `:301` |
| Null-user alone: clear + PiP close, then current-gen refuse | ✅ | Host `:320` |
| Existing generation / Login / uninitialized-component stay green | ✅ | Pre-existing Host cases retained |
| Authenticated unmount keeps snapshot / PiP | ✅ | Pre-existing Host case |

**Isolation / patterns:** Vitest + VTU; Inertia `usePage` mocked with reactive `page`; fake Document PiP; Schedule composables stubbed in the acceptance file; naming matches Host privacy style; no network; fast.

**Acceptable gaps:** browser Document PiP smoke out of scope per plan; catalogue-Login hardening deferred P2; no distinct user-2 payload assert (P3-1).

## Review Summary

| Severity | Count | Status |
|----------|-------|--------|
| CRITICAL / P1 | 0 | pass |
| HIGH / P2 | 0 | pass |
| MEDIUM / P3 | 5 | note |
| LOW | 0 | — |

Verdict: **APPROVE** — no blocking findings. Optional P3 tightenings only.
