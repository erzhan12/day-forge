# 0076 — SSH host-key pin: review trail

Feature: pin the production Deploy workflow's SSH host key, remove `ssh-keyscan`
TOFU (issue #194). Plan: `docs/features/0076_PLAN.md`.

## External review trail (codex gpt-5.6-sol + cursor)

Scope: `.github/workflows/deploy.yml`, `deployment/README.md` (GitHub Actions YAML +
docs only — no backend/frontend source; pytest/vitest/vue-tsc/build not applicable).
Verification surface: YAML validity (`ruby -ryaml`) + shell/fail-closed correctness +
per-line `StrictHostKeyChecking=yes` joint assertion.

**Iter 1** — workflow verified clean by both engines (keyscan removed; fail-closed Pin
step; all 5 ssh/scp carry `StrictHostKeyChecking=yes` + `UserKnownHostsFile`; valid
YAML). Doc findings accepted & fixed:
- **ACCEPT (P2, codex + cursor)** — fingerprint verification re-scanned the host
  separately from the line that gets pasted → the exact pasted key was never
  fingerprinted (intermittent-MITM gap). Fixed: capture once to
  `/tmp/dayforge_known_hosts`, fingerprint that file, paste that same file.
- **ACCEPT (P2, codex)** — rotation omitted `sshd` reload + lockout window. Fixed:
  ordered steps with `ssh-keygen -A` + `systemctl restart ssh` and an explicit
  fail-closed lockout-window note.
- **ACCEPT (P3, cursor)** — "two fingerprints must match" compared full lines whose
  comment fields differ. Fixed: compare only the `SHA256:` field.

**Iter 2** — workflow re-confirmed clean. One accepted finding (self-introduced in
iter 1):
- **ACCEPT (P2 cursor / P3 codex)** — default capture scanned `ed25519,ecdsa,rsa` but
  verified only ed25519, then "paste exact contents" pasted the unverified ECDSA/RSA
  lines → reintroduced the TOFU gap, contradicting the ed25519-only recommendation.
  Fixed: default flow is now Ed25519-only end to end (capture `-t ed25519` → fingerprint
  → paste the single verified line); ECDSA/RSA are an explicit opt-in requiring per-line
  `SHA256:` verification before paste.

**Iter 3** — both engines: NO P1/P2, full MATCH verification across workflow + docs.

Result: **SUCCESS** — zero valid P1/P2, YAML valid.

## Local staged review (pre-external)

- Workflow: clean (shell fail-closed under `bash -e`, all 5 invocations pinned, ordering
  correct, no secret-interpolation hazard).
- Docs: one WARNING (fingerprint-verify step implicitly needs on-droplet/console access)
  → clarified.
