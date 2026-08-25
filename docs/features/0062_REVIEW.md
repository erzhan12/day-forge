# Feature 0062 — External Code Review Trail

Feature: AI quick-input suggestion chips send immediately on click instead of prefilling (issue #168).
Plan: `docs/features/0062_PLAN.md`.

## External review trail

**Engines:** codex (`gpt-5.6-sol`, read-only) + cursor (`agent --mode ask`).
**Rounds:** 1.
**Change surface:** `frontend/src/components/CommandBar.vue`, `frontend/src/components/ChatResultChip.vue`, `frontend/tests/CommandBar.test.ts`, `frontend/tests/chatResultChip.test.ts`.

### Findings

- **codex:** NO P1/P2, no P3.
- **cursor:** NO P1/P2. Three P3s, all non-blocking, none fixed (recorded as accepted gaps):
  1. `CommandBar.test.ts:190-194` draft-discard asserts `pushUndo` as `expect.any(Function)` rather than identity. Accepted gap — the `pushUndo` identity is already locked by the sibling send-on-click test (`:169-173`); `mount4a` does not expose the fn, so tightening would require threading a captured `pushUndo` through the helper for redundant coverage.
  2. `CommandBar.test.ts:269-285` height-restore assertion is weakly load-bearing (`onMounted autosize()` may already set the variant minimum, so the `20px`/`120px` check can pass without the post-submit `autosize()`). Accepted — `textarea.value === ""` is the load-bearing clear assertion by design; the height value is secondary.
  3. `CommandBar.vue:255` chip listener `(text: string) => void submitSuggestion(text)` uses an inline typed arrow / `void` floating-promise guard. Accepted — matches the existing `void` floating-promise pattern; style-only, not a defect.

### Previously-rejected (carried from plan-debate, fed to engines, not re-raised)

- Double-submit / second-chip-click race — `submitTurn` sets `isProcessing=true` synchronously (`useChat.ts:176`) before its first await; both guards catch subsequent calls; real clicks are macrotasks; identical to preexisting Enter path.
- "VTU `trigger()` fires @click on disabled button" — backwards; `trigger()` skips disabled via `!this.isDisabled()` (`vue-test-utils.esm-bundler.mjs:7294`).

### Verification

- `npm test -- tests/CommandBar.test.ts tests/chatResultChip.test.ts` → 59 passed.
- `npx vue-tsc --noEmit` → clean (exit 0).

**Result:** SUCCESS — zero valid P1/P2, tests + typecheck green.
