// Shared chat state belongs to the current schedule owner. Replacing the
// owner or ending its session clears the transcript, input, and request tokens.
// UI cancellation drops a reply; the mutation owner still settles its write.

import { computed, ref, type Ref } from "vue"
import type { TimeBlock, UndoAction } from "../types"
import {
  isScheduleChangedConflict,
  SCHEDULE_CHANGED_RETRY_MESSAGE,
} from "../utils/aiScheduleConflict"
import { type ApiResult, requestJson } from "./useHttp"
import { registerMutationUndo } from "./useMutationUndo"
import { clearChatRequests, readChatRequest, removeChatRequest, storeChatRequest, type PendingChatRequest } from "../utils/chatRequestRecovery"
import { extractErrorMessage } from "../utils/errorMessage"
import { useScheduleRevision, runScheduleMutation, type ScheduleRevisionState } from "./useScheduleRevision"

export interface ChatMessage {
  role: "user" | "assistant"
  content: string
  ask: string | null
  explanation: string | null
  ts: number
  appliedResult?: AppliedBlockResult[]
  // IDs added by this assistant turn. Sent back with the transcript so the
  // server can tell a partial apply from a preexisting same-title block.
  appliedAddBlockIds?: number[]
  // Feature 0083 (issue #219): set only on the two synthetic failure
  // bubbles below. Sent to the server as `is_error` so the replay guard
  // can exclude a never-applied failed turn from its evidence — see
  // RULES.md "Chat replay guard".
  isError?: boolean
}

export interface AppliedBlockResult {
  title: string
  start_time: string
  end_time: string
  category: TimeBlock["category"]
  change: "added" | "changed" | "removed"
}

interface ChatState {
  activeDate: Ref<string | null>
  messages: Ref<ChatMessage[]>
  isProcessing: Ref<boolean>
  lastError: Ref<string | null>
  pendingAsk: Ref<string | null>
  apiHealthy: Ref<boolean>
  draftInput: Ref<string>
  latestRequestId: number
  pendingRequest: Ref<PendingChatRequest | null>
  userId?: number
  unsubscribe?: () => void
}

function createChatState(): ChatState {
  return {
    activeDate: ref<string | null>(null), messages: ref<ChatMessage[]>([]),
    isProcessing: ref(false), lastError: ref<string | null>(null),
    pendingAsk: ref<string | null>(null), apiHealthy: ref(true),
    draftInput: ref(""), latestRequestId: 0, pendingRequest: ref(null),
  }
}

let ownerStates = new WeakMap<ScheduleRevisionState, ChatState>()
let standaloneState = createChatState()
let lastAccessedState = standaloneState

function stateFor(owner?: ScheduleRevisionState): ChatState {
  if (!owner) return standaloneState
  let state = ownerStates.get(owner)
  if (!state) {
    state = createChatState()
    ownerStates.set(owner, state)
    state.unsubscribe = owner.subscribeScopeReset((reason) => {
      if (reason === "user" || reason === "session") clearChatRequests(state!.userId)
      if (reason === "date") clearThreadState(state!)
      else clearSessionState(state!)
      state!.pendingRequest.value = null
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

function clearThreadState(state: ChatState): void {
  state.latestRequestId += 1
  state.isProcessing.value = false
  state.messages.value = []
  state.pendingAsk.value = null
  state.lastError.value = null
}

function clearSessionState(state: ChatState): void {
  clearThreadState(state)
  state.activeDate.value = null
  state.apiHealthy.value = true
  state.draftInput.value = ""
}

interface ChatApiResult extends ApiResult {
  data?: Record<string, unknown> & {
    blocks?: unknown
    explanation?: string | null
    ask?: string | null
    applied?: boolean
    partial?: boolean
    outcomes?: unknown[]
  }
}

function blockKey(block: TimeBlock): string {
  // Chip copy omits `sort_order`: a backend reorder of otherwise identical
  // blocks is not a user-visible mutation in the applied-turn summary.
  return `${block.id}|${block.title}|${block.start_time}|${block.end_time}|${block.category}|${block.is_completed}`
}

// `data.blocks` is the entire post-turn schedule, not a list of mutations.
// Preserve the user-visible diff only, including deletion-only turns.
function appliedResultFromDiff(snapshot: TimeBlock[], blocks: unknown): AppliedBlockResult[] {
  if (!Array.isArray(blocks)) return []
  const after = blocks as TimeBlock[]
  const beforeById = new Map(snapshot.map((block) => [block.id, block]))
  const afterById = new Map(after.map((block) => [block.id, block]))
  const result: AppliedBlockResult[] = []
  for (const block of after) {
    const before = beforeById.get(block.id)
    if (!before || blockKey(before) !== blockKey(block)) {
      result.push({ title: block.title, start_time: block.start_time, end_time: block.end_time, category: block.category, change: before ? "changed" : "added" })
    }
  }
  for (const block of snapshot) {
    if (!afterById.has(block.id)) result.push({ title: block.title, start_time: block.start_time, end_time: block.end_time, category: block.category, change: "removed" })
  }
  return result
}

function addedBlockIdsFromDiff(snapshot: TimeBlock[], blocks: unknown): number[] | undefined {
  if (!Array.isArray(blocks)) return undefined
  const beforeIds = new Set(snapshot.map((block) => block.id))
  return (blocks as TimeBlock[])
    .filter((block) => !beforeIds.has(block.id))
    .map((block) => block.id)
}

function uncertain(result: ApiResult): boolean {
  if (result.ok || result.data?.request_completed === true) return false
  return result.code === "request_in_progress" || result.code === "request_unavailable"
    || result.status === undefined || result.status >= 500 || result.status < 300
}

/** Share one owner's thread between the page, dock, and regenerate button. */
export function useChat(explicitRevision?: ScheduleRevisionState) {
  const revision = useScheduleRevision(explicitRevision)
  const state = stateFor(revision)
  lastAccessedState = state
  const { activeDate, messages, isProcessing, lastError, pendingAsk, apiHealthy, draftInput } = state
  function setActiveDate(date: string): void {
    if (activeDate.value === date) return
    clearThread()
    state.pendingRequest.value = null
    activeDate.value = date
    restorePending()
  }

  function clearThread(): void {
    // Logical cancel: bump the token first so any in-flight resolver sees
    // `myId !== latestRequestId` and skips its writes; then clear UI
    // state directly. After this returns there is no in-flight request
    // that owns the spinner, so resetting it here cannot race.
    clearThreadState(state)
  }

  function restorePending(): void {
    if (!activeDate.value || state.pendingRequest.value) return
    const capture = revision?.capture(activeDate.value)
    state.userId = capture?.userId
    state.pendingRequest.value = readChatRequest(state.userId, activeDate.value)
  }

  async function submitTurn(text: string, pushUndo: (a: UndoAction) => void): Promise<void> {
    restorePending()
    if (state.pendingRequest.value) {
      lastError.value = "Recover the previous AI request before sending another turn."
      draftInput.value = text
      return
    }
    await executeTurn(text, pushUndo, false)
  }

  async function recoverPending(pushUndo: (a: UndoAction) => void): Promise<void> {
    restorePending()
    if (!state.pendingRequest.value) return
    await executeTurn("", pushUndo, true)
  }

  async function executeTurn(
    text: string,
    pushUndo: (a: UndoAction) => void,
    recovering: boolean,
  ): Promise<void> {
    if (activeDate.value === null) {
      // Surface a user-visible message before throwing — if the
      // Schedule.vue watcher ever regresses, the user sees something
      // actionable in the dock instead of a silent no-op. The throw
      // remains so unit tests catch the regression deterministically.
      lastError.value = "Chat not initialised — please reload the page."
      throw new Error(
        "useChat.submitTurn called before setActiveDate — caller must " +
          "register the active date first.",
      )
    }
    const trimmed = text.trim()
    if (!trimmed && !recovering) return

    // The UI token controls transcript updates; the owner controls writes.
    const requestDate = activeDate.value

    // The mutation owner captures canonical blocks and revision together.
    // A second request must not replace the first request's UI token.
    if (!revision || revision.busy.value) {
      return
    }
    const myId = ++state.latestRequestId
    isProcessing.value = true
    lastError.value = null

    if (!recovering) messages.value = [
      ...messages.value,
      {
        role: "user",
        content: trimmed,
        ask: null,
        explanation: null,
        ts: Date.now(),
      },
    ]

    let pending = recovering ? state.pendingRequest.value : null
    if (recovering && pending && messages.value.length === 0) {
      messages.value = pending.body.messages.map(m => ({
        role: m.role as "user" | "assistant", content: m.content,
        ask: m.is_ask ? m.content : null, explanation: null, ts: Date.now(),
        isError: m.is_error, appliedAddBlockIds: m.applied_add_block_ids,
      }))
    }
    let result: ChatApiResult
    try {
      result = await runScheduleMutation(revision, requestDate, async (capture) => {
        if (!pending) {
          pending = {
            date: requestDate, userId: capture.userId,
            body: {
              request_id: crypto.randomUUID(), expected_revision: capture.revision,
              messages: messages.value.map(({ role, content, ask, isError, appliedAddBlockIds }) => ({
                role, content,
                ...(role === "assistant" && ask !== null ? { is_ask: true } : {}),
                ...(role === "assistant" && isError ? { is_error: true } : {}),
                ...(role === "assistant" && appliedAddBlockIds !== undefined ? { applied_add_block_ids: [...appliedAddBlockIds] } : {}),
              })),
            },
          }
          state.userId = capture.userId
          if (!storeChatRequest(pending)) {
            draftInput.value = trimmed
            return { ok: false, status: 400, errors: { detail: "Cannot save AI recovery state. Enable session storage before sending." } }
          }
          state.pendingRequest.value = pending
        }
        // Exactly one immediate transport retry. Never manufacture a new
        // transcript/revision/UUID, and never retry across a session boundary.
        let response: ApiResult
        for (let attempt = 0; ; attempt++) {
          response = await requestJson(`/api/ai/schedules/${requestDate}/chat/`, "POST", pending.body, { expectedUserId: pending.userId })
          // A proxy can deliver an empty 200 without triggering fetch's body
          // error. Only a receipt for this UUID establishes a terminal result.
          if ((response.ok || response.data?.request_completed === true)
            && (response.data?.request_completed !== true || response.data.request_id !== pending.body.request_id)) {
            response = { ok: false, status: 503, code: "request_unavailable", errors: { detail: "AI response could not be verified. Recover the original request." } }
          }
          if (!uncertain(response) || response.code === "request_in_progress" || attempt === 1
            || myId !== state.latestRequestId || !revision.isCurrent(capture)) break
        }
        return response
      }) as ChatApiResult
    } finally {
      // Only the most-recent owner of the latest-request slot may clear
      // the spinner. If `clearThread` (manual or via date change) or a
      // newer `submitTurn` ran while we were awaiting, leave the spinner
      // alone — those callers either cleared it directly or own it now.
      if (myId === state.latestRequestId) {
        isProcessing.value = false
      }
    }

    if (pending && !uncertain(result)) {
      removeChatRequest(pending)
      if (state.pendingRequest.value?.body.request_id === pending.body.request_id) state.pendingRequest.value = null
    }
    // A cancelled turn can still commit, but cannot update a newer thread.
    if (myId !== state.latestRequestId) return

    if (result.ok) {
      apiHealthy.value = true
      const data = result.data ?? {}
      const ask = typeof data.ask === "string" ? data.ask : null
      const explanation =
        typeof data.explanation === "string" ? data.explanation : null
      const applied = data.applied === true
      const partial = data.partial === true
      const snapshot = result.mutation?.previousBlocks ?? []
      const appliedResult = applied && !partial && result.mutation
        ? appliedResultFromDiff(snapshot, data.blocks)
        : undefined
      const appliedAddBlockIds = ask === null
        ? undefined
        : applied && result.mutation
          ? addedBlockIdsFromDiff(snapshot, data.blocks)
          : applied ? undefined : []

      // Prefer ask over explanation in the assistant message's `content`
      // so the next turn's transcript carries the actual question the
      // user is answering. Both fields are stored separately so callers
      // that want to render them distinctly can.
      messages.value = [
        ...messages.value,
        {
          role: "assistant",
          content: ask ?? explanation ?? "",
          ask,
          explanation,
          ts: Date.now(),
          appliedResult,
          appliedAddBlockIds,
        },
      ]
      pendingAsk.value = ask

      if (applied) registerMutationUndo(result, pushUndo, {
        description: explanation || "AI chat",
        type: "ai",
        silent: true,
      })
      if (result.code === "schedule_sync_failed") lastError.value = "Changes were saved, but the display could not refresh. Reload the page."
      return
    }

    if (uncertain(result) && state.pendingRequest.value) {
      apiHealthy.value = false
      lastError.value = "The previous AI result is not confirmed. Recover it before sending another turn."
      // No synthetic is_error bubble: the original write may have committed.
      return
    }

    // Failure path — keep the optimistically-appended user message and
    // append a synthetic assistant bubble carrying the error so the
    // user has a record they can edit and retry against.
    if (isScheduleChangedConflict(result)) {
      apiHealthy.value = true
      lastError.value = SCHEDULE_CHANGED_RETRY_MESSAGE
      messages.value = [
        ...messages.value,
        {
          role: "assistant",
          content: SCHEDULE_CHANGED_RETRY_MESSAGE,
          ask: null,
          explanation: null,
          ts: Date.now(),
          isError: true,
        },
      ]
      return
    }
    if (
      result.status === undefined ||
      result.status === 502 ||
      result.status === 503 ||
      result.status === 504
    ) {
      apiHealthy.value = false
    }
    const errMessage =
      result.status === 503
        ? "AI is unavailable — manual editing still works."
        : extractErrorMessage(result.errors, "AI chat failed")
    lastError.value = errMessage
    messages.value = [
      ...messages.value,
      {
        role: "assistant",
        content: errMessage,
        ask: null,
        explanation: null,
        ts: Date.now(),
        isError: true,
      },
    ]
  }

  return {
    activeDate,
    messages,
    isProcessing,
    lastError,
    pendingAsk,
    apiHealthy,
    draftInput,
    setActiveDate,
    clearThread,
    submitTurn,
    recoverPending,
    hasPendingRequest: computed(() => state.pendingRequest.value !== null),
    pendingRequestText: computed(() => state.pendingRequest.value?.body.messages.at(-1)?.content ?? ""),
  }
}

// Test-only reset for direct composable tests that construct many owners.
export function _resetChatStateForTests(): void {
  clearSessionState(lastAccessedState)
  lastAccessedState.unsubscribe?.()
  ownerStates = new WeakMap()
  standaloneState = createChatState()
  lastAccessedState = standaloneState
}

export function _peekLatestRequestId(): number {
  return lastAccessedState.latestRequestId
}

/** Clear the current applied-turn chip after a successful AI undo. */
export function clearAppliedResultForUndo(owner?: ScheduleRevisionState): void {
  const state = owner ? stateFor(owner) : lastAccessedState
  const next = [...state.messages.value]
  for (let i = next.length - 1; i >= 0; i--) {
    if (next[i].appliedResult) {
      next[i] = { ...next[i], appliedResult: undefined }
      break
    }
  }
  state.messages.value = next
}
