import { ref, computed, onMounted, onUnmounted } from "vue"
import type { TimeBlock, UndoAction } from "../types"
import { useSchedule } from "./useSchedule"
import { type DateSource, readDate } from "../utils/dateSource"

/**
 * Client-side undo stack for schedule edits.
 *
 * Important: undo state lives entirely in this tab's memory and is never
 * synchronised across browser tabs or devices. Concurrent edits in
 * multiple tabs can silently destroy work:
 *
 *   1. Tab A loads the schedule and snapshots its blocks into the stack.
 *   2. Tab B (same user) makes a separate edit and saves it.
 *   3. The user undoes in Tab A. The undo posts Tab A's snapshot to
 *      `POST /api/schedules/<date>/blocks/restore/`, which atomically
 *      replaces every block on the day — including Tab B's change.
 *      Tab B's edit is gone with no warning.
 *
 * This is acceptable for the single-user MVP. If multi-tab usage becomes
 * common, options to consider: (a) wire the BroadcastChannel API so each
 * tab clears or warns on its stack when another tab mutates the day;
 * (b) add an `If-Match`-style version check to `restore_blocks`; or
 * (c) move the undo stack server-side. None are wired up today.
 */

const MAX_UNDO_STACK = 20
const TOAST_DURATION_MS = 8_000

export function useUndo(
  getCurrentDate: DateSource,
  getCurrentBlocks: () => TimeBlock[],
  isDisabled?: () => boolean,
) {
  const { restoreBlocks } = useSchedule(getCurrentDate)

  const undoStack = ref<UndoAction[]>([])
  const canUndo = computed(() => {
    const currentDate = readDate(getCurrentDate)
    return undoStack.value.some((a) => a.scheduleDate === currentDate)
  })
  const currentToast = ref<{ description: string; actionable: boolean } | null>(null)

  let toastTimer: ReturnType<typeof setTimeout> | null = null
  let undoInFlight = false

  function clearToastTimer() {
    if (toastTimer !== null) {
      clearTimeout(toastTimer)
      toastTimer = null
    }
  }

  function showToast(description: string, actionable: boolean) {
    clearToastTimer()
    currentToast.value = { description, actionable }
    toastTimer = setTimeout(() => {
      currentToast.value = null
      toastTimer = null
    }, TOAST_DURATION_MS)
  }

  function dismissToast() {
    clearToastTimer()
    currentToast.value = null
  }

  function snapshotBlocks(): TimeBlock[] {
    // Shallow spread unwraps Vue's reactive proxy (Inertia wraps page
    // props in a readonly reactive, which structuredClone can't clone
    // — throws DataCloneError). TimeBlock is flat primitives only, so
    // a shallow copy is a full clone.
    return getCurrentBlocks().map((b) => ({ ...b }))
  }

  function pushUndo(action: UndoAction) {
    undoStack.value.push(action)
    if (undoStack.value.length > MAX_UNDO_STACK) {
      undoStack.value.shift()
    }
    // Silent actions stay on the stack but skip the toast (issue #54).
    if (!action.silent) {
      showToast(action.description, true)
    }
  }

  async function performUndo(): Promise<void> {
    if (undoInFlight) return
    if (isDisabled?.()) return

    // The stack accumulates entries across dates — it survives Inertia
    // date navigation. Undo the most recent entry *for the date currently
    // on screen*, never one bound to another day (that would call
    // restore_blocks on a day the user isn't looking at and wipe it).
    // Scanning from the top keeps navigate-back-then-undo working even
    // when a later entry for a different day sits on top of the stack.
    const currentDate = readDate(getCurrentDate)
    let index = -1
    for (let i = undoStack.value.length - 1; i >= 0; i--) {
      if (undoStack.value[i].scheduleDate === currentDate) {
        index = i
        break
      }
    }
    if (index === -1) {
      showToast("Nothing to undo.", false)
      return
    }

    undoInFlight = true
    try {
      const action = undoStack.value[index]
      const blocksPayload = action.previousBlocks.map((b) => ({
        title: b.title,
        start_time: b.start_time,
        end_time: b.end_time,
        category: b.category,
        is_completed: b.is_completed,
        sort_order: b.sort_order,
      }))

      const result = await restoreBlocks(action.scheduleDate, blocksPayload)
      if (result.ok) {
        // Guard the async gap: if the user navigated to another date while
        // the restore was in flight, leave the stack/toast untouched (the
        // entry stays undoable on its own date) so we don't pop an entry —
        // or flash an "Undone" toast — for a day no longer on screen.
        if (readDate(getCurrentDate) !== currentDate) return
        // Re-locate by object identity: `index` was captured before the
        // await, and pushUndo is not gated by undoInFlight — a new action
        // arriving mid-flight can shift() a full stack and stale the index.
        const postAsyncIndex = undoStack.value.indexOf(action)
        if (postAsyncIndex !== -1) undoStack.value.splice(postAsyncIndex, 1)
        showToast(`Undone: ${action.description}`, false)
      } else {
        showToast("Undo failed. Please try again.", false)
      }
    } finally {
      undoInFlight = false
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (!(e.metaKey || e.ctrlKey) || e.key !== "z") return
    if (isDisabled?.()) return

    const target = e.target as HTMLElement
    const tag = target.tagName.toLowerCase()
    if (
      tag === "input" ||
      tag === "textarea" ||
      tag === "select" ||
      target.isContentEditable
    ) {
      return
    }

    e.preventDefault()
    performUndo()
  }

  onMounted(() => {
    document.addEventListener("keydown", handleKeydown)
  })

  onUnmounted(() => {
    document.removeEventListener("keydown", handleKeydown)
    clearToastTimer()
  })

  return {
    undoStack,
    canUndo,
    currentToast,
    pushUndo,
    performUndo,
    snapshotBlocks,
    dismissToast,
  }
}
