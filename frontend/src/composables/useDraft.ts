import { ref, type Ref } from "vue"
import { type ApiResult, requestJson } from "./useHttp"
import { extractErrorMessage } from "../utils/errorMessage"
import { useScheduleRevision, runScheduleMutation, isScheduleRevisionConflict, SCHEDULE_CHANGED_MESSAGE, type ScheduleRevisionState } from "./useScheduleRevision"
import { registerMutationUndo } from "./useMutationUndo"
import type { UndoAction } from "../types"

interface DraftSubmitResult extends ApiResult {
  explanation?: string | null
}

interface DraftState {
  isGeneratingDraft: Ref<boolean>
  lastDraftError: Ref<string | null>
  latestRequestId: number
  unsubscribe?: () => void
}

function createDraftState(): DraftState {
  return { isGeneratingDraft: ref(false), lastDraftError: ref<string | null>(null), latestRequestId: 0 }
}

let ownerStates = new WeakMap<ScheduleRevisionState, DraftState>()
let standaloneState = createDraftState()
let lastAccessedState = standaloneState

function stateFor(owner?: ScheduleRevisionState): DraftState {
  if (!owner) return standaloneState
  let state = ownerStates.get(owner)
  if (!state) {
    state = createDraftState()
    ownerStates.set(owner, state)
    state.unsubscribe = owner.subscribeScopeReset((reason) => {
      clearDraftState(state!)
      if (reason === "dispose") {
        state!.unsubscribe?.()
        state!.unsubscribe = undefined
        ownerStates.delete(owner)
        if (lastAccessedState === state) lastAccessedState = standaloneState
      }
    })
  }
  return state
}

function clearDraftState(state: DraftState): void {
  state.latestRequestId += 1
  state.isGeneratingDraft.value = false
  state.lastDraftError.value = null
}

function statusToMessage(status: number | undefined): string | null {
  switch (status) {
    case 409:
      return "Schedule already has blocks. Clear them before regenerating."
    case 422:
      return "No template configured. Open Settings to create one."
    case 429:
      return "Draft rate limit reached. Try again later."
    case 503:
      return "AI is unavailable. Manual editing still works."
    default:
      return null
  }
}

export function useDraft(explicitRevision?: ScheduleRevisionState) {
  const revision = useScheduleRevision(explicitRevision)
  const state = stateFor(revision)
  lastAccessedState = state
  const { isGeneratingDraft, lastDraftError } = state
  /** Drop the current draft UI response without assuming its write was cancelled. */
  function abandonInFlight(): void {
    state.latestRequestId += 1
    isGeneratingDraft.value = false
  }

  async function generateDraft(date: string, pushUndo?: (action: UndoAction) => void): Promise<DraftSubmitResult> {
    if (!revision || revision.busy.value) {
      return { ok: false, code: "schedule_synchronizing", errors: { detail: "Schedule is updating. Wait for it to finish, then try again." } }
    }
    const myId = ++state.latestRequestId
    isGeneratingDraft.value = true
    lastDraftError.value = null

    let result: DraftSubmitResult
    try {
      result = await runScheduleMutation(revision, date, (capture) => requestJson(
        `/api/ai/schedules/${date}/generate-draft/`,
        "POST",
        { expected_revision: capture.revision },
        { expectedUserId: capture.userId },
      ))
    } finally {
      if (myId === state.latestRequestId) {
        isGeneratingDraft.value = false
      }
    }

    if (myId !== state.latestRequestId) {
      return { ok: false, errors: { detail: "stale" } }
    }

    if (result.ok) {
      const explanation =
        typeof result.data?.explanation === "string"
          ? result.data.explanation
          : null
      registerMutationUndo(result, pushUndo, {
        description: explanation || "Generated draft",
        type: "draft",
      })
      if (result.code === "schedule_sync_failed") lastDraftError.value = "Changes were saved, but the display could not refresh. Reload the page."
      return { ...result, explanation }
    }

    if (isScheduleRevisionConflict(result)) {
      lastDraftError.value = SCHEDULE_CHANGED_MESSAGE
      return result
    }

    if (result.status === 409) {
      // Race: schedule already has blocks. Visibility guard upstream
      // should make this nearly impossible; treat as silent no-op.
      return { ok: false, status: 409, errors: result.errors }
    }

    lastDraftError.value =
      statusToMessage(result.status) ??
      extractErrorMessage(result.errors, "Draft generation failed")
    return { ok: false, status: result.status, errors: result.errors }
  }

  function clearDraftError() {
    lastDraftError.value = null
  }

  return {
    isGeneratingDraft,
    lastDraftError,
    generateDraft,
    clearDraftError,
    abandonInFlight,
  }
}

/** Test-only reset — mirrors useChat._resetChatStateForTests. */
export function _resetDraftStateForTests(): void {
  clearDraftState(lastAccessedState)
  lastAccessedState.unsubscribe?.()
  ownerStates = new WeakMap()
  standaloneState = createDraftState()
  lastAccessedState = standaloneState
}

/** Test-only peek at the request counter. */
export function _peekLatestRequestId(): number {
  return lastAccessedState.latestRequestId
}
