// Tests for useDraft in-flight request token guard.
//
// Overlapping generateDraft calls (auto-draft on date navigation during a
// slow LLM) must not clear isGeneratingDraft early or router.reload from a
// stale resolver — that unlocks edits mid-flight and stomps them.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

const { requestJsonMock, routerReload } = vi.hoisted(() => ({
  requestJsonMock: vi.fn(),
  routerReload: vi.fn(),
}))

vi.mock("../src/composables/useHttp", () => ({
  requestJson: async (...args: unknown[]) => {
    const result = await requestJsonMock(...args)
    if (!result.ok) return result
    const date = String(args[0]).split("/")[4]
    return { ...result, data: { blocks: [], ...result.data, revision: 1, schedule: { id: 1, date, status: "draft", revision: 1 } } }
  },
}))

vi.mock("@inertiajs/vue3", () => ({
  router: { reload: routerReload },
}))

import {
  _peekLatestRequestId,
  _resetDraftStateForTests,
  useDraft as actualUseDraft,
} from "../src/composables/useDraft"

import { nextTick, ref } from "vue"
import { createScheduleRevision } from "../src/composables/useScheduleRevision"
import { makeRevisionState } from "./helpers/schedule"
function useDraft() {
  const date = ref("2026-05-04")
  const draft = actualUseDraft(makeRevisionState(() => date.value))
  return { ...draft, generateDraft: (nextDate: string, pushUndo?: Parameters<typeof draft.generateDraft>[1]) => {
    if (date.value === nextDate) return draft.generateDraft(nextDate, pushUndo)
    date.value = nextDate
    return nextTick().then(() => draft.generateDraft(nextDate, pushUndo))
  } }
}

function makeDeferred() {
  let resolve!: (value: { ok: boolean; data?: unknown }) => void
  const promise = new Promise<{ ok: boolean; data?: unknown }>((res) => {
    resolve = res
  })
  return { resolve, promise }
}

describe("useDraft", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    _resetDraftStateForTests()
    routerReload.mockImplementation((options) => { options.onSuccess?.(); options.onFinish?.() })
  })

  afterEach(() => {
    _resetDraftStateForTests()
    routerReload.mockImplementation((options) => { options.onSuccess?.(); options.onFinish?.() })
  })

  it("binds draft writes to the captured account identity", async () => {
    const owner = createScheduleRevision("2026-05-04", () => ({ id: 1, date: "2026-05-04", status: "active", revision: 0 }), { getBlocks: () => [], getUserId: () => 7 })
    const draft = actualUseDraft(owner)
    requestJsonMock.mockResolvedValue({ ok: true, data: { blocks: [] } })
    await draft.generateDraft("2026-05-04")
    expect(requestJsonMock.mock.calls[0][3]).toEqual({ expectedUserId: 7 })
  })

  it("keeps two active owners' draft state independent", () => {
    const firstOwner = makeRevisionState("2026-05-04")
    const secondOwner = makeRevisionState("2026-05-04")
    const first = actualUseDraft(firstOwner)
    const second = actualUseDraft(secondOwner)
    first.lastDraftError.value = "First owner error"
    first.isGeneratingDraft.value = true

    expect(second.lastDraftError.value).toBeNull()
    expect(second.isGeneratingDraft.value).toBe(false)
    firstOwner.reset("session")
    expect(first.lastDraftError.value).toBeNull()
    expect(second.lastDraftError.value).toBeNull()
  })

  it("records undo from the accepted draft diff with its expected revision", async () => {
    const draft = useDraft()
    const pushUndo = vi.fn()
    const block = { id: 1, title: "Draft", start_time: "09:00", end_time: "10:00", category: "work", is_completed: false, sort_order: 0 }
    requestJsonMock.mockResolvedValueOnce({ ok: true, data: { explanation: "Created", blocks: [block] } })
    const result = await draft.generateDraft("2026-05-04", pushUndo)
    expect(result.ok).toBe(true)
    expect(pushUndo).toHaveBeenCalledWith(expect.objectContaining({ type: "draft", previousBlocks: [], expected_revision: 1, previous_revision: 0 }))
    expect(routerReload).not.toHaveBeenCalled()
  })

  it("a successful no-op draft does not create undo", async () => {
    const draft = useDraft()
    const pushUndo = vi.fn()
    requestJsonMock.mockResolvedValueOnce({ ok: true, data: { blocks: [] } })
    await draft.generateDraft("2026-05-04", pushUndo)
    expect(pushUndo).not.toHaveBeenCalled()
  })

  it("clears draft errors and invalidates an old response when the session ends", async () => {
    const owner = makeRevisionState("2026-05-04")
    const draft = actualUseDraft(owner)
    const deferred = makeDeferred()
    requestJsonMock.mockReturnValueOnce(deferred.promise)
    const pending = draft.generateDraft("2026-05-04", vi.fn())
    owner.reset("session")
    expect(draft.isGeneratingDraft.value).toBe(false)
    expect(draft.lastDraftError.value).toBeNull()
    deferred.resolve({ ok: false, errors: { detail: "Old failure" } })
    await pending
    expect(draft.lastDraftError.value).toBeNull()
    expect(routerReload).not.toHaveBeenCalled()
  })

  it("stale in-flight draft does not clear spinner or reload", async () => {
    const draftA = makeDeferred()
    const draftB = makeDeferred()
    requestJsonMock
      .mockReturnValueOnce(draftA.promise)
      .mockReturnValueOnce(draftB.promise)

    const { generateDraft, isGeneratingDraft } = useDraft()

    const pA = generateDraft("2026-05-04")
    expect(isGeneratingDraft.value).toBe(true)
    expect(_peekLatestRequestId()).toBe(1)

    const pB = generateDraft("2026-05-05")
    await nextTick()
    expect(isGeneratingDraft.value).toBe(true)
    expect(_peekLatestRequestId()).toBeGreaterThan(2)

    draftA.resolve({ ok: true, data: { explanation: "stale" } })
    await pA

    expect(isGeneratingDraft.value).toBe(true)
    expect(routerReload).not.toHaveBeenCalled()

    draftB.resolve({ ok: true, data: { explanation: "current" } })
    await pB

    expect(isGeneratingDraft.value).toBe(false)
    expect(routerReload).not.toHaveBeenCalled()
  })

  it("abandonInFlight clears spinner and stale-completes without reload", async () => {
    const draft = makeDeferred()
    requestJsonMock.mockReturnValueOnce(draft.promise)

    const { generateDraft, isGeneratingDraft, abandonInFlight } = useDraft()
    const p = generateDraft("2026-05-04")
    expect(isGeneratingDraft.value).toBe(true)

    abandonInFlight()
    expect(isGeneratingDraft.value).toBe(false)

    draft.resolve({ ok: true, data: { explanation: "abandoned" } })
    await p

    expect(isGeneratingDraft.value).toBe(false)
    expect(routerReload).not.toHaveBeenCalled()
  })

  it("sends the expected revision and never reads the browser timezone", async () => {
    const formatSpy = vi.spyOn(Intl, "DateTimeFormat")
    requestJsonMock.mockResolvedValue({ ok: true, data: { explanation: "ok" } })
    const { generateDraft } = useDraft()

    await generateDraft("2026-05-04")
    await generateDraft("2026-05-05")

    expect(requestJsonMock.mock.calls[0][2]).toEqual({ expected_revision: 0 })
    expect(requestJsonMock.mock.calls[1][2]).toEqual({ expected_revision: 0 })
    expect(formatSpy).not.toHaveBeenCalled()
    formatSpy.mockRestore()
  })

  it("stale in-flight draft does not set lastDraftError from a failed response", async () => {
    const draftA = makeDeferred()
    const draftB = makeDeferred()
    requestJsonMock
      .mockReturnValueOnce(draftA.promise)
      .mockReturnValueOnce(draftB.promise)

    const { generateDraft, lastDraftError } = useDraft()

    const pA = generateDraft("2026-05-04")
    const pB = generateDraft("2026-05-05")
    await nextTick()

    draftA.resolve({
      ok: false,
      status: 503,
      errors: { detail: "stale failure" },
    })
    await pA

    expect(lastDraftError.value).toBeNull()

    draftB.resolve({
      ok: false,
      status: 503,
      errors: { detail: "current failure" },
    })
    await pB

    expect(lastDraftError.value).toBe(
      "AI is unavailable. Manual editing still works.",
    )
  })
})

// Fallback-literal guard (feature 0037): pin the exact fallback string. A
// `default`-branch status (500) makes statusToMessage return null so
// control falls through to the shared helper; `errors: {}` yields the
// fallback. (503/429/422 resolve via statusToMessage; 409 early-returns at
// generateDraft before either helper runs.)
describe("useDraft fallback-literal guard", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    _resetDraftStateForTests()
    routerReload.mockImplementation((options) => { options.onSuccess?.(); options.onFinish?.() })
  })

  it("generateDraft surfaces the exact fallback literal on an empty errors map", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      errors: {},
    })
    const { generateDraft, lastDraftError } = useDraft()
    await generateDraft("2026-05-07")
    expect(lastDraftError.value).toBe("Draft generation failed")
  })
})
