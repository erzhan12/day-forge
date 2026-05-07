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
  requestJson: (...args: unknown[]) => requestJsonMock(...args),
}))

vi.mock("@inertiajs/vue3", () => ({
  router: { reload: routerReload },
}))

import {
  _peekLatestRequestId,
  _resetChatStateForTests,
  useChat,
} from "../src/composables/useChat"

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
  resolve: (
    value: { ok: boolean; status?: number; data?: unknown; errors?: unknown },
  ) => void
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
  })

  afterEach(() => {
    _resetChatStateForTests()
  })

  it("submitTurn refuses when activeDate is null", async () => {
    const chat = useChat()
    await expect(
      chat.submitTurn("hi", snapshotBlocks, vi.fn()),
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
          { ...BLOCK, id: 2, title: "Standup", start_time: "10:00", end_time: "10:15" },
        ],
        explanation: "Added",
        ask: null,
        applied: true,
      },
    })
    const pushUndo = vi.fn()

    await chat.submitTurn("add standup", snapshotBlocks, pushUndo)

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
    expect(routerReload).toHaveBeenCalledOnce()
    expect(chat.isProcessing.value).toBe(false)
  })

  it("URL is derived from activeDate, not from any external argument", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock.mockResolvedValue({
      ok: true,
      data: { blocks: null, explanation: "ok", ask: null, applied: false },
    })
    await chat.submitTurn("hi", snapshotBlocks, vi.fn())
    expect(requestJsonMock).toHaveBeenCalledTimes(1)
    expect(requestJsonMock.mock.calls[0][0]).toBe(
      "/api/ai/schedules/2026-05-07/chat/",
    )
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

    await chat.submitTurn("add gym", snapshotBlocks, vi.fn())

    const last = chat.messages.value[chat.messages.value.length - 1]
    // Content prefers ask so the next request's transcript carries the
    // actual question the user is answering.
    expect(last.content).toBe("when?")
    expect(last.ask).toBe("when?")
    expect(last.explanation).toBe("I understood you want gym")
    expect(chat.pendingAsk.value).toBe("when?")
    expect(routerReload).not.toHaveBeenCalled()
  })

  it("error path keeps user message and appends synthetic assistant error", async () => {
    const chat = useChat()
    chat.setActiveDate("2026-05-07")
    requestJsonMock.mockResolvedValue({
      ok: false,
      status: 500,
      errors: { detail: "boom" },
    })

    await chat.submitTurn("oops", snapshotBlocks, vi.fn())

    expect(chat.messages.value.length).toBe(2)
    expect(chat.messages.value[0]).toMatchObject({ role: "user", content: "oops" })
    expect(chat.messages.value[1]).toMatchObject({
      role: "assistant",
      content: "boom",
    })
    expect(chat.lastError.value).toBe("boom")
    expect(chat.isProcessing.value).toBe(false)
  })

  describe("clearThread (logical cancel)", () => {
    it("resets messages, pendingAsk, lastError; preserves activeDate", () => {
      const chat = useChat()
      chat.setActiveDate("2026-05-07")
      chat.messages.value = [
        { role: "user", content: "x", ask: null, explanation: null, ts: 1 },
      ]
      chat.pendingAsk.value = "?"
      chat.lastError.value = "err"

      chat.clearThread()

      expect(chat.messages.value).toEqual([])
      expect(chat.pendingAsk.value).toBe(null)
      expect(chat.lastError.value).toBe(null)
      expect(chat.activeDate.value).toBe("2026-05-07")
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

      const inFlight = chat.submitTurn("submit me", snapshotBlocks, pushUndo)
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
          blocks: [
            { ...BLOCK, id: 99, title: "Late" },
          ],
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

      const inFlight = chat.submitTurn("hi", snapshotBlocks, vi.fn())
      chat.clearThread()

      deferred.resolve({ ok: false, status: 500, errors: { detail: "boom" } })
      await inFlight

      expect(chat.messages.value).toEqual([])
      expect(chat.lastError.value).toBe(null)
      expect(chat.isProcessing.value).toBe(false)
    })
  })

  describe("setActiveDate", () => {
    it("clears thread on date change", () => {
      const chat = useChat()
      chat.setActiveDate("2026-05-07")
      chat.messages.value = [
        { role: "user", content: "x", ask: null, explanation: null, ts: 1 },
      ]
      chat.pendingAsk.value = "?"

      chat.setActiveDate("2026-05-08")

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

      const inFlight = chat.submitTurn("authored on A", snapshotBlocks, pushUndo)
      chat.setActiveDate("2026-05-08")

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
    const inFlightA = chat.submitTurn("turn A", snapshotBlocks, vi.fn())
    expect(chat.isProcessing.value).toBe(true)

    // Navigate away — this clears the thread + bumps token + resets
    // spinner directly.
    chat.setActiveDate("2026-05-08")
    expect(chat.isProcessing.value).toBe(false)

    // B is in-flight on day B.
    const deferredB = makeDeferred()
    requestJsonMock.mockReturnValueOnce(deferredB.promise)
    const inFlightB = chat.submitTurn("turn B", snapshotBlocks, vi.fn())
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
    const inFlightA = chat.submitTurn("A", snapshotBlocks, vi.fn())

    chat.setActiveDate("2026-05-08")

    const deferredB = makeDeferred()
    requestJsonMock.mockReturnValueOnce(deferredB.promise)
    const inFlightB = chat.submitTurn("B", snapshotBlocks, vi.fn())

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
