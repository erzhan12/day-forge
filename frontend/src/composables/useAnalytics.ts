import { getCurrentScope, onScopeDispose, ref } from "vue"
import { type ApiResult, requestJson } from "./useHttp"
import { extractErrorMessage } from "../utils/errorMessage"
import { useScheduleRevision, runScheduleMutation, type ScheduleRevisionState } from "./useScheduleRevision"

export function useAnalytics(explicitRevision?: ScheduleRevisionState) {
  const revision = useScheduleRevision(explicitRevision)
  const isMarkingReviewed = ref(false)
  const lastError = ref<string | null>(null)
  let generation = 0
  let userEpoch = 0
  let latestNotesRequest = 0
  const notesQueues = new Map<string, Promise<void>>()

  const notesKey = (date: string, userId?: number) => `${userId ?? "anonymous"}:${date}`

  function resetScope(reason?: string) {
    generation += 1
    if (reason === "user" || reason === "session") userEpoch += 1
    latestNotesRequest += 1
    isMarkingReviewed.value = false
    lastError.value = null
  }
  const unsubscribe = revision?.subscribeScopeReset(resetScope)
  if (getCurrentScope()) onScopeDispose(() => { unsubscribe?.(); resetScope() })

  async function markReviewed(date: string, notes?: string): Promise<ApiResult> {
    if (isMarkingReviewed.value || revision?.busy.value) {
      return { ok: false, code: "schedule_synchronizing", errors: { detail: "Schedule is updating. Wait for it to finish, then try again." } }
    }
    const requestGeneration = generation
    const captured = revision?.capture(date)
    const key = notesKey(date, captured?.userId)
    const previousNotes = notesQueues.get(key)
    let releaseBarrier!: () => void
    const released = new Promise<void>((resolve) => { releaseBarrier = resolve })
    const barrier = previousNotes ? previousNotes.then(() => released) : released
    notesQueues.set(key, barrier)
    void barrier.then(() => { if (notesQueues.get(key) === barrier) notesQueues.delete(key) })
    isMarkingReviewed.value = true
    let result: ApiResult
    try {
      if (previousNotes) await previousNotes
      if (generation !== requestGeneration) return { ok: false, code: "stale" }
      lastError.value = null
      result = await runScheduleMutation(revision, date, (capture) => requestJson(
        `/api/analytics/schedules/${date}/mark-reviewed/`,
        "POST",
        { expected_revision: capture.revision, ...(notes !== undefined ? { notes } : {}) },
        { expectedUserId: capture.userId },
      ), { only: ["review", "streak", "schedule"] })
    } finally {
      releaseBarrier()
      if (generation === requestGeneration) isMarkingReviewed.value = false
    }
    if (generation !== requestGeneration || result.code === "stale") return result
    if (!result.ok) {
      lastError.value = extractErrorMessage(result.errors, "Could not mark this day reviewed.")
    } else if (result.code === "schedule_sync_failed") {
      lastError.value = "Changes were saved, but the display could not refresh. Reload the page."
    }
    return result
  }

  function saveNotes(date: string, notes: string, expectedUserId?: number): Promise<ApiResult> {
    // The path remains valid before a DailyReview row exists. Keep writes for
    // one day and account ordered so an older request cannot overwrite a newer draft.
    const requestGeneration = generation
    const requestUserEpoch = userEpoch
    const requestId = ++latestNotesRequest
    const key = notesKey(date, expectedUserId)
    const previous = notesQueues.get(key)
    const send = async (): Promise<ApiResult> => {
      if (userEpoch !== requestUserEpoch) return { ok: false, code: "stale" }
      const result = await requestJson(`/api/analytics/schedules/${date}/notes/`, "PATCH", { notes }, { expectedUserId })
      const current = generation === requestGeneration && revision?.schedule.value?.date === date
      if (current && (result.code === "session_invalid" || result.status === 401)) {
        revision?.reset("session")
      } else if (current && requestId === latestNotesRequest && !result.ok) {
        lastError.value = extractErrorMessage(result.errors, "Could not save notes.")
      }
      return result
    }
    const operation = previous ? previous.then(send, send) : send()
    const tail = operation.then(() => undefined, () => undefined)
    notesQueues.set(key, tail)
    void tail.then(() => { if (notesQueues.get(key) === tail) notesQueues.delete(key) })
    return operation
  }

  function clearError() { lastError.value = null }

  return { isMarkingReviewed, lastError, markReviewed, saveNotes, clearError }
}
