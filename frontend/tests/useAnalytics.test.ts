import { describe, it, expect, vi, beforeEach } from "vitest"

vi.mock("@inertiajs/vue3", () => ({
  router: { reload: vi.fn() },
}))

import { useAnalytics as actualUseAnalytics } from "../src/composables/useAnalytics"
import { router } from "@inertiajs/vue3"
import { createScheduleRevision } from "../src/composables/useScheduleRevision"
import { nextTick, ref } from "vue"
import { makeRevisionState, revisionEnvelope } from "./helpers/schedule"
function useAnalytics() { return actualUseAnalytics(makeRevisionState("2026-04-18")) }

function okJson(body: Record<string, unknown>) {
  return {
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify({ ...body, ...revisionEnvelope("2026-04-18") })),
  }
}

function errJson(status: number, body: Record<string, unknown>) {
  return {
    ok: false,
    status,
    text: () => Promise.resolve(JSON.stringify(body)),
  }
}

describe("useAnalytics", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.mocked(router.reload).mockClear()
    vi.mocked(router.reload).mockImplementation((options) => { options?.onSuccess?.({} as never); options?.onFinish?.({} as never) })
    document.cookie = "XSRF-TOKEN=; expires=Thu, 01 Jan 1970 00:00:00 GMT"
    const { clearError } = useAnalytics()
    clearError()
  })

  it("binds review writes to the captured account identity", async () => {
    const owner = createScheduleRevision("2026-04-18", () => ({ id: 1, date: "2026-04-18", status: "active", revision: 0 }), { getBlocks: () => [], getUserId: () => 7 })
    const analytics = actualUseAnalytics(owner)
    const fetchSpy = vi.fn().mockResolvedValue(okJson({ id: 1 }))
    vi.stubGlobal("fetch", fetchSpy)
    await analytics.markReviewed("2026-04-18")
    expect(fetchSpy.mock.calls[0][1].headers["X-Schedule-User"]).toBe("7")
  })

  it("keeps a successful review successful when its display reload fails", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okJson({ id: 1 })))
    vi.mocked(router.reload).mockImplementationOnce((options) => { options?.onError?.({ detail: "offline" }); options?.onFinish?.({} as never) })
    const analytics = useAnalytics()
    const result = await analytics.markReviewed("2026-04-18")
    expect(result.ok).toBe(true)
    expect(result.code).toBe("schedule_sync_failed")
    expect(analytics.lastError.value).toBe("Changes were saved, but the display could not refresh. Reload the page.")
    expect(analytics.isMarkingReviewed.value).toBe(false)
    expect(fetch).toHaveBeenCalledTimes(1)
  })

  it("does not leak a departed day's review failure into the current day", async () => {
    const date = ref("2026-04-18")
    const owner = createScheduleRevision(() => date.value, () => ({ id: 1, date: date.value, status: "active", revision: 0 }), { getBlocks: () => [] })
    const analytics = actualUseAnalytics(owner)
    let resolve!: (value: ReturnType<typeof errJson>) => void
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise((done) => { resolve = done })))
    const pending = analytics.markReviewed(date.value)
    date.value = "2026-04-19"
    resolve(errJson(400, { errors: { detail: "Old review failed" } }))
    await pending
    expect(analytics.lastError.value).toBeNull()
    expect(analytics.isMarkingReviewed.value).toBe(false)
    expect(router.reload).not.toHaveBeenCalled()
  })

  it("notes remain outside revision and stale errors stay on their original scope", async () => {
    const date = ref("2026-04-18")
    const owner = createScheduleRevision(() => date.value, () => ({ id: 1, date: date.value, status: "active", revision: 0 }), { getBlocks: () => [] })
    const analytics = actualUseAnalytics(owner)
    let resolve!: (value: ReturnType<typeof errJson>) => void
    const fetchSpy = vi.fn().mockReturnValue(new Promise((done) => { resolve = done }))
    vi.stubGlobal("fetch", fetchSpy)
    const pending = analytics.saveNotes("2026-04-18", "Old note")
    expect(owner.phase.value).toBe("idle")
    expect(owner.revision.value).toBe(0)
    date.value = "2026-04-19"
    resolve(errJson(400, { errors: { detail: "Old notes failed" } }))
    await pending
    expect(analytics.lastError.value).toBeNull()
    expect(JSON.parse(fetchSpy.mock.calls[0][1].body)).toEqual({ notes: "Old note" })
    expect(owner.revision.value).toBe(0)
  })

  it("invalid notes sessions clear the owner and ignore old note results", async () => {
    const owner = makeRevisionState("2026-04-18")
    const analytics = actualUseAnalytics(owner)
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(errJson(401, { code: "session_invalid" })))
    await analytics.saveNotes("2026-04-18", "Private note")
    expect(owner.schedule.value).toBeNull()
    expect(analytics.lastError.value).toBeNull()
  })

  it("markReviewed without notes sends the expected revision", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(okJson({ id: 1, notes: "" }))
    vi.stubGlobal("fetch", fetchSpy)

    const { markReviewed } = useAnalytics()
    const result = await markReviewed("2026-04-18")
    expect(result.ok).toBe(true)
    const [url, options] = fetchSpy.mock.calls[0]
    expect(url).toBe("/api/analytics/schedules/2026-04-18/mark-reviewed/")
    expect(options.method).toBe("POST")
    expect(JSON.parse(options.body)).toEqual({ expected_revision: 0 })
  })

  it("markReviewed with notes sends body", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(okJson({ id: 1, notes: "ok" }))
    vi.stubGlobal("fetch", fetchSpy)

    const { markReviewed } = useAnalytics()
    await markReviewed("2026-04-18", "Felt focused")
    const [, options] = fetchSpy.mock.calls[0]
    expect(JSON.parse(options.body)).toEqual({ notes: "Felt focused", expected_revision: 0 })
  })

  it("markReviewed refreshes review with coherent schedule and blocks on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okJson({ id: 1 })))
    const { markReviewed } = useAnalytics()
    await markReviewed("2026-04-18")
    expect(router.reload).toHaveBeenCalledWith(expect.objectContaining({
      only: ["blocks", "schedule", "review", "streak", "auth_user_id", "schedule_window"],
    }))
  })

  it("markReviewed surfaces 400 errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(errJson(400, { errors: { detail: "draft" } })),
    )
    const { markReviewed, lastError } = useAnalytics()
    const result = await markReviewed("2026-04-18")
    expect(result.ok).toBe(false)
    expect(lastError.value).toBe("draft")
  })

  it("saveNotes PATCHes the right URL and body", async () => {
    const fetchSpy = vi.fn().mockResolvedValue(okJson({ id: 7, notes: "x" }))
    vi.stubGlobal("fetch", fetchSpy)
    const { saveNotes } = useAnalytics()
    await saveNotes("2026-04-18", "x")
    const [url, options] = fetchSpy.mock.calls[0]
    expect(url).toBe("/api/analytics/schedules/2026-04-18/notes/")
    expect(options.method).toBe("PATCH")
    expect(JSON.parse(options.body)).toEqual({ notes: "x" })
  })

  it("binds note writes to the captured account without changing schedule revision", async () => {
    const owner = createScheduleRevision("2026-04-18", () => ({ id: 1, date: "2026-04-18", status: "active", revision: 4 }), { getBlocks: () => [], getUserId: () => 7 })
    const fetchSpy = vi.fn().mockResolvedValue(okJson({ id: 9, notes: "memo" }))
    vi.stubGlobal("fetch", fetchSpy)
    await actualUseAnalytics(owner).saveNotes("2026-04-18", "memo", 7)
    expect(fetchSpy.mock.calls[0][1].headers["X-Schedule-User"]).toBe("7")
    expect(owner.revision.value).toBe(4)
    expect(owner.phase.value).toBe("idle")
  })

  it("serializes notes and waits for the latest note before marking reviewed", async () => {
    const owner = makeRevisionState("2026-04-18")
    const analytics = actualUseAnalytics(owner)
    let resolveFirst!: (value: ReturnType<typeof okJson>) => void
    let resolveSecond!: (value: ReturnType<typeof okJson>) => void
    const fetchSpy = vi.fn()
      .mockReturnValueOnce(new Promise((done) => { resolveFirst = done }))
      .mockReturnValueOnce(new Promise((done) => { resolveSecond = done }))
      .mockResolvedValue(okJson({ id: 1 }))
    vi.stubGlobal("fetch", fetchSpy)

    const first = analytics.saveNotes("2026-04-18", "older")
    const second = analytics.saveNotes("2026-04-18", "newest")
    const mark = analytics.markReviewed("2026-04-18", "newest")
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    resolveFirst(okJson({ notes: "older" }))
    await first
    await vi.waitFor(() => expect(fetchSpy).toHaveBeenCalledTimes(2))
    expect(fetchSpy.mock.calls[1][0]).toBe("/api/analytics/schedules/2026-04-18/notes/")
    resolveSecond(okJson({ notes: "newest" }))
    await second
    await mark
    expect(fetchSpy).toHaveBeenCalledTimes(3)
    expect(fetchSpy.mock.calls[2][0]).toBe("/api/analytics/schedules/2026-04-18/mark-reviewed/")
    expect(JSON.parse(fetchSpy.mock.calls[2][1].body).notes).toBe("newest")
  })

  it("saves a later note after an in-flight review finishes", async () => {
    const analytics = useAnalytics()
    let resolveMark!: (value: ReturnType<typeof okJson>) => void
    const fetchSpy = vi.fn()
      .mockReturnValueOnce(new Promise((done) => { resolveMark = done }))
      .mockResolvedValueOnce(okJson({ notes: "newer note" }))
    vi.stubGlobal("fetch", fetchSpy)

    const mark = analytics.markReviewed("2026-04-18", "older note")
    expect(fetchSpy).toHaveBeenCalledTimes(1)
    expect(fetchSpy.mock.calls[0][0]).toBe("/api/analytics/schedules/2026-04-18/mark-reviewed/")
    const laterSave = analytics.saveNotes("2026-04-18", "newer note")
    await Promise.resolve()
    expect(fetchSpy).toHaveBeenCalledTimes(1)

    resolveMark(okJson({ id: 1 }))
    await mark
    await laterSave
    expect(fetchSpy).toHaveBeenCalledTimes(2)
    expect(fetchSpy.mock.calls[1][0]).toBe("/api/analytics/schedules/2026-04-18/notes/")
    expect(JSON.parse(fetchSpy.mock.calls[1][1].body)).toEqual({ notes: "newer note" })
  })

  it("does not let a late earlier note failure replace the latest save error", async () => {
    const analytics = useAnalytics()
    let resolveOld!: (value: ReturnType<typeof errJson>) => void
    const fetchSpy = vi.fn()
      .mockReturnValueOnce(new Promise((done) => { resolveOld = done }))
      .mockResolvedValueOnce(errJson(400, { errors: { detail: "Latest save failed" } }))
    vi.stubGlobal("fetch", fetchSpy)
    const old = analytics.saveNotes("2026-04-18", "old")
    const latest = analytics.saveNotes("2026-04-18", "latest")
    resolveOld(errJson(400, { errors: { detail: "Old save failed" } }))
    await old
    await latest
    expect(analytics.lastError.value).toBe("Latest save failed")
  })

  it("ignores an old failure after navigating away and back to the same date", async () => {
    const date = ref("2026-04-18")
    const owner = createScheduleRevision(() => date.value, () => ({ id: 1, date: date.value, status: "active", revision: 0 }), { getBlocks: () => [] })
    const analytics = actualUseAnalytics(owner)
    let resolveOld!: (value: ReturnType<typeof errJson>) => void
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(new Promise((done) => { resolveOld = done })))
    const old = analytics.saveNotes("2026-04-18", "old")
    date.value = "2026-04-19"
    await nextTick()
    date.value = "2026-04-18"
    await nextTick()
    resolveOld(errJson(400, { errors: { detail: "Old failure" } }))
    await old
    expect(analytics.lastError.value).toBeNull()
  })

  it("keeps the new day's error when an older notes response arrives late", async () => {
    const date = ref("2026-04-18")
    const owner = createScheduleRevision(() => date.value, () => ({ id: 1, date: date.value, status: "active", revision: 0 }), { getBlocks: () => [] })
    const analytics = actualUseAnalytics(owner)
    let resolveOld!: (value: ReturnType<typeof errJson>) => void
    const fetchSpy = vi.fn()
      .mockReturnValueOnce(new Promise((done) => { resolveOld = done }))
      .mockResolvedValueOnce(errJson(400, { errors: { detail: "New day failed" } }))
    vi.stubGlobal("fetch", fetchSpy)
    const old = analytics.saveNotes("2026-04-18", "old")
    date.value = "2026-04-19"
    await nextTick()
    await analytics.saveNotes("2026-04-19", "new")
    expect(analytics.lastError.value).toBe("New day failed")
    resolveOld(errJson(400, { errors: { detail: "Old day failed" } }))
    await old
    expect(analytics.lastError.value).toBe("New day failed")
  })

  it("drops a queued unsent draft when the account changes", async () => {
    const userId = ref(7)
    const owner = createScheduleRevision("2026-04-18", () => ({ id: 1, date: "2026-04-18", status: "active", revision: 0 }), { getBlocks: () => [], getUserId: () => userId.value })
    const analytics = actualUseAnalytics(owner)
    let resolveFirst!: (value: ReturnType<typeof okJson>) => void
    const fetchSpy = vi.fn().mockReturnValueOnce(new Promise((done) => { resolveFirst = done }))
    vi.stubGlobal("fetch", fetchSpy)
    const first = analytics.saveNotes("2026-04-18", "already sent", 7)
    const queued = analytics.saveNotes("2026-04-18", "queued", 7)
    userId.value = 8
    await nextTick()
    resolveFirst(okJson({ notes: "already sent" }))
    await first
    expect((await queued).code).toBe("stale")
    expect(fetchSpy).toHaveBeenCalledTimes(1)
  })

  // Fallback-literal guards (features 0037/0038): pin each method's exact
  // fallback because useAnalytics intentionally uses two distinct strings.
  describe("fallback-literal guards", () => {
    it("markReviewed surfaces the exact fallback literal on an empty errors map", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(errJson(500, { errors: {} })),
      )
      const { markReviewed, lastError } = useAnalytics()
      const result = await markReviewed("2026-04-18")
      expect(result.ok).toBe(false)
      expect(lastError.value).toBe("Could not mark this day reviewed.")
      // A server failure has an unknown commit outcome and reconciles once.
      expect(vi.mocked(router.reload)).toHaveBeenCalledTimes(1)
    })

    it("saveNotes surfaces the exact fallback literal on an empty errors map", async () => {
      vi.stubGlobal(
        "fetch",
        vi.fn().mockResolvedValue(errJson(500, { errors: {} })),
      )
      const { saveNotes, lastError } = useAnalytics()
      const result = await saveNotes("2026-04-18", "x")
      expect(result.ok).toBe(false)
      expect(lastError.value).toBe("Could not save notes.")
    })
  })
})
