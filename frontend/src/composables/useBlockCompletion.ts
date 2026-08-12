import { getCurrentInstance, onUnmounted, ref } from "vue"
import type { TimeBlock, UndoAction } from "../types"
import type { ApiResult } from "./useSchedule"

// Module scope: shared across every call-site instance (pure constants, no
// per-instance state). All failures retry (including 4xx) — accepted tradeoff:
// a genuine validation 4xx pays the full 4.3s backoff before the error
// surfaces. (Lifted verbatim from the pre-refactor TimeBlock.vue.)
const TOGGLE_RETRY_DELAYS_MS = [300, 1000, 3000] as const
const sleep = (ms: number) => new Promise<void>((r) => setTimeout(r, ms))

/** Terminal outcome of a completion chain (see 0049 plan § Outcome contract). */
export type CompletionOutcome = "success" | "failure" | "superseded"

interface BlockCompletionDeps {
  updateBlock: (
    id: number,
    data: Record<string, unknown>,
    options?: { signal?: AbortSignal },
  ) => Promise<ApiResult>
  undo?: {
    pushUndo: (action: UndoAction) => void
    snapshotBlocks: () => TimeBlock[]
  }
  isDisabled: () => boolean
}

/**
 * Shared block-completion controller. **Per-call-site factory, NOT a
 * singleton** — every call returns a fresh, independent state bundle. The
 * retry/backoff loop, generation-guard, abort-on-supersede, and silent-undo
 * logic live here (one module → the timeline checkbox and the PiP indicator
 * cannot diverge); each call site owns its own reactive state so per-row
 * spinners and the abort-on-list-reshape invariant (issue #21) are preserved.
 */
export function useBlockCompletion(deps: BlockCompletionDeps) {
  const { updateBlock, undo, isDisabled } = deps

  const saving = ref(false)
  const errorState = ref(false)
  const generation = ref(0)
  let toggleAbort: AbortController | null = null

  async function setCompleted(
    block: TimeBlock,
    date: string,
    desired: boolean,
  ): Promise<CompletionOutcome> {
    if (isDisabled()) return "superseded"

    // Abort any in-flight PATCH so a slow superseded write is less likely to
    // commit after a newer toggle. Best-effort guard, not a distributed
    // ordering guarantee.
    toggleAbort?.abort()
    const ac = new AbortController()
    toggleAbort = ac
    const myGen = ++generation.value
    errorState.value = false
    saving.value = true

    const snapshot = undo?.snapshotBlocks()
    // Capture the block's object properties live at mutation start (see issue
    // #21): a mid-backoff list reshape must not retarget the PATCH or mislabel
    // the undo. (`date` is a primitive param — already captured by value.)
    const blockId = block.id
    const blockTitle = block.title

    for (let attempt = 0; attempt < TOGGLE_RETRY_DELAYS_MS.length + 1; attempt++) {
      let result: ApiResult | { ok: false }
      try {
        result = await updateBlock(blockId, { is_completed: desired }, { signal: ac.signal })
      } catch (err) {
        // Superseding toggle aborted this chain — bail without touching state.
        if (err instanceof DOMException && err.name === "AbortError") return "superseded"
        result = { ok: false }
      }
      // Newer toggle (or dispose/reset) superseded this chain — bail cleanly.
      if (myGen !== generation.value) return "superseded"
      if (result.ok) {
        if (undo && snapshot) {
          // Label from the value this chain writes, not a captured prop: a
          // rapid re-toggle can leave the prop stale and mislabel the action.
          const action = desired ? "Checked" : "Unchecked"
          undo.pushUndo({
            description: `${action} "${blockTitle}"`,
            type: "toggle",
            previousBlocks: snapshot,
            scheduleDate: date,
            silent: true,
          })
        }
        saving.value = false
        return "success"
      }
      if (attempt < TOGGLE_RETRY_DELAYS_MS.length) {
        await sleep(TOGGLE_RETRY_DELAYS_MS[attempt])
        if (myGen !== generation.value) return "superseded"
      }
    }

    // Retries exhausted. (No post-loop generation re-check: the final iteration
    // has no async boundary between the in-loop guard at :78 and here, so
    // `generation` cannot change — a reset/dispose mid-await is already caught
    // by that guard.)
    saving.value = false
    errorState.value = true
    return "failure"
  }

  function complete(block: TimeBlock, date: string): Promise<CompletionOutcome> {
    return setCompleted(block, date, true)
  }

  /**
   * Identity-change reset (reused row / active block swap): abort the in-flight
   * chain AND clear `saving`/`errorState` so the prior block's spinner/error
   * never sticks on the next block. Mirrors TimeBlock.vue's `block.id` watcher.
   */
  function reset(): void {
    toggleAbort?.abort()
    generation.value++
    saving.value = false
    errorState.value = false
  }

  /**
   * Unmount disposal: abort + bump generation ONLY (no state clear — the
   * call-site is gone). A late resolve then bails `"superseded"` and cannot
   * `pushUndo`. Mirrors TimeBlock.vue's `onUnmounted`.
   */
  function dispose(): void {
    toggleAbort?.abort()
    generation.value++
  }

  if (getCurrentInstance()) onUnmounted(dispose)

  return { saving, errorState, setCompleted, complete, reset, dispose }
}
