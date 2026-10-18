// Comprehensive tests for the `useChat` composable (feature 0007).
//
// Covers the request-token guard from the PLAN's 2.1 + 2.6:
//   * Happy path (apply + clarifying-question + chit-chat)
//   * `clearThread` is a logical cancel: bumps the token, clears the
//     spinner, AND drops any in-flight resolver
//   * `setActiveDate` clears on different date / no-op on same date
//   * Stale in-flight turn dropped on date change
//   * Token-race: old A resolution must not clear new B spinner
//   * `submitTurn` refuses when activeDate is null
//   * URL is derived from activeDate, not from any external argument

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

// `vi.mock` factories are hoisted ABOVE the test-file imports, so any
// closure they capture must also be hoisted. `vi.hoisted` is the standard
// vitest escape hatch — it runs before any imports / mock factories so
// the mocks below can safely reference the spies.
const { requestJsonMock, routerReload } = vi.hoisted(() => ({
  requestJsonMock: vi.fn(),
  routerReload: vi.fn(),
}))

vi.mock("../src/composables/useHttp", () => ({
  requestJson: async (...args: unknown[]) => {
    const result = await requestJsonMock(...args)
    if (!result.ok) return result
    const date = String(args[0]).split("/")[4]
    const revision = Number((args[2] as { expected_revision: number }).expected_revision) + (result.data?.applied ? 1 : 0)
    return { ...result, data: { ...result.data, revision, schedule: { id: 1, date, status: "active", revision } } }
  },
}))

vi.mock("@inertiajs/vue3", () => ({
  router: { reload: routerReload },
}))

import {
  _peekLatestRequestId,
  _resetChatStateForTests,
  clearAppliedResultForUndo,
  useChat as actualUseChat,
} from "../src/composables/useChat"
import { nextTick, ref } from "vue"
import { createScheduleRevision } from "../src/composables/useScheduleRevision"

let fixtureState: ReturnType<typeof createScheduleRevision> | undefined
const fixtureRevision = ref(0)
const fixtureDate = ref("2026-05-07")
function useChat() {
  const date = () => fixtureDate.value
  // Updating this fixture represents the Inertia refresh after a conflict.
  fixtureState = createScheduleRevision(date, () => ({ date: date(), revision: fixtureRevision.value }), { getBlocks: snapshotBlocks })
  const chat = actualUseChat(fixtureState)
  return { ...chat, setActiveDate: (next: string) => { fixtureDate.value = next; chat.setActiveDate(next) } }
}
import { SCHEDULE_CHANGED_RETRY_MESSAGE } from "../src/utils/aiScheduleConflict"

const BLOCK = {
  id: 1,
  title: "A",
  start_time: "09:00",
  end_time: "10:00",
  category: "work" as const,
  is_completed: false,
  sort_order: 0,
}

const snapshotBlocks = () => [{ ...BLOCK }]

interface DeferredApiResult {
  resolve: (value: {
    ok: boolean
    status?: number
    data?: unknown
    errors?: unknown
  }) => void
  reject: (e: unknown) => void
  promise: Promise<unknown>
}

function makeDeferred(): DeferredApiResult {
  let resolve!: DeferredApiResult["resolve"]
  let reject!: DeferredApiResult["reject"]
  const promise = new Promise<unknown>((res, rej) => {
    resolve = res as unknown as DeferredApiResult["resolve"]
    reject = rej
  })
  return { resolve, reject, promise }
}

describe("useChat", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    _resetChatStateForTests()
    fixtureRevision.value = 0
    fixtureDate.value = "2026-05-07"
    routerReload.mockImplementation((options) => {
      if (fixtureState?.revision.value !== null && fixtureState?.revision.value !== undefined) fixtureRevision.value = fixtureState.revision.value
      options.onSuccess?.()
      options.onFinish?.()
    })
  })

  afterEach(() => {
    _resetChatStateForTests()
    fixtureRevision.value = 0
    fixtureDate.value = "2026-05-07"
    routerReload.mockImplementation((options) => {
      if (fixtureState?.revision.value !== null && fixtureState?.revision.value !== undefined) fixtureRevision.value = fixtureState.revision.value
      options.onSuccess?.()
      options.onFinish?.()
    })
  })

  it("binds chat writes to the captured account identity", async () => {
    const owner = createScheduleRevision("2026-05-07", () => ({ id: 1, date: "2026-05-07", status: "active", revision: 0 }), { getBlocks: snapshotBlocks, getUserId: () => 7 })
    const chat = actualUseChat(owner)
    chat.setActiveDate("2026-05-07")
    requestJsonMock.mockResolvedValue({ ok: true, data: { applied: false, explanation: "Done" } })
    await chat.submitTurn("hello", vi.fn())
    expect(requestJsonMock.mock.calls[0][3]).toEqual({ expectedUserId: 7 })
  })

  it("uses the accepted canonical snapshot and revision for a follow-up without reload", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock
      .mockResolvedValueOnce({ ok: true, data: { applied: true, blocks: [{ ...BLOCK, title: "First" }] } })
      .mockResolvedValueOnce({ ok: true, data: { applied: true, blocks: [{ ...BLOCK, title: "Second" }] } })
    const pushUndo = vi.fn()
    await chat.submitTurn("first", pushUndo)
    await chat.submitTurn("second", pushUndo)
    expect(requestJsonMock.mock.calls.map((call) => call[2].expected_revision)).toEqual([0, 1])
    expect(pushUndo.mock.calls[0][0]).toMatchObject({ expected_revision: 1, previous_revision: 0, previousBlocks: [BLOCK] })
    expect(pushUndo.mock.calls[1][0]).toMatchObject({ expected_revision: 2, previous_revision: 1, previousBlocks: [{ ...BLOCK, title: "First" }] })
    expect(routerReload).not.toHaveBeenCalled()
  })

  it("blocks another turn while the first request owns the schedule", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    const deferred = makeDeferred()
    requestJsonMock.mockReturnValueOnce(deferred.promise)
    const first = chat.submitTurn("first", vi.fn())
    await chat.submitTurn("second", vi.fn())
    expect(requestJsonMock).toHaveBeenCalledTimes(1)
    expect(chat.isProcessing.value).toBe(true)
    expect(chat.messages.value.map((message) => message.content)).toEqual(["first"])
    deferred.resolve({ ok: true, data: { applied: false, explanation: "Done" } })
    await first
    expect(chat.isProcessing.value).toBe(false)
  })

  it("keeps a new owner's chat isolated from an old owner's late response", async () => {
    const first = useChat()
    first.setActiveDate("2026-05-07")
    first.draftInput.value = "Private unsent input"
    first.apiHealthy.value = false
    const deferred = makeDeferred()
    requestJsonMock.mockReturnValueOnce(deferred.promise)
    const pushUndo = vi.fn()
    const pending = first.submitTurn("Private prompt", pushUndo)
    const newOwner = createScheduleRevision("2026-05-07", () => ({ id: 2, date: "2026-05-07", status: "active", revision: 0 }), { getBlocks: () => [] })
    const second = actualUseChat(newOwner)
    second.setActiveDate("2026-05-07")
    expect(second.messages.value).toEqual([])
    expect(second.draftInput.value).toBe("")
    expect(second.apiHealthy.value).toBe(true)
    fixtureState?.reset("dispose")
    deferred.resolve({ ok: true, data: { applied: true, blocks: [{ ...BLOCK, title: "Old result" }] } })
    await pending
    expect(second.messages.value).toEqual([])
    expect(newOwner.blocks.value).toEqual([])
    expect(pushUndo).not.toHaveBeenCalled()
  })

  it("keeps two active owners' transcripts and input independent", () => {
    const firstOwner = createScheduleRevision("2026-05-07", () => ({ id: 1, date: "2026-05-07", status: "active", revision: 0 }), { getBlocks: snapshotBlocks })
    const secondOwner = createScheduleRevision("2026-05-07", () => ({ id: 2, date: "2026-05-07", status: "active", revision: 0 }), { getBlocks: snapshotBlocks })
    const first = actualUseChat(firstOwner)
    const second = actualUseChat(secondOwner)
    first.setActiveDate("2026-05-07")
    second.setActiveDate("2026-05-07")
    first.draftInput.value = "First user's prompt"
    first.messages.value = [{ role: "user", content: "First", ask: null, explanation: null, ts: 1 }]

    expect(second.draftInput.value).toBe("")
    expect(second.messages.value).toEqual([])
    second.clearThread()
    expect(first.messages.value).toHaveLength(1)

    firstOwner.reset("session")
    expect(first.draftInput.value).toBe("")
    expect(second.activeDate.value).toBe("2026-05-07")
  })

  it("reconciles an unknown outcome once and keeps the writer busy until reload completes", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock.mockResolvedValue({ ok: false, errors: { detail: "Network error" } })
    let finish!: () => void
    routerReload.mockImplementationOnce((options) => { finish = () => { options.onSuccess(); options.onFinish() } })
    const pushUndo = vi.fn()
    const pending = chat.submitTurn("unknown", pushUndo)
    await Promise.resolve()
    await Promise.resolve()
    expect(fixtureState!.busy.value).toBe(true)
    await chat.submitTurn("retry before reconciliation", pushUndo)
    expect(requestJsonMock).toHaveBeenCalledTimes(1)
    finish()
    await pending
    expect(routerReload).toHaveBeenCalledTimes(1)
    expect(requestJsonMock).toHaveBeenCalledTimes(1)
    expect(pushUndo).not.toHaveBeenCalled()
    expect(fixtureState!.busy.value).toBe(false)
  })

  it("submitTurn refuses when activeDate is null", async () => {
    const chat = useChat()
    await expect(
      chat.submitTurn("hi", vi.fn()),
    ).rejects.toThrow(/before setActiveDate/)
    expect(requestJsonMock).not.toHaveBeenCalled()
  })

  it("happy path: apply turn appends user + assistant, pushes undo, reloads", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock.mockResolvedValue({
      ok: true,
      data: {
        blocks: [
          {
            ...BLOCK,
            id: 2,
            title: "Standup",
            start_time: "10:00",
            end_time: "10:15",
          },
        ],
        explanation: "Added",
        ask: null,
        applied: true,
      },
    })
    const pushUndo = vi.fn()

    await chat.submitTurn("add standup", pushUndo)

    expect(chat.messages.value.length).toBe(2)
    expect(chat.messages.value[0]).toMatchObject({
      role: "user",
      content: "add standup",
    })
    expect(chat.messages.value[1]).toMatchObject({
      role: "assistant",
      content: "Added",
      ask: null,
    })
    expect(pushUndo).toHaveBeenCalledOnce()
    expect(pushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "ai", silent: true }),
    )
    expect(routerReload).not.toHaveBeenCalled()
    expect(chat.isProcessing.value).toBe(false)
  })

  it("stores only the applied schedule diff for the result chip", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock.mockResolvedValue({
      ok: true,
      data: {
        blocks: [
          { ...BLOCK, title: "Renamed" },
          { ...BLOCK, id: 2, title: "Added", start_time: "11:00", end_time: "11:30" },
        ],
        applied: true,
        explanation: "Updated schedule",
      },
    })

    await chat.submitTurn("update", vi.fn())

    expect(chat.messages.value.at(-1)?.appliedResult).toEqual([
      expect.objectContaining({ title: "Renamed", change: "changed" }),
      expect.objectContaining({ title: "Added", change: "added" }),
    ])
  })

  it("does not treat a sort_order-only reorder as an applied chip change", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock.mockResolvedValue({
      ok: true,
      data: {
        blocks: [{ ...BLOCK, sort_order: 10 }],
        applied: true,
        explanation: "Reordered",
      },
    })

    await chat.submitTurn("reorder", vi.fn())

    expect(chat.messages.value.at(-1)?.appliedResult).toEqual([])
  })

  it("clears only the most recent applied chip on AI undo", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock
      .mockResolvedValueOnce({
        ok: true,
        data: {
          blocks: [{ ...BLOCK, title: "First" }],
          applied: true,
          explanation: "First apply",
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: {
          blocks: [{ ...BLOCK, title: "Second" }],
          applied: true,
          explanation: "Second apply",
        },
      })

    await chat.submitTurn("first", vi.fn())
    await chat.submitTurn("second", vi.fn())

    const applied = chat.messages.value.filter((m) => m.appliedResult)
    expect(applied).toHaveLength(2)

    clearAppliedResultForUndo(fixtureState)

    const remaining = chat.messages.value.filter((m) => m.appliedResult)
    expect(remaining).toHaveLength(1)
    expect(remaining[0].appliedResult?.[0]?.title).toBe("First")
  })

  it("URL is derived from activeDate, not from any external argument", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock.mockResolvedValue({
      ok: true,
      data: { blocks: null, explanation: "ok", ask: null, applied: false },
    })
    await chat.submitTurn("hi", vi.fn())
    expect(requestJsonMock).toHaveBeenCalledTimes(1)
    expect(requestJsonMock.mock.calls[0][0]).toBe(
      "/api/ai/schedules/2026-05-07/chat/",
    )
  })

  it("sends messages only and never reads the browser timezone", async () => {
    const formatSpy = vi.spyOn(Intl, "DateTimeFormat")
    requestJsonMock.mockResolvedValue({
      ok: true,
      data: { blocks: null, explanation: "ok", ask: null, applied: false },
    })
    const chat = useChat()
    chat.setActiveDate("2026-05-07")

    await chat.submitTurn("first", vi.fn())
    await chat.submitTurn("second", vi.fn())

    expect(requestJsonMock.mock.calls[0][2]).toEqual(
      { expected_revision: expect.any(Number), messages: expect.any(Array) },
    )
    expect(requestJsonMock.mock.calls[1][2]).toEqual(
      { expected_revision: expect.any(Number), messages: expect.any(Array) },
    )
    expect(formatSpy).not.toHaveBeenCalled()
    formatSpy.mockRestore()
  })

  it.each(["I understood", "", " \t\n"])("sends a nonblank ask on the next turn with explanation %j", async (explanation) => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock
      .mockResolvedValueOnce({
        ok: true,
        data: { blocks: null, explanation, ask: "when?", applied: false },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: { blocks: null, explanation: "ok", ask: null, applied: false },
      })

    await chat.submitTurn("add gym", vi.fn())
    await chat.submitTurn("18:00", vi.fn())

    const secondBody = requestJsonMock.mock.calls[1][2] as { messages: unknown[] }
    expect(secondBody.messages).toEqual([
      { role: "user", content: "add gym" },
      { role: "assistant", content: "when?", is_ask: true, applied_add_block_ids: [] },
      { role: "user", content: "18:00" },
    ])
  })

  it("sends is_error on failure bubbles", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        errors: { detail: "schedule_changed" },
      })
      .mockResolvedValueOnce({
        ok: false,
        status: 502,
        errors: { detail: "boom" },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: { blocks: null, explanation: "ok", ask: null, applied: false },
      })

    await chat.submitTurn("move gym", vi.fn())
    fixtureRevision.value += 1
    await chat.submitTurn("try again", vi.fn())
    await chat.submitTurn("try again", vi.fn())

    const secondBody = requestJsonMock.mock.calls[1][2] as { messages: unknown[] }
    expect(secondBody.messages[1]).toEqual({
      role: "assistant",
      content: SCHEDULE_CHANGED_RETRY_MESSAGE,
      is_error: true,
    })
    const thirdBody = requestJsonMock.mock.calls[2][2] as { messages: unknown[] }
    expect(thirdBody.messages[3]).toEqual({
      role: "assistant",
      content: "boom",
      is_error: true,
    })
  })

  it("an explanation-only assistant turn carries neither key", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock
      .mockResolvedValueOnce({
        ok: true,
        data: { blocks: null, explanation: "Added gym", ask: null, applied: true, partial: false },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: { blocks: null, explanation: "ok", ask: null, applied: false },
      })

    await chat.submitTurn("add gym", vi.fn())
    await chat.submitTurn("thanks", vi.fn())

    const secondBody = requestJsonMock.mock.calls[1][2] as { messages: unknown[] }
    expect(secondBody.messages[1]).toEqual({ role: "assistant", content: "Added gym" })
  })

  it("clarifying-question turn stores ask in content (not explanation)", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock.mockResolvedValue({
      ok: true,
      data: {
        blocks: null,
        explanation: "I understood you want gym",
        ask: "when?",
        applied: false,
      },
    })

    await chat.submitTurn("add gym", vi.fn())

    const last = chat.messages.value[chat.messages.value.length - 1]
    // Content prefers ask so the next request's transcript carries the
    // actual question the user is answering.
    expect(last.content).toBe("when?")
    expect(last.ask).toBe("when?")
    expect(last.explanation).toBe("I understood you want gym")
    expect(chat.pendingAsk.value).toBe("when?")
    expect(routerReload).not.toHaveBeenCalled()
  })

  it("partial apply with a server ask pushes one undo entry and preserves the ask", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock.mockResolvedValue({
      ok: true,
      data: {
        blocks: [{ ...BLOCK, title: "Renamed" }],
        explanation: "Renamed it",
        ask: "Should I look for an earlier or later slot?",
        applied: true,
        partial: true,
        outcomes: [],
      },
    })
    const pushUndo = vi.fn()

    await chat.submitTurn("rename and move it", pushUndo)

    expect(pushUndo).toHaveBeenCalledOnce()
    expect(chat.pendingAsk.value).toBe("Should I look for an earlier or later slot?")
    expect(chat.messages.value.at(-1)).toMatchObject({
      content: "Should I look for an earlier or later slot?",
      ask: "Should I look for an earlier or later slot?",
    })
    expect(chat.messages.value.at(-1)?.appliedResult).toBeUndefined()
  })

  it("sends IDs added before a partial apply ask on the next turn", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock
      .mockResolvedValueOnce({
        ok: true,
        data: {
          blocks: [{ ...BLOCK }, { ...BLOCK, id: 2, title: "Gym" }],
          explanation: "Added Gym",
          ask: "When should Vocal start?",
          applied: true,
          partial: true,
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: { blocks: null, explanation: "ok", ask: null, applied: false },
      })

    await chat.submitTurn("add Gym plus Vocal", vi.fn())
    await chat.submitTurn("15 minutes", vi.fn())

    const secondBody = requestJsonMock.mock.calls[1][2] as { messages: unknown[] }
    expect(secondBody.messages[1]).toEqual({
      role: "assistant",
      content: "When should Vocal start?",
      is_ask: true,
      applied_add_block_ids: [2],
    })
    expect(chat.messages.value[1].appliedResult).toBeUndefined()
  })

  it("409 schedule_changed shows retry message, reloads, no undo, apiHealthy true", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    chat.apiHealthy.value = false
    requestJsonMock.mockResolvedValue({
      ok: false,
      status: 409,
      errors: { detail: "schedule_changed" },
    })
    const pushUndo = vi.fn()

    await chat.submitTurn("move gym", pushUndo)

    expect(requestJsonMock).toHaveBeenCalledTimes(1)
    expect(pushUndo).not.toHaveBeenCalled()
    expect(routerReload).toHaveBeenCalledOnce()
    expect(routerReload).toHaveBeenCalledWith(expect.objectContaining({ only: ["blocks", "schedule", "auth_user_id", "schedule_window"] }))
    expect(chat.apiHealthy.value).toBe(true)
    expect(chat.lastError.value).toBe(SCHEDULE_CHANGED_RETRY_MESSAGE)
    expect(chat.messages.value.length).toBe(2)
    expect(chat.messages.value[1]).toMatchObject({
      role: "assistant",
      content: SCHEDULE_CHANGED_RETRY_MESSAGE,
    })
    expect(chat.messages.value[1].appliedResult).toBeUndefined()
    expect(chat.isProcessing.value).toBe(false)
  })

  it("unrelated 409 stays an ordinary error without reload", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock.mockResolvedValue({
      ok: false,
      status: 409,
      errors: { detail: "draft schedule already has blocks" },
    })

    await chat.submitTurn("generate", vi.fn())

    expect(requestJsonMock).toHaveBeenCalledTimes(1)
    expect(routerReload).not.toHaveBeenCalled()
    expect(chat.apiHealthy.value).toBe(true)
    expect(chat.lastError.value).toBe("draft schedule already has blocks")
    expect(chat.messages.value[1]).toMatchObject({
      role: "assistant",
      content: "draft schedule already has blocks",
    })
  })

  it("error path keeps user message and appends synthetic assistant error", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock.mockResolvedValue({
      ok: false,
      status: 500,
      errors: { detail: "boom" },
    })

    await chat.submitTurn("oops", vi.fn())

    expect(chat.messages.value.length).toBe(2)
    expect(chat.messages.value[0]).toMatchObject({
      role: "user",
      content: "oops",
    })
    expect(chat.messages.value[1]).toMatchObject({
      role: "assistant",
      content: "boom",
    })
    expect(chat.lastError.value).toBe("boom")
    expect(chat.isProcessing.value).toBe(false)
  })

  describe("clearThread (logical cancel)", () => {
    it("resets messages, pendingAsk, lastError; preserves activeDate and draftInput", () => {
      const chat = useChat()
      chat.setActiveDate("2026-05-07")
      chat.messages.value = [
        { role: "user", content: "x", ask: null, explanation: null, ts: 1 },
      ]
      chat.pendingAsk.value = "?"
      chat.lastError.value = "err"
      chat.draftInput.value = "unsent message"

      chat.clearThread()

      expect(chat.messages.value).toEqual([])
      expect(chat.pendingAsk.value).toBe(null)
      expect(chat.lastError.value).toBe(null)
      expect(chat.activeDate.value).toBe("2026-05-07")
      expect(chat.draftInput.value).toBe("unsent message")
    })

    it("bumps the request token", () => {
      const chat = useChat()
      const before = _peekLatestRequestId()
      chat.clearThread()
      expect(_peekLatestRequestId()).toBe(before + 1)
    })

    it("clears isProcessing directly", () => {
      const chat = useChat()
      chat.isProcessing.value = true
      chat.clearThread()
      expect(chat.isProcessing.value).toBe(false)
    })

    it("cancels in-flight turn: resolved response is dropped", async () => {
      const chat = useChat()
      chat.setActiveDate("2026-05-07")
      const deferred = makeDeferred()
      requestJsonMock.mockReturnValue(deferred.promise)
      const pushUndo = vi.fn()

      const inFlight = chat.submitTurn("submit me", pushUndo)
      expect(chat.isProcessing.value).toBe(true)
      // User message was appended optimistically.
      expect(chat.messages.value.length).toBe(1)

      // Click Clear before the request resolves.
      chat.clearThread()
      expect(chat.messages.value).toEqual([])
      expect(chat.isProcessing.value).toBe(false)

      // Now resolve as if the response landed late with applied=true.
      deferred.resolve({
        ok: true,
        data: {
          blocks: [{ ...BLOCK, id: 99, title: "Late" }],
          explanation: "Late",
          ask: null,
          applied: true,
        },
      })
      await inFlight

      // The stale resolver must NOT have repopulated the thread, called
      // pushUndo, or triggered a router.reload.
      expect(chat.messages.value).toEqual([])
      expect(pushUndo).not.toHaveBeenCalled()
      expect(routerReload).not.toHaveBeenCalled()
      expect(chat.isProcessing.value).toBe(false)
    })

    it("cancels in-flight turn: rejected response also dropped", async () => {
      const chat = useChat()
      chat.setActiveDate("2026-05-07")
      const deferred = makeDeferred()
      requestJsonMock.mockReturnValue(deferred.promise)

      const inFlight = chat.submitTurn("hi", vi.fn())
      chat.clearThread()

      deferred.resolve({ ok: false, status: 500, errors: { detail: "boom" } })
      await inFlight

      expect(chat.messages.value).toEqual([])
      expect(chat.lastError.value).toBe(null)
      expect(chat.isProcessing.value).toBe(false)
    })
  })

  describe("setActiveDate", () => {
    it("clears thread on date change", async () => {
      const chat = useChat()
      chat.setActiveDate("2026-05-07")
      chat.messages.value = [
        {
          role: "assistant",
          content: "x",
          ask: null,
          explanation: null,
          ts: 1,
          appliedResult: [
            {
              title: "A",
              start_time: "09:00",
              end_time: "10:00",
              category: "work",
              change: "changed",
            },
          ],
        },
      ]
      chat.pendingAsk.value = "?"

      chat.setActiveDate("2026-05-08")
    await nextTick()

      expect(chat.messages.value).toEqual([])
      expect(chat.pendingAsk.value).toBe(null)
      expect(chat.isProcessing.value).toBe(false)
      expect(chat.activeDate.value).toBe("2026-05-08")
    })

    it("is a no-op when called with the same date (token does NOT advance)", () => {
      const chat = useChat()
      chat.setActiveDate("2026-05-07")
      const before = _peekLatestRequestId()
      chat.setActiveDate("2026-05-07")
      expect(_peekLatestRequestId()).toBe(before)
    })

    it("stale in-flight turn dropped on date change", async () => {
      const chat = useChat()
      chat.setActiveDate("2026-05-07")
      const deferred = makeDeferred()
      requestJsonMock.mockReturnValue(deferred.promise)
      const pushUndo = vi.fn()

      const inFlight = chat.submitTurn(
        "authored on A",
        pushUndo,
      )
      chat.setActiveDate("2026-05-08")
    await nextTick()

      deferred.resolve({
        ok: true,
        data: {
          blocks: [{ ...BLOCK, id: 5, title: "leaked" }],
          explanation: "leaked",
          ask: null,
          applied: true,
        },
      })
      await inFlight

      expect(chat.messages.value).toEqual([])
      expect(pushUndo).not.toHaveBeenCalled()
      expect(routerReload).not.toHaveBeenCalled()
      expect(chat.isProcessing.value).toBe(false)
    })
  })

  it("token-race: old-A resolution must not clear new-B spinner", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")

    // A is in-flight.
    const deferredA = makeDeferred()
    requestJsonMock.mockReturnValueOnce(deferredA.promise)
    const inFlightA = chat.submitTurn("turn A", vi.fn())
    expect(chat.isProcessing.value).toBe(true)

    // Navigate away — this clears the thread + bumps token + resets
    // spinner directly.
    chat.setActiveDate("2026-05-08")
    await nextTick()
    expect(chat.isProcessing.value).toBe(false)

    // B is in-flight on day B.
    const deferredB = makeDeferred()
    requestJsonMock.mockReturnValueOnce(deferredB.promise)
    const inFlightB = chat.submitTurn("turn B", vi.fn())
    expect(chat.isProcessing.value).toBe(true)

    // Resolve A. Its resolver MUST NOT clear B's spinner nor leak its
    // assistant bubble into B's thread.
    deferredA.resolve({
      ok: true,
      data: {
        blocks: null,
        explanation: "from A",
        ask: null,
        applied: false,
      },
    })
    await inFlightA
    expect(chat.isProcessing.value).toBe(true)
    // B's user message is the only entry so far; A's resolver must not
    // have appended an assistant bubble.
    expect(chat.messages.value.length).toBe(1)
    expect(chat.messages.value[0]).toMatchObject({ content: "turn B" })

    // Now resolve B normally.
    deferredB.resolve({
      ok: true,
      data: {
        blocks: null,
        explanation: "from B",
        ask: null,
        applied: false,
      },
    })
    await inFlightB

    expect(chat.isProcessing.value).toBe(false)
    expect(chat.messages.value.length).toBe(2)
    expect(chat.messages.value[1]).toMatchObject({
      role: "assistant",
      content: "from B",
    })
  })

  it("token-race: B-rejecting + A-succeeding still leaves B owning the spinner", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")

    const deferredA = makeDeferred()
    requestJsonMock.mockReturnValueOnce(deferredA.promise)
    const inFlightA = chat.submitTurn("A", vi.fn())

    chat.setActiveDate("2026-05-08")
    await nextTick()

    const deferredB = makeDeferred()
    requestJsonMock.mockReturnValueOnce(deferredB.promise)
    const inFlightB = chat.submitTurn("B", vi.fn())

    // B fails first.
    deferredB.resolve({ ok: false, status: 500, errors: { detail: "fail" } })
    await inFlightB
    expect(chat.isProcessing.value).toBe(false)

    // A's late resolution must not flip the spinner back on, and must
    // not append anything to the thread.
    const lengthBefore = chat.messages.value.length
    deferredA.resolve({
      ok: true,
      data: {
        blocks: null,
        explanation: "stale",
        ask: null,
        applied: false,
      },
    })
    await inFlightA
    expect(chat.isProcessing.value).toBe(false)
    expect(chat.messages.value.length).toBe(lengthBefore)
  })
})

// Fallback-literal guard (feature 0037): pin the exact fallback string in
// the `:` branch of the 503-ternary. A non-503 failure (500) with
// `errors: {}` makes the ternary fall to the shared helper's fallback.
describe("useChat fallback-literal guard", () => {
  beforeEach(() => {
    _resetChatStateForTests()
    fixtureRevision.value = 0
    routerReload.mockImplementation((options) => {
      if (fixtureState?.revision.value !== null && fixtureState?.revision.value !== undefined) fixtureRevision.value = fixtureState.revision.value
      options.onSuccess?.()
      options.onFinish?.()
    })
    requestJsonMock.mockReset()
  })

  it("submitTurn surfaces the exact fallback literal on an empty errors map", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      errors: {},
    })
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    await chat.submitTurn("hi", vi.fn())
    expect(chat.lastError.value).toBe("AI chat failed")
  })
})
