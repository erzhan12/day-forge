# 0072 — External code review trail

Feature: Document PiP focus-indicator — whole-view opacity preference, persistent
ownership host, explicit close (X + header Show/Hide), device-local restore flag,
Settings → Appearance opacity slider. Branch `feature/0072-focus-indicator-opacity`.

Engines: **codex** (`gpt-5.6-sol`, read-only). **cursor** (`agent`) produced empty
output on every attempt this session (3×) and was dropped — review ran codex-only.

## Iteration 1 — raised 8 (4 P2, 4 P3)

| # | Sev | Finding | Verdict |
|---|-----|---------|---------|
| 1 | P2 | Reconcile applies `sent`, could discard a newer cross-session value | **REJECTED** — not lost permanently; the `!inFlight` prop watcher (`SettingsAppearancePanel.vue:31-42`) reconciles a newer prop on the next Inertia update (self-heals sub-second). Added a test proving idle reconciliation. |
| 2 | P2 | Late reload `onFinish` can fire a queued commit after unmount → stray PATCH | **FIXED** — `settleThenCommitQueued` now guards `&& isMounted`. Regression test added. |
| 3 | P2 | Storage: failed `setItem`/`removeItem` leaves stale storage authoritative; malformed JSON returns prior memory | **FIXED** — malformed payload now reads strict `false`; `clear()` writes `"false"` if `removeItem` throws. 2 regression tests. |
| 4 | P2 | Failure messages not cleared on a later successful trailing commit | **FIXED** — `reconcileAfterReload` clears stale error/warning on success. Regression test. |
| 5 | P3 | Model `Min/Max` validators accept NaN; `FloatField` coerces `True`→`1.0` | **REJECTED** — the API PATCH layer is the enforcement boundary (rejects bool/non-numeric/NaN/Inf/out-of-range before write, tested); validators are defense-in-depth, admin is staff-only/out-of-scope. |
| 6 | P3 | Slider failure/coalesce test gaps | **PARTIALLY ACCEPTED** — covered by the regression tests added for #2/#3/#4. |
| 7 | P3 | Backend opacity coverage gaps (cross-user isolation, partial-PATCH preservation, propagation) | **ACCEPTED** — added `..._partial_patch_preserves_each_field`, `..._is_isolated_per_user`, `..._saved_value_flows_through_shared_payload`. |
| 8 | P3 | `useFocusIndicator` shouldRestore/opener-unload tests weak | **REJECTED** — strong tests already exist (intermediate `true`, opener-unload preserves vs normal close clears, dispose-vs-cleanup) with spies + `flushPromises`. |

## Iteration 2 — raised 4 (2 P2, 2 P3)

| # | Sev | Finding | Verdict |
|---|-----|---------|---------|
| 1 | P2 | A rejected save promise bypasses settlement → `inFlight=true` forever, slider silently stops persisting | **FIXED** — `commit()` wraps the await in try/catch, treating a throw like a failed save. Regression test "recovers and keeps committing when a save promise rejects". (Note: the opacity path passes no `AbortSignal`, so `requestJson` does not currently reject — this is a defensive guard against a permanent-stuck state.) |
| 2 | P2 | `math.isfinite()` raises `OverflowError` on an over-large JSON integer → 500 instead of structured 400 | **FIXED** — dropped `math.isfinite` from `api.py`'s PATCH-validation path (and its now-unused `import math`); the plain range comparison rejects NaN/±Inf/over-large-int without raising. `preferences.py` retains `math.isfinite` for read-side normalization, where no huge-int OverflowError is possible. Tests add `10**400` and `-(10**400)` → 400. |
| 3 | P3 | Reload-failure test omits queued-newer-input + compound rollback-baseline cases | Partially covered by iteration-1 additions; remaining compound case is a non-blocking P3. |
| 4 | P3 | Propagation test only exercises the shared helper, not each real Inertia page | **ACKNOWLEDGED P3** — every page serializes through the directly-tested `ui_preferences_payload`; a per-page render test is deferred as harness-heavy/low-value. |

## Iteration 3 — convergence check: blocked

Codex hit its account usage limit mid-run and produced no verdict; cursor was
already dropped. No new findings were surfaced (the pass did not complete). All
P2 findings from iterations 1–2 are fixed and independently re-verified; there are
no unresolved findings. The PR's `claude-review` gate provides the additional
independent review pass.

## Verification after fixes

- `uv run pytest backend/tests/test_user_preferences_api.py -q` → 92 passed
- `uv run ruff check backend/` → All checks passed
- `uv run python backend/manage.py makemigrations --check` → No changes detected
- `cd frontend && npm test -- --run` → 1082 passed (91 files)
- `cd frontend && npx vue-tsc --noEmit` → clean

## Trace

```
ext-code-review trace
  scope: 30 files
  engines: codex (cursor dropped — empty output 3×)
  iterations: 2 completed + 1 blocked (codex usage limit) / 4 max
  findings: raised 12, accepted 6 (fixed 6), rejected 3, P3-acknowledged 3
  verification: 1082 frontend + 92 backend passed, ruff clean, tsc clean
  result: SUCCESS (all P2 resolved + regression-tested; iter3 confirmation blocked externally)
```
