import { ref, computed, onMounted, onUnmounted } from "vue"
import type { TimeBlock, UndoAction } from "../types"
import { useSchedule } from "./useSchedule"
import { useScheduleRevision, type ScheduleRevisionState } from "./useScheduleRevision"
import { clearAppliedResultForUndo } from "./useChat"
import { type DateSource, readDate } from "../utils/dateSource"

// Each entry belongs to a confirmed revision. Only a successful contiguous
// restore chain may move the next entry to the newly committed revision.

const MAX_UNDO_STACK = 20
const TOAST_DURATION_MS = 8_000

// Most-recent stack index whose action targets `date`, or -1. Single source
// for the date-match rule shared by `canUndo` and `performUndo` — keep them
// in sync (a divergence shows an enabled Undo that then says "Nothing to
// undo" on click).
function findLastIndexForDate(stack: UndoAction[], date: string): number {
  for (let i = stack.length - 1; i >= 0; i--) {
    if (stack[i].scheduleDate === date) return i
  }
  return -1
}

export function useUndo(
  getCurrentDate: DateSource,
  getCurrentBlocks: () => TimeBlock[],
  isDisabled?: () => boolean,
  revision?: ScheduleRevisionState,
) {
  const owner = useScheduleRevision(revision)
  const { restoreBlocks } = useSchedule(getCurrentDate, owner)

  const undoStack = ref<UndoAction[]>([])
  const canUndo = computed(
    () =>
      findLastIndexForDate(undoStack.value, readDate(getCurrentDate)) !== -1,
  )
  const currentToast = ref<{ description: string; actionable: boolean } | null>(null)

  let toastTimer: ReturnType<typeof setTimeout> | null = null
  let undoInFlight = false
  let scopeEpoch = 0

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

  function clearDate(date: string) {
    undoStack.value = undoStack.value.filter((action) => action.scheduleDate !== date)
    if (readDate(getCurrentDate) === date) dismissToast()
  }
  const unsubscribeInvalidation = owner?.subscribeInvalidation((date) => clearDate(date))
  const unsubscribeScope = owner?.subscribeScopeReset((reason) => {
    scopeEpoch += 1
    dismissToast()
    if (reason !== "date") undoStack.value = []
  })

  function pushUndo(action: UndoAction) {
    // Missing result metadata cannot safely be reconstructed from the latest
    // GET. In particular, it may belong to a different user or late request.
    if (!Number.isSafeInteger(action.expected_revision) || !Number.isSafeInteger(action.previous_revision)) return
    if (owner && (action.scheduleDate !== readDate(getCurrentDate) || owner.revision.value !== action.expected_revision)) return
    if (owner && action.generation !== undefined && owner.capture(action.scheduleDate)?.generation !== action.generation) return
    const last = findLastIndexForDate(undoStack.value, action.scheduleDate)
    if (last !== -1 && undoStack.value[last].expected_revision !== action.previous_revision) clearDate(action.scheduleDate)
    undoStack.value.push({ ...action, previousBlocks: action.previousBlocks.map((block) => ({ ...block })) })
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
    const index = findLastIndexForDate(undoStack.value, currentDate)
    if (index === -1) {
      showToast("Nothing to undo.", false)
      return
    }

    undoInFlight = true
    const requestEpoch = scopeEpoch
    try {
      const action = undoStack.value[index]
      const blocksPayload = action.previousBlocks.map((b) => ({
        id: b.id,
        title: b.title,
        start_time: b.start_time,
        end_time: b.end_time,
        category: b.category,
        is_completed: b.is_completed,
        sort_order: b.sort_order,
        restore_proof: b.restore_proof,
      }))

      const result = await restoreBlocks(action.scheduleDate, blocksPayload, action.expected_revision)
      // Re-locate by object identity: `index` was captured before the await,
      // and pushUndo is not gated by undoInFlight — a new action arriving
      // mid-flight can shift() a full stack and stale the index.
      const postAsyncIndex = undoStack.value.indexOf(action)
      const sameScope = requestEpoch === scopeEpoch && readDate(getCurrentDate) === currentDate
      if (result.ok) {
        // The restore succeeded, so the entry is spent — remove it whether
        // or not the user is still on this date. But only flash the "Undone"
        // toast when they're still viewing the day it applied to; if they
        // navigated away mid-flight, a toast on the new day is misleading.
        if (postAsyncIndex !== -1) undoStack.value.splice(postAsyncIndex, 1)
        const priorIndex = findLastIndexForDate(undoStack.value, action.scheduleDate)
        const newRevision = result.mutation?.expectedRevision
        if (sameScope && priorIndex !== -1) {
          const prior = undoStack.value[priorIndex]
          if (newRevision !== undefined && prior.expected_revision === action.previous_revision) {
            prior.expected_revision = newRevision
          } else {
            clearDate(action.scheduleDate)
          }
        }
        if (sameScope && action.type === "ai") clearAppliedResultForUndo(owner)
        if (sameScope) {
          showToast(`Undone: ${action.description}`, false)
        }
      } else if (sameScope) {
        if (result.code === "schedule_changed" || result.status === undefined || (result.status ?? 0) >= 500) clearDate(currentDate)
        // Same rule for the failure toast: don't surface it on a day the
        // user has since navigated to (the date watcher cleared any toast).
        showToast(result.code === "schedule_changed"
          ? "Schedule changed. Review the refreshed schedule before undoing."
          : "Undo failed. Please try again.", false)
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
    unsubscribeInvalidation?.()
    unsubscribeScope?.()
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
