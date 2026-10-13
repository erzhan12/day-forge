import { computed, provide, watch } from "vue"
import type { Schedule, TimeBlock } from "../types"
import { useSchedule } from "./useSchedule"
import { provideScheduleRevision } from "./useScheduleRevision"
import { useUndo } from "./useUndo"
import { useChat } from "./useChat"
import { useDraft } from "./useDraft"
import { ScheduleDisabledKey, ScheduleUndoKey } from "./scheduleContext"

export interface SchedulePageControllerOptions {
  getDate: () => string
  getSchedule: () => Schedule
  getBlocks: () => TimeBlock[]
  getUserId: () => number | null | undefined
  getTimeZone: () => string
  getAutoDraftPending: () => boolean | undefined
  getMutationsDisabled?: () => boolean
}

/** Owns the page's canonical writer, undo history, and AI request lifecycle. */
export function useSchedulePageController(options: SchedulePageControllerOptions) {
  const {
    getDate, getSchedule, getBlocks: getInitialBlocks, getUserId,
    getTimeZone, getAutoDraftPending, getMutationsDisabled,
  } = options
  const scheduleRevision = provideScheduleRevision(getDate, getSchedule, {
    getContextKey: getTimeZone,
    getBlocks: getInitialBlocks,
    getUserId,
  })
  const canonicalBlocks = computed(() => scheduleRevision.blocks.value)
  const canonicalSchedule = computed(() => scheduleRevision.schedule.value)
  const getBlocks = () => canonicalBlocks.value
  const { reorderBlocks, updateBlock } = useSchedule(getDate, scheduleRevision)
  const { isGeneratingDraft, lastDraftError, generateDraft, abandonInFlight } = useDraft(scheduleRevision)
  const { setActiveDate: setChatActiveDate, isProcessing: isChatProcessing } = useChat(scheduleRevision)
  const scheduleDisabled = computed(() => scheduleRevision.busy.value || Boolean(getMutationsDisabled?.()))
  provide(ScheduleDisabledKey, scheduleDisabled)

  const {
    currentToast, pushUndo, performUndo, snapshotBlocks, dismissToast,
  } = useUndo(getDate, getBlocks, () => scheduleDisabled.value, scheduleRevision)
  provide(ScheduleUndoKey, { pushUndo, snapshotBlocks })

  const attemptedAutoDraftDates = new Set<string>()
  let lastUserId = getUserId()
  watch([getDate, getTimeZone, getUserId], ([date, , userId]) => {
    if (userId !== lastUserId) {
      attemptedAutoDraftDates.clear()
      lastUserId = userId
    }
    setChatActiveDate(date)
    abandonInFlight()
    dismissToast()
  }, { immediate: true })

  async function runDraft() {
    return generateDraft(getDate(), pushUndo)
  }
  function handleRegenerateClick() {
    void runDraft()
  }
  function maybeGenerateDraft() {
    const date = getDate()
    if (!getAutoDraftPending() || canonicalBlocks.value.length !== 0 || attemptedAutoDraftDates.has(date)) return
    attemptedAutoDraftDates.add(date)
    void runDraft()
  }
  watch(() => [getDate(), getUserId(), getAutoDraftPending(), canonicalBlocks.value.length] as const,
    maybeGenerateDraft, { immediate: true })

  function resetSession() {
    scheduleRevision.reset("session")
  }

  return {
    scheduleRevision, canonicalBlocks, canonicalSchedule, getBlocks,
    reorderBlocks, updateBlock,
    isGeneratingDraft, lastDraftError, generateDraft, abandonInFlight,
    isChatProcessing, scheduleDisabled,
    currentToast, pushUndo, performUndo, snapshotBlocks, dismissToast,
    runDraft, handleRegenerateClick, resetSession,
  }
}
