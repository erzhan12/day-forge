import { ref, computed, onMounted, onUnmounted } from "vue"
import type { TimeBlock, UndoAction } from "../types"
import { useSchedule } from "./useSchedule"

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
    // structuredClone is ~2× faster than JSON round-trip and handles
    // more types (Dates, Sets, Maps) that we don't currently use but
    // might in the future. Available in all modern browsers (Chrome
    // 98+, Firefox 94+, Safari 15.4+) and Node 17+, which covers our
    // Vite build target and the Vitest/jsdom test environment.
    return structuredClone(getCurrentBlocks())
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
