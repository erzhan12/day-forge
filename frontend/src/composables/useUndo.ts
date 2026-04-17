import { ref, computed, onMounted, onUnmounted } from "vue"
import type { TimeBlock, UndoAction } from "../types"
import { useSchedule } from "./useSchedule"

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

export function useUndo(date: string, getCurrentBlocks: () => TimeBlock[]) {
  const { restoreBlocks } = useSchedule(date)

  const undoStack = ref<UndoAction[]>([])
  const canUndo = computed(() => undoStack.value.length > 0)
  const currentToast = ref<{ description: string; actionable: boolean } | null>(null)

  let toastTimer: ReturnType<typeof setTimeout> | null = null

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
    showToast(action.description, true)
  }

  async function performUndo(): Promise<void> {
    if (undoStack.value.length === 0) return

    const action = undoStack.value[undoStack.value.length - 1]
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
      undoStack.value.pop()
      showToast(`Undone: ${action.description}`, false)
    } else {
      showToast("Undo failed. Please try again.", false)
    }
  }

  function handleKeydown(e: KeyboardEvent) {
    if (!(e.metaKey || e.ctrlKey) || e.key !== "z") return

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
