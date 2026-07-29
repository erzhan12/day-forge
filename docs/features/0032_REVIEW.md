# 0032 — Block checkbox optimistic sync: Code Review Trail

Feature: fix issue #104 — a time-block completion checkbox stays visually flipped
after a failed PATCH, desyncing UI from server.

## External review trail (ext-code-review)

- **Engines:** codex (`gpt-5.6-sol`, read-only) + cursor `agent` (ask mode), both per round.
- **Rounds:** 3 iterations. Every finding verified in-code before accept/reject; all
  fixes applied in the main session, re-verified after each round.
- **Final verification:** `npx vitest run` — 677/677 pass (57 files); `npx vue-tsc
  --noEmit` clean. Backend untouched (no ruff surface).

### Round 1 — 2 valid P1/P2 fixed, 1 rejected, plus P3s

| Finding | Engines | Verdict | Action |
|---|---|---|---|
| Retry loop reads live `props.block.id`; `Schedule.vue :key="idx"` → mid-backoff row reuse PATCHes wrong block | codex (P1) + cursor (P2) | **ACCEPT** | Capture `blockId` at chain start |
| Rapid re-toggle: undo label from stale `serverValue` → wrong "Checked"/"Unchecked" | codex (P2) | **ACCEPT** | Label derives from `desired`; drop `serverValue` |
| Non-`AbortError` rejection rethrown → stuck `saving`, no revert (`useHttp` reads body outside try/catch) | codex (P2) | **ACCEPT** | Catch → treat as failed attempt (retry then revert) |
| Abort doesn't cancel server-side write; superseded PATCH can commit after newer | codex + cursor (P2) | **REJECT** | Inherent distributed-ordering property, accepted best-effort per plan; misleading code comment corrected |
| No `useSchedule` unit test for `{signal}` forwarding | both (P3) | accepted gap | one-line pass-through, indirectly covered by component test |
| Compact-branch checkbox untested | both (P3) | **ACCEPT** | Added compact-branch toggle test |
| Plan doc says revert to `serverValue`, code uses live prop | codex (P3) | **ACCEPT** | Added implementation note to plan |

Also added tests round 1: unmount-mid-flight (skips undo), live-prop revert.

### Round 2 — 3 valid P2 fixed, plus P3s

| Finding | Engines | Verdict | Action |
|---|---|---|---|
| `is_completed` watcher unconditionally overwrites `displayedCompleted` → older chain's late reload clobbers newer optimistic value | codex (P2) | **ACCEPT** | `saving`-guard the watcher |
| Index-keyed instance reuse leaves optimistic checked / saving spinner / error on the wrong block ~4.3s | codex + cursor (P2) | **ACCEPT** | New `props.block.id` watcher: abort + `generation++` + re-align UI |
| Checkboxes not natively `:disabled` when `scheduleDisabled` → native click flips control with no revert (same desync class) | codex (P2) | **ACCEPT** | `:disabled="disabled"` on both inputs |
| Undo description uses live `props.block.title` after prop swap | cursor (P3) | **ACCEPT** | Capture `blockTitle` at chain start |
| Test comment stale line ref; assert `saving` on optimistic path | cursor (P3) | **ACCEPT** | Fixed comment; added `saving` assertion |

Root-cause `Schedule.vue :key="idx"` re-keying was **rejected** as out-of-scope (a
pre-existing architectural choice affecting all block UI incl. drag/animations); the
instance-reuse symptom is mitigated in-component via the id watcher.

Tests added round 2: id-reuse abort+reset, no-clobber-on-stale-reload, disabled-state.

### Round 3 — converged

- **codex: NO P1/P2 FINDINGS. cursor: NO P1/P2 FINDINGS.**
- Remaining P3s (doc/comment drift only, non-blocking): plan describes the old
  unconditional watcher; RULES omits the two watchers; a stale `onUnmounted` line ref
  in a test comment. All three reconciled (plan divergence notes, RULES entry
  expanded, comment de-referenced).

**Result: SUCCESS** — zero valid P1/P2, tests + type-check green.
