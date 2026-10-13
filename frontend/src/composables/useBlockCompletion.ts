import { getCurrentInstance, onUnmounted, ref } from "vue"
import type { TimeBlock, UndoAction } from "../types"
import type { ApiResult, ScheduleRequestOptions } from "./useSchedule"
import { registerMutationUndo } from "./useMutationUndo"

export type CompletionOutcome = "success" | "failure" | "superseded"

interface BlockCompletionDeps {
  updateBlock: (
    id: number,
    data: Record<string, unknown>,
    options?: ScheduleRequestOptions,
  ) => Promise<ApiResult>
  undo?: {
    pushUndo: (action: UndoAction) => void
    snapshotBlocks: () => TimeBlock[]
  }
  isDisabled: () => boolean
}

/** Completion intents are serialized; the schedule controller owns each write. */
export function useBlockCompletion(deps: BlockCompletionDeps) {
  const { updateBlock, undo, isDisabled } = deps
  const saving = ref(false)
  const errorState = ref(false)
  let generation = 0
  let lifetime = 0
  let queueEpoch = 0
  let pending = 0
  let queue: Promise<unknown> | null = null
  let disposed = false

  function setCompleted(
    block: TimeBlock,
    date: string,
    desired: boolean,
  ): Promise<CompletionOutcome> {
    if (disposed || (isDisabled() && !saving.value)) return Promise.resolve("superseded")
    const myGeneration = ++generation
    const myLifetime = lifetime
    const myQueueEpoch = queueEpoch
    const blockId = block.id
    const blockTitle = block.title
    pending++
    saving.value = true
    errorState.value = false

    async function write(): Promise<CompletionOutcome> {
      // A reused row cancels its unsent intents. An already accepted write
      // remains owned by the schedule controller until reconciliation finishes.
      if (disposed || myLifetime !== lifetime || myQueueEpoch !== queueEpoch) return "superseded"
      let result: ApiResult
      try {
        result = await updateBlock(blockId, { is_completed: desired }, { scheduleDate: date })
      } catch {
        // No retry: the server may have committed before the response was lost.
        // useSchedule reconciles this result and keeps the shared owner busy.
        result = { ok: false }
      }
      registerMutationUndo(result, undo?.pushUndo, {
        description: `${desired ? "Checked" : "Unchecked"} "${blockTitle}"`,
        type: "toggle",
        silent: true,
      })
      // Intents collected before a conflict or uncertain result must not be
      // applied to the freshly reconciled external state. A later user click
      // can start a new queue after the owner has finished reconciliation.
      const chainBroken = !result.ok || !result.mutation || result.code === "schedule_reconciled" ||
        result.code === "schedule_sync_failed" || Boolean(result.synchronizationError)
      if (chainBroken) queueEpoch++
      if (disposed || myLifetime !== lifetime) return "superseded"
      if (!result.ok) {
        errorState.value = true
        return "failure"
      }
      if (myGeneration !== generation) return "superseded"
      errorState.value = false
      return "success"
    }

    // Start the first request synchronously; subsequent intents await the
    // complete request/reconciliation lifecycle before acquiring another write.
    const operation = queue ? queue.then(write) : write()
    const settled = operation.finally(() => {
      pending--
      if (myLifetime === lifetime && !disposed) saving.value = pending > 0
      if (queue === settled) queue = null
    })
    queue = settled
    return settled
  }

  function complete(block: TimeBlock, date: string): Promise<CompletionOutcome> {
    return setCompleted(block, date, true)
  }

  function reset(): void {
    lifetime++
    queueEpoch++
    generation++
    saving.value = false
    errorState.value = false
  }

  function dispose(): void {
    disposed = true
    reset()
  }

  if (getCurrentInstance()) onUnmounted(dispose)
  return { saving, errorState, setCompleted, complete, reset, dispose }
}
