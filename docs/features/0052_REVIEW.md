# 0052 — Review trail

Feature: add the documented backend Ruff gate (`uv run ruff check backend/`)
as a required step in the `test` job of `.github/workflows/deploy.yml`
(issue #137).

## External review trail (ext-code-review)

- **Engines:** codex (`gpt-5.6-sol`, read-only). Cursor dropped — account
  usage cap (`ActionRequiredError: You're out of usage`), same limit that
  ended it during the earlier ext-plan-review; not recoverable in-session.
- **Iterations:** 1/10.
- **Findings:** raised 0 P1/P2, accepted 0, rejected 0, P3-ignored 0.
  Codex output `NO P1/P2 FINDINGS` after verifying: exact command match to
  README:108, valid YAML (`ruby_yaml_parse: ok`), step positioned after
  `uv sync --frozen` and before `Run backend tests`, `needs:` chain intact.
- **Fixes applied:** none required.
- **Verification:** `uv run ruff check backend/` → exit 0 ("All checks
  passed!"); YAML parses. No Python/app code changed, so no pytest delta.

## Plan-review trail (ext-plan-review, pre-implementation)

- Codex raised 2 P2 on the plan, both accepted + fixed:
  1. Plan proposed observing the gate via a throwaway-branch push, but
     `deploy.yml` triggers only on `push:[main]` + `workflow_dispatch` — a
     non-main branch push triggers nothing. Corrected to a
     `workflow_dispatch`-based observation with a trigger-constraint note.
  2. Red/green ordering was impossible (observe the CI lint step fail
     before adding it). Reordered so the CI-level observation lives in
     Green after the step exists; local non-zero exit is the authoritative
     RED proof.

## Local verification (RED → GREEN)

- RED: introduced a transient `F401` (`import os`) under `backend/` →
  `uv run ruff check backend/` reported "Found 1 error" (non-zero).
- GREEN: removed the probe, added the `Run backend lint` step → ruff exit 0,
  YAML valid, README↔CI command parity confirmed (README:108 identical).

**Result:** SUCCESS — ready to ship.
