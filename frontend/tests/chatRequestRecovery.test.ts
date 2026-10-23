import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { ref } from "vue"
import { createScheduleRevision } from "../src/composables/useScheduleRevision"
import { _resetChatStateForTests, useChat } from "../src/composables/useChat"
import { readChatRequest, retainChatRequestsForUser } from "../src/utils/chatRequestRecovery"
import type { TimeBlock } from "../src/types"

const { reload } = vi.hoisted(() => ({ reload: vi.fn() }))
vi.mock("@inertiajs/vue3", () => ({ router: { reload } }))

const DAY = "2027-01-15"
const BLOCK: TimeBlock = { id: 1, title: "Smoke", category: "work", start_time: "14:00", end_time: "14:30", sort_order: 0, is_completed: false }
const fetchMock = vi.fn()
function setup(userId = 7, revision = 0, blocks: TimeBlock[] = []) {
  const props = ref({ schedule: { id: 1, date: DAY, revision, status: "active" as const }, blocks })
  const state = createScheduleRevision(DAY, () => props.value.schedule, { getUserId: () => userId, getBlocks: () => props.value.blocks })
  const chat = useChat(state)
  chat.setActiveDate(DAY)
  return { state, chat, props }
}
function success(revision = 1, blocks = [BLOCK]) {
  return new Response(JSON.stringify({
    request_id: sent(fetchMock.mock.calls.length - 1).request_id, request_completed: true, revision, schedule: { id: 1, date: DAY, revision, status: "active" },
    blocks, explanation: "Added Smoke.", ask: null, applied: true, partial: false, outcomes: [],
  }), { status: 200 })
}
function sent(index = 0) { return JSON.parse(fetchMock.mock.calls[index][1].body) }

beforeEach(() => {
  _resetChatStateForTests()
  sessionStorage.clear()
  fetchMock.mockReset()
  vi.stubGlobal("fetch", fetchMock)
  reload.mockImplementation(options => { options.onSuccess?.(); options.onFinish?.() })
})
afterEach(() => { _resetChatStateForTests(); sessionStorage.clear(); vi.restoreAllMocks(); vi.unstubAllGlobals() })

describe("durable chat recovery", () => {
  it("restores a frozen continuation after remount with the same intent and request UUID", async () => {
    const first = setup()
    const intent = { id: "ba598a1c-bddc-461f-a057-e5bf2b6bf81c", version: 2, expires_at: "2027-01-15T15:00:00Z", ask: "When?" }
    fetchMock.mockImplementationOnce(() => new Response(JSON.stringify({
      request_id: sent().request_id, request_completed: true, revision: 0,
      schedule: { id: 1, date: DAY, revision: 0, status: "active" },
      blocks: null, applied: false, ask: "When?", pending_intent: intent,
    }), { status: 200 }))
    await first.chat.submitTurn("Move Gym", vi.fn())
    fetchMock.mockRejectedValue(new TypeError("lost"))
    await first.chat.submitTurn("14:00", vi.fn())
    const frozen = sent(1)
    first.state.reset("dispose")
    const second = setup()
    fetchMock.mockImplementationOnce(() => success())
    await second.chat.recoverPending(vi.fn())
    expect(sent(3)).toEqual(frozen)
    expect(frozen).toMatchObject({ pending_intent_id: intent.id, pending_intent_version: 2, intent_action: "continue" })
    expect(second.chat.hasPendingRequest.value).toBe(false)
  })

  it.each([
    { pending_intent_id: "bad", pending_intent_version: 1 },
    { pending_intent_version: 1 },
    { intent_action: "cancel" },
    { pending_intent_id: crypto.randomUUID(), pending_intent_version: true },
  ])("rejects malformed persisted intent references %#", extra => {
    sessionStorage.setItem(`day-forge:chat-request:7:${DAY}`, JSON.stringify({
      userId: 7, date: DAY, body: { request_id: crypto.randomUUID(), expected_revision: 0,
      messages: [{ role: "user", content: "14:00" }], ...extra },
    }))
    expect(readChatRequest(7, DAY)).toBeNull()
  })

  it.each(["network", "body", "empty", "wrong identity"])("recovers a lost %s response with the identical body and one Undo", async mode => {
    const { chat, state } = setup()
    if (mode === "network") fetchMock.mockRejectedValueOnce(new TypeError("lost response"))
    else if (mode === "body") fetchMock.mockResolvedValueOnce({ status: 200, ok: true, text: async () => { throw new Error("truncated body") } })
    else if (mode === "empty") fetchMock.mockResolvedValueOnce(new Response("", { status: 200 }))
    else fetchMock.mockResolvedValueOnce(new Response(JSON.stringify({ request_completed: true, request_id: crypto.randomUUID() }), { status: 200 }))
    fetchMock.mockImplementationOnce(() => success())
    const pushUndo = vi.fn()
    await chat.submitTurn("Add Smoke at 14:00", pushUndo)
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(fetchMock.mock.calls[0][1].body).toBe(fetchMock.mock.calls[1][1].body)
    expect(sent().request_id).toMatch(/^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/)
    expect(state.blocks.value).toEqual([BLOCK])
    expect(chat.hasPendingRequest.value).toBe(false)
    expect(chat.messages.value).toHaveLength(2)
    expect(chat.messages.value[1].isError).not.toBe(true)
    expect(pushUndo).toHaveBeenCalledTimes(1)
    expect(sessionStorage.length).toBe(0)
  })

  it("keeps an in-progress request, blocks a new turn, and recovers without a second user bubble", async () => {
    const { chat } = setup()
    fetchMock.mockRejectedValueOnce(new TypeError("uncertain"))
      .mockResolvedValueOnce(new Response(JSON.stringify({ code: "request_in_progress" }), { status: 409 }))
    await chat.submitTurn("Add Smoke", vi.fn())
    expect(chat.hasPendingRequest.value).toBe(true)
    expect(chat.messages.value).toHaveLength(1)
    const original = sent()
    await chat.submitTurn("try again", vi.fn())
    expect(fetchMock).toHaveBeenCalledTimes(2)
    expect(chat.draftInput.value).toBe("try again")
    fetchMock.mockImplementationOnce(() => success())
    await chat.recoverPending(vi.fn())
    expect(sent(2)).toEqual(original)
    expect(chat.messages.value.map(m => m.role)).toEqual(["user", "assistant"])
    expect(chat.hasPendingRequest.value).toBe(false)
  })

  it("treats a stored provider failure as final and mints a new ID for an explicit retry", async () => {
    const { chat } = setup()
    fetchMock.mockImplementationOnce(() => new Response(JSON.stringify({ request_id: sent(fetchMock.mock.calls.length - 1).request_id, request_completed: true, errors: { detail: "Provider offline" } }), { status: 502 }))
    await chat.submitTurn("Add Smoke", vi.fn())
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(chat.hasPendingRequest.value).toBe(false)
    expect(chat.messages.value[1].isError).toBe(true)
    fetchMock.mockImplementationOnce(() => success())
    await chat.submitTurn("try again", vi.fn())
    expect(sent(1).request_id).not.toBe(sent().request_id)
    expect(sent(1).messages[1].is_error).toBe(true)
  })

  it("restores the frozen request after remount, preserves the original revision, and adds no invalid Undo", async () => {
    const first = setup()
    fetchMock.mockRejectedValue(new TypeError("offline"))
    await first.chat.submitTurn("Add Smoke", vi.fn())
    const original = sent()
    first.state.reset("dispose")
    const second = setup(7, 1, [BLOCK])
    expect(second.chat.hasPendingRequest.value).toBe(true)
    fetchMock.mockImplementationOnce(() => success())
    const pushUndo = vi.fn()
    await second.chat.recoverPending(pushUndo)
    expect(sent(2)).toEqual(original)
    expect(sent(2).expected_revision).toBe(0)
    expect(second.state.blocks.value).toEqual([BLOCK])
    expect(pushUndo).not.toHaveBeenCalled()
    expect(sessionStorage.length).toBe(0)
  })

  it("reconciles a stored older snapshot without rewinding a newer manual edit", async () => {
    const first = setup()
    fetchMock.mockRejectedValue(new TypeError("offline"))
    await first.chat.submitTurn("Add Smoke", vi.fn())
    first.state.reset("dispose")
    const manual = { ...BLOCK, id: 2, title: "Manual", start_time: "16:00", end_time: "16:30" }
    const second = setup(7, 2, [BLOCK, manual])
    fetchMock.mockImplementationOnce(() => success())
    const pushUndo = vi.fn()
    await second.chat.recoverPending(pushUndo)
    expect(second.state.revision.value).toBe(2)
    expect(second.state.blocks.value).toEqual([BLOCK, manual])
    expect(pushUndo).not.toHaveBeenCalled()
    expect(second.chat.hasPendingRequest.value).toBe(false)
  })

  it("clears unresolved private bodies on Logout and prevents old-scope transport retries", async () => {
    const first = setup()
    let reject!: (reason: unknown) => void
    fetchMock.mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
    const turn = first.chat.submitTurn("Private request", vi.fn())
    expect(sessionStorage.length).toBe(1)
    first.state.reset("session")
    reject(new TypeError("lost after Logout"))
    await turn
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(sessionStorage.length).toBe(0)
    expect(first.chat.messages.value).toEqual([])
  })

  it("clears stored bodies at the root account boundary even after the owner is disposed", async () => {
    const first = setup()
    fetchMock.mockRejectedValue(new TypeError("offline"))
    await first.chat.submitTurn("Private request", vi.fn())
    first.state.reset("dispose")
    expect(sessionStorage.length).toBe(1)
    retainChatRequestsForUser(8)
    expect(sessionStorage.length).toBe(0)
    expect(setup(8).chat.hasPendingRequest.value).toBe(false)
  })

  it("refuses to send if recovery storage is unavailable and restores the input", async () => {
    const { chat } = setup()
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota") })
    await chat.submitTurn("Add Smoke", vi.fn())
    expect(fetchMock).not.toHaveBeenCalled()
    expect(chat.draftInput.value).toBe("Add Smoke")
    expect(chat.lastError.value).toContain("Enable session storage")
  })

  it("does not issue an automatic transport retry after a logical clear", async () => {
    const { chat } = setup()
    let reject!: (reason: unknown) => void
    fetchMock.mockImplementationOnce(() => new Promise((_, fail) => { reject = fail }))
    const turn = chat.submitTurn("Add Smoke", vi.fn())
    chat.clearThread()
    reject(new TypeError("lost response"))
    await turn
    expect(fetchMock).toHaveBeenCalledTimes(1)
    expect(chat.messages.value).toEqual([])
    expect(chat.hasPendingRequest.value).toBe(true)
  })
})
