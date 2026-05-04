import { describe, it, expect, vi, beforeEach } from "vitest"

vi.mock("@inertiajs/vue3", () => ({
  router: { reload: vi.fn() },
}))

import { useAnalytics } from "../src/composables/useAnalytics"
import { router } from "@inertiajs/vue3"

function okJson(body: Record<string, unknown>) {
  return {
    ok: true,
    status: 200,
    text: () => Promise.resolve(JSON.stringify(body)),
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
    document.cookie = "XSRF-TOKEN=; expires=Thu, 01 Jan 1970 00:00:00 GMT"
    const { clearError } = useAnalytics()
    clearError()
  })

  it("markReviewed without notes sends no body", async () => {
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
    expect(options.body).toBeUndefined()
  })

  it("markReviewed with notes sends body", async () => {
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(okJson({ id: 1, notes: "ok" }))
    vi.stubGlobal("fetch", fetchSpy)

    const { markReviewed } = useAnalytics()
    await markReviewed("2026-04-18", "Felt focused")
    const [, options] = fetchSpy.mock.calls[0]
    expect(JSON.parse(options.body)).toEqual({ notes: "Felt focused" })
  })

  it("markReviewed reloads only review + schedule on success", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(okJson({ id: 1 })))
    const { markReviewed } = useAnalytics()
    await markReviewed("2026-04-18")
    expect(router.reload).toHaveBeenCalledWith({
      only: ["review", "schedule"],
    })
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
    await saveNotes(7, "x")
    const [url, options] = fetchSpy.mock.calls[0]
    expect(url).toBe("/api/analytics/reviews/7/notes/")
    expect(options.method).toBe("PATCH")
    expect(JSON.parse(options.body)).toEqual({ notes: "x" })
  })
})
