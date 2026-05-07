// Multi-turn AI chat composable (feature 0007).
//
// Module-level state — there is one chat thread per tab; the bottom dock
// (PR A) and the future sidebar (PR B) share state through this single
// instance. Tests reset state in `beforeEach` to avoid cross-test leakage.
//
// **Staleness guard:** every event that should invalidate an in-flight
// turn (a fresh `submitTurn`, an explicit `clearThread`, or a date
// navigation via `setActiveDate`) bumps `latestRequestId`. Each
// `submitTurn` captures its own `myId` and only writes back to state if
// `myId === latestRequestId` at resolution time — for both the spinner
// and the UI updates. This is the single source of truth for "is this
// resolver still relevant?", and it covers every cancellation cause
// (newer submit, manual Clear, date change) without overlapping checks.

import { router } from "@inertiajs/vue3"
import { ref } from "vue"
import type { TimeBlock, UndoAction } from "../types"
import { scheduleChanged } from "../utils/scheduleDiff"
import { type ApiResult, requestJson } from "./useHttp"

export interface ChatMessage {
  role: "user" | "assistant"
  content: string
  ask: string | null
  explanation: string | null
  ts: number
}

const activeDate = ref<string | null>(null)
const messages = ref<ChatMessage[]>([])
const isProcessing = ref(false)
const lastError = ref<string | null>(null)
const pendingAsk = ref<string | null>(null)
const apiHealthy = ref(true)

// Module-level counter, intentionally NOT a ref — it never participates
// in rendering. Every `submitTurn` bumps it; `clearThread` (and via it,
// `setActiveDate`) bumps it. `submitTurn` resolvers compare their own
// captured `myId` against this to decide whether they may write to state.
let latestRequestId = 0

interface ChatApiResult extends ApiResult {
  data?: {
    blocks?: unknown
    explanation?: string | null
    ask?: string | null
    applied?: boolean
  }
}

function extractErrorMessage(
  errors: Record<string, string | string[]> | undefined,
): string {
  if (!errors) return "AI chat failed"
  if (typeof errors.detail === "string") return errors.detail
  const first = Object.values(errors).flat()[0]
  return typeof first === "string" && first ? first : "AI chat failed"
}

export function useChat() {
  function setActiveDate(date: string): void {
    if (activeDate.value === date) return
    clearThread()
    activeDate.value = date
  }

  function clearThread(): void {
    // Logical cancel: bump the token first so any in-flight resolver sees
    // `myId !== latestRequestId` and skips its writes; then clear UI
    // state directly. After this returns there is no in-flight request
    // that owns the spinner, so resetting it here cannot race.
    latestRequestId += 1
    isProcessing.value = false
    messages.value = []
    pendingAsk.value = null
    lastError.value = null
  }

  async function submitTurn(
    text: string,
    snapshotBlocks: () => TimeBlock[],
    pushUndo: (a: UndoAction) => void,
  ): Promise<void> {
    if (activeDate.value === null) {
      throw new Error(
        "useChat.submitTurn called before setActiveDate — caller must " +
          "register the active date first.",
      )
    }
    const trimmed = text.trim()
    if (!trimmed) return

    // Token + date capture. `requestDate` is used only for URL building
    // (and as a record on the optimistic user message). Staleness is
    // decided exclusively by the token.
    const myId = ++latestRequestId
    const requestDate = activeDate.value

    isProcessing.value = true
    lastError.value = null
    const snapshot = snapshotBlocks()

    messages.value = [
      ...messages.value,
      {
        role: "user",
        content: trimmed,
        ask: null,
        explanation: null,
        ts: Date.now(),
      },
    ]

    let result: ChatApiResult
    try {
      result = (await requestJson(
        `/api/ai/schedules/${requestDate}/chat/`,
        "POST",
        {
          messages: messages.value.map(({ role, content }) => ({
            role,
            content,
          })),
        },
      )) as ChatApiResult
    } finally {
      // Only the most-recent owner of the latest-request slot may clear
      // the spinner. If `clearThread` (manual or via date change) or a
      // newer `submitTurn` ran while we were awaiting, leave the spinner
      // alone — those callers either cleared it directly or own it now.
      if (myId === latestRequestId) {
        isProcessing.value = false
      }
    }

    // Single staleness check covers every cancellation path: newer
    // submit, manual Clear, or date change.
    if (myId !== latestRequestId) return

    if (result.ok) {
      apiHealthy.value = true
      const data = result.data ?? {}
      const ask = typeof data.ask === "string" ? data.ask : null
      const explanation =
        typeof data.explanation === "string" ? data.explanation : null
      const applied = data.applied === true

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
        },
      ]
      pendingAsk.value = ask

      if (applied) {
        if (scheduleChanged(snapshot, data.blocks)) {
          pushUndo({
            description: explanation || "AI chat",
            type: "ai",
            previousBlocks: snapshot,
            scheduleDate: requestDate,
          })
        }
        router.reload({ only: ["blocks", "schedule"] })
      }
      return
    }

    // Failure path — keep the optimistically-appended user message and
    // append a synthetic assistant bubble carrying the error so the
    // user has a record they can edit and retry against.
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
        : extractErrorMessage(result.errors)
    lastError.value = errMessage
    messages.value = [
      ...messages.value,
      {
        role: "assistant",
        content: errMessage,
        ask: null,
        explanation: null,
        ts: Date.now(),
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
    setActiveDate,
    clearThread,
    submitTurn,
  }
}

// Test-only escape hatch so unit tests can reset module-level state in
// `beforeEach` without relying on import ordering tricks. Not exported
// from the public surface; tests import it explicitly.
export function _resetChatStateForTests(): void {
  activeDate.value = null
  messages.value = []
  isProcessing.value = false
  lastError.value = null
  pendingAsk.value = null
  apiHealthy.value = true
  latestRequestId = 0
}

export function _peekLatestRequestId(): number {
  return latestRequestId
}
