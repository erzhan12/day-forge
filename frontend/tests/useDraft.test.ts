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
  requestJson: (...args: unknown[]) => requestJsonMock(...args),
}))

vi.mock("@inertiajs/vue3", () => ({
  router: { reload: routerReload },
}))

import {
  _peekLatestRequestId,
  _resetDraftStateForTests,
  useDraft,
} from "../src/composables/useDraft"

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
  })

  afterEach(() => {
    _resetDraftStateForTests()
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
    expect(isGeneratingDraft.value).toBe(true)
    expect(_peekLatestRequestId()).toBe(2)

    draftA.resolve({ ok: true, data: { explanation: "stale" } })
    await pA

    expect(isGeneratingDraft.value).toBe(true)
    expect(routerReload).not.toHaveBeenCalled()

    draftB.resolve({ ok: true, data: { explanation: "current" } })
    await pB

    expect(isGeneratingDraft.value).toBe(false)
    expect(routerReload).toHaveBeenCalledTimes(1)
    expect(routerReload).toHaveBeenCalledWith({
      only: ["blocks", "schedule"],
    })
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

  it("stale in-flight draft does not set lastDraftError from a failed response", async () => {
    const draftA = makeDeferred()
    const draftB = makeDeferred()
    requestJsonMock
      .mockReturnValueOnce(draftA.promise)
      .mockReturnValueOnce(draftB.promise)

    const { generateDraft, lastDraftError } = useDraft()

    const pA = generateDraft("2026-05-04")
    const pB = generateDraft("2026-05-05")

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
