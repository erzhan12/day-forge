# Issue #102 — Frontend prod lockfile refresh + CI audit gate — Review trail

## Change surface
- `.github/workflows/deploy.yml` — new "Frontend prod audit" step (`npm audit --omit=dev --audit-level=high`) in the `test` job, between `npm ci` and type-check/tests.
- `frontend/package-lock.json` — transitive prod bumps: axios 1.14.0→1.18.1, form-data 4.0.5→4.0.6, follow-redirects 1.15.11→1.16.0, postcss 8.5.8→8.5.24, qs 6.15.0→6.15.3. No major bumps; `package.json` unchanged.

## External review trail

**Engines:** codex (`gpt-5.6-sol`, read-only) + cursor (`agent`, ask mode). Both parallel.
**Iterations:** 1 (converged).

### Findings

| # | Engine | Sev | Location | Verdict |
|---|---|---|---|---|
| 1 | both | P3 | `deploy.yml:48` | ACCEPTED-GAP (by design) — audit hits npmjs advisory endpoint at deploy time; an outage or a newly-disclosed high advisory in an already-shipped dep fails `test` and blocks all main deploys incl. backend-only. Intended fail-closed tradeoff; no escape hatch added. |
| 2 | cursor | P3 | `deploy.yml:48` | ACCEPTED-GAP (by design) — `--audit-level=high` does not gate moderate regressions. Matches issue #102 policy (moderate-only must not wedge deploys). |

**P1/P2 raised:** 0. **Rejected:** 0. **P3 ignored (non-blocking):** 2.

Cursor verification log confirmed independently: audit step placement, fail-closed flags, `package.json` direct deps unchanged (`@inertiajs/vue3 ^2.0`, `vue ^3.5`), all 5 resolved versions in-range for Inertia 2.3.18 / Vue 3.5.32, single hoisted copy per package (no nested vulnerable trees), postcss reachable via prod `vue → @vue/compiler-sfc` (so correctly in prod-audit scope).

## Verification
- `npm audit --omit=dev --audit-level=high` → exit 0 (0 vulns).
- `npm ci` → OK (lockfile ↔ package.json in sync).
- `npm run type-check` → clean. `npm test` → 664 passed (57 files). `npm run build` → OK.
- Backend untouched → no ruff/pytest impact.

**Result:** SUCCESS — zero valid P1/P2, verification green.
