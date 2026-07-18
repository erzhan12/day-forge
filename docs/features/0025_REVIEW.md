# Feature 0025 — App logo / favicon: code review

Branch `feature/0025-app-logo`. No `0025_PLAN.md` exists, so plan-conformance
checking was skipped; the change was reviewed on its own merits.

**Scope:** `RULES.md`, `backend/templates/base.html`, `tasks/todo.md`, plus new
untracked `frontend/public/*.png` (7 assets) and `backend/tests/
test_base_template_icons.py` (added during review).

## External review trail

Engines: **codex** (`codex exec --sandbox read-only`) and **cursor agent**
(`agent -p --mode ask`), run in parallel, 4 rounds across two invocations.
Preceded by an internal 2-agent pass (static-asset wiring; docs/tests/
security/perf).

Findings: raised **21** (deduped across engines and rounds) — accepted **12**,
rejected **5**, recorded as accepted gaps **4**. Zero P1 at any point. Final
round: **both engines returned `NO P1/P2 FINDINGS`**.

### Round 1 — accepted and fixed

| Finding | Fix |
|---|---|
| Dev-branch icon hrefs were root-relative (`/favicon.png`), so they 404 when the document is loaded from Django's `:8006` origin directly — a working dev path precisely because the adjacent `@vite/client` script tags are absolute. | `base.html` dev hrefs changed to absolute `http://localhost:5173/...`, matching those script tags. |
| No test covered the dual `vite_dev_mode` branches, despite `RULES.md` naming branch drift as the footgun. Default `StaticFilesStorage` resolves `{% static %}` by string join, so a missing asset cannot fail a build or a test — only a live 404. | Added `backend/tests/test_base_template_icons.py`. |
| `RULES.md` attributed production serving to `STATICFILES_DIRS`, omitting the mandatory `npm run build` and `collectstatic` steps. With `DEBUG=False` WhiteNoise reads only `STATIC_ROOT` (no `WHITENOISE_USE_FINDERS`). | Documented the full chain `public/ → npm run build → dist/ → collectstatic → STATIC_ROOT → WhiteNoise`, plus the non-manifest storage note. |
| `RULES.md` claimed a 2048px logo master; no such file exists anywhere in the repo (largest is `logo-full.png` at 1024×1024). | Claim removed; replaced with an explicit note that no master is committed. |
| `RULES.md` said a new public asset must be added to BOTH template branches, but `icon-192/512` and `logo-full` ship with no links. | Narrowed to assets *referenced from* `base.html`. |

### Rounds 2–3 — accepted and fixed (test quality)

- **`RULES.md` overclaimed what the test enforces** (`sizes`↔filename mapping).
  Resolved by *strengthening the test* rather than weakening the doc: declared
  `sizes` is now checked against each PNG's real IHDR pixel dimensions
  (stdlib `struct`, no Pillow dependency).
- **Vacuous-pass risk**: `LINK_RE` requires `sizes` before `href`, so an
  attribute reorder would zero the matches and let per-link loops pass over an
  empty list. The parse helper now asserts the expected link count, converting
  that failure mode from silent-pass to loud-fail. Verified by mutation —
  breaking the regex makes every link-iterating test fail rather than pass.
- **Set collapse**: `_sizes_and_filenames` deduped into a set, so a branch
  repeating one icon and dropping another could still satisfy count and parity.
  Added a uniqueness assert before the set conversion.
- **`_png_dimensions`** checked the PNG signature but not the `IHDR` tag before
  unpacking. Added.
- **"dimensions machine-verified"** read as a claim about the test while the
  test only covers the four linked icons. Reworded to distinguish the one-time
  manual check of all seven from the four continuously enforced.

### Round 4 — second invocation, fresh pass

Re-run of both engines over the post-round-3 tree, with all eleven prior
findings fed back as out-of-scope and an explicit instruction to hunt for what
earlier rounds missed rather than re-confirm them. **Both engines returned
`NO P1/P2 FINDINGS`.** Four P3s, all accepted as trivially cheap:

- **`rel` was parsed but discarded**, so demoting `apple-touch-icon` to a plain
  `icon` in *both* branches would satisfy parity. `rel` is now part of the
  compared tuple, plus a dedicated assert that exactly one `apple-touch-icon`
  is declared. (codex)
- **Dev href assertion was prefix-only**: `http://localhost:5173/static/x.png`
  would pass, yet Vite serves `publicDir` at the origin root only — and the
  filename extraction (`rsplit("/", 1)[-1]`) hid the nested path from the
  existence check. Both branches now assert the path is a bare filename.
  (cursor)
- **`tasks/todo.md`** read as though the 192/512 PWA icons were linked from
  `base.html`. Reworded to state they ship unlinked. (cursor)
- **This document** claimed the mutation check made "all three per-link tests"
  fail; the suite has grown past three. Corrected above. (cursor)

### Rejected (with evidence)

1. **"Prod `{% static %}` renders path-relative because `STATIC_URL = "static/"`
   lacks a leading slash, so `/accounts/login/` requests
   `/accounts/login/static/favicon.png`."** (codex, P2 — round 2.)
   Factually wrong. Django's `Settings.__init__` normalises `STATIC_URL` via
   `_add_script_prefix`. Verified at runtime: `settings.STATIC_URL == '/static/'`
   and `base.html` renders `href="/static/favicon.png"`. Codex had itself proved
   this in round 1 and contradicted it in round 2. A regression test now pins it.
2. **"The documented dev workflow serves HTML from Django `:8006`, with Vite
   only for JS."** (cursor, P2 — round 1.)
   `.claude/rules/workflows.md:8` explicitly says to browse
   `http://localhost:5173/`; the Makefile `dev` target prints both server
   commands and designates no browse origin. The severity rested on this
   premise, so it dropped to P3 — the underlying href fix was applied anyway,
   since it is one line and matches the adjacent convention.
3. **"Pin a golden `{(sizes, filename), ...}` allowlist in the test."**
   (cursor, P3 — round 3.) Rejected: it duplicates `base.html` into the test and
   drifts. Every intentional icon change would require a test edit for no added
   safety. The invariants that matter — branch parity, real pixel dimensions,
   on-disk existence, href convention — are already enforced.
4. **"`favicon.png` (48) is inconsistent with `favicon-16/32.png`."**
   (cursor, P3 — round 3.) `favicon.png` is the standard default name; renaming
   churns binary assets, template, and docs for cosmetics.
5. **"Wordmark may be used at tiny favicon sizes."** (codex, round 1, self-
   resolved.) Codex inspected the assets and confirmed the favicon source is the
   icon-only anvil crop, no text.

### Accepted gaps (no fix)

- `icon-192.png` / `icon-512.png` ship as "PWA-ready" with no web app manifest
  and no `base.html` link — 106KB of deploy weight, zero page-load cost. Now
  documented explicitly in `RULES.md` as intentional.
- `logo-full.png` (228KB) is unreferenced; available for a login-page header.
- The unlinked 192/512/1024 assets are not covered by the parity test and can
  drift silently. Documented.
- `frontend/public/` is untracked (`??`, not modified), so `git commit -am`
  would skip it and ship `{% static %}` refs with no assets — **404s in
  production only**. Needs an explicit `git add frontend/public/` before commit.
  Not a code defect; called out here because the failure mode is deploy-only
  and silent.

## Verification

`uv run pytest backend/tests/ -q` → **666 passed**.
`uv run ruff check backend/` → **All checks passed**.

## Result

**SUCCESS** — round 4 returned zero P1/P2 from both engines independently, with
tests and lint green. Rounds 2–4 produced only test-quality and doc-wording
nits after round 1's substantive fixes; every accepted item since round 1 has
hardened the icon test rather than changed shipped behaviour.

Outstanding before commit: `frontend/public/` is untracked, so it needs an
explicit `git add frontend/public/` — `git commit -am` would skip it and ship
`{% static %}` references with no assets behind them.
