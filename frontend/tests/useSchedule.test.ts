import { describe, it, expect, vi, beforeEach } from "vitest"

// Mock @inertiajs/vue3 before importing the composable
vi.mock("@inertiajs/vue3", () => ({
  router: { reload: vi.fn() },
}))

import { useSchedule } from "../src/composables/useSchedule"
import { router } from "@inertiajs/vue3"

describe("useSchedule", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.mocked(router.reload).mockClear()
    // Clear cookies
    document.cookie = "XSRF-TOKEN=; expires=Thu, 01 Jan 1970 00:00:00 GMT"
  })

  it("reads CSRF token from cookie", async () => {
    document.cookie = "XSRF-TOKEN=test-token-123"
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('{"id":1}'),
    })
    vi.stubGlobal("fetch", fetchSpy)

    const { createBlock } = useSchedule("2026-04-10")
    await createBlock({ title: "X", start_time: "09:00", end_time: "10:00", category: "work" })

    expect(fetchSpy).toHaveBeenCalledOnce()
    const headers = fetchSpy.mock.calls[0][1].headers
    expect(headers["X-XSRF-TOKEN"]).toBe("test-token-123")
  })

  it("returns ok and data on success", async () => {
    const body = { id: 1, title: "Test" }
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve(JSON.stringify(body)),
    }))

    const { createBlock } = useSchedule("2026-04-10")
    const result = await createBlock({ title: "Test", start_time: "09:00", end_time: "10:00", category: "work" })

    expect(result.ok).toBe(true)
    expect(result.data).toEqual(body)
    expect(router.reload).toHaveBeenCalledWith({ only: ["blocks", "schedule"] })
  })

  it("resolves createBlock date lazily from a getter", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('{"id":1}'),
    })
    vi.stubGlobal("fetch", fetchSpy)

    let currentDate = "2026-04-10"
    const { createBlock } = useSchedule(() => currentDate)
    currentDate = "2026-04-11"

    await createBlock({
      title: "Moved-day add",
      start_time: "09:00",
      end_time: "10:00",
      category: "work",
    })

    expect(fetchSpy).toHaveBeenCalledOnce()
    expect(fetchSpy.mock.calls[0][0]).toBe(
      "/api/schedules/2026-04-11/blocks/",
    )
  })

  it("returns errors on 400", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      text: () =>
        Promise.resolve(JSON.stringify({ errors: { title: "Required" } })),
    }))

    const { createBlock } = useSchedule("2026-04-10")
    const result = await createBlock({ title: "", start_time: "09:00", end_time: "10:00", category: "work" })

    expect(result.ok).toBe(false)
    expect(result.errors).toEqual({ title: "Required" })
    expect(router.reload).not.toHaveBeenCalled()
  })

  it("returns network error on fetch rejection", async () => {
    vi.stubGlobal("fetch", vi.fn().mockRejectedValue(new TypeError("Failed to fetch")))

    const { deleteBlock } = useSchedule("2026-04-10")
    const result = await deleteBlock(1)

    expect(result.ok).toBe(false)
    expect(result.errors?.detail).toMatch(/network/i)
  })

  it("handles malformed JSON response gracefully", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve("not json"),
    }))

    const { updateBlock } = useSchedule("2026-04-10")
    const result = await updateBlock(1, { title: "X" })

    expect(result.ok).toBe(false)
    expect(result.errors?.detail).toMatch(/invalid/i)
  })

  it("handles non-JSON error response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 500,
      text: () => Promise.resolve("not json"),
    }))

    const { deleteBlock } = useSchedule("2026-04-10")
    const result = await deleteBlock(1)

    expect(result.ok).toBe(false)
    expect(result.errors?.detail).toMatch(/500/)
  })

  it("sends reorderBlocks with correct payload", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('{"blocks":[]}'),
    })
    vi.stubGlobal("fetch", fetchSpy)

    const { reorderBlocks } = useSchedule("2026-04-10")
    const updates = [
      { id: 1, start_time: "08:00", end_time: "09:00", sort_order: 0 },
      { id: 2, start_time: "09:00", end_time: "10:00", sort_order: 10 },
    ]
    const result = await reorderBlocks(updates)

    expect(result.ok).toBe(true)
    expect(fetchSpy).toHaveBeenCalledOnce()
    const [url, options] = fetchSpy.mock.calls[0]
    expect(url).toBe("/api/blocks/reorder/")
    expect(options.method).toBe("POST")
    expect(JSON.parse(options.body)).toEqual({ updates })
    expect(router.reload).toHaveBeenCalledWith({ only: ["blocks", "schedule"] })
  })

  it("sends restoreBlocks with correct payload", async () => {
    const fetchSpy = vi.fn().mockResolvedValue({
      ok: true,
      text: () => Promise.resolve('{"blocks":[]}'),
    })
    vi.stubGlobal("fetch", fetchSpy)

    const { restoreBlocks } = useSchedule("2026-04-10")
    const blocks = [
      { title: "A", start_time: "08:00", end_time: "09:00", category: "work", is_completed: false, sort_order: 0 },
    ]
    const result = await restoreBlocks("2026-04-10", blocks)

    expect(result.ok).toBe(true)
    expect(fetchSpy).toHaveBeenCalledOnce()
    const [url, options] = fetchSpy.mock.calls[0]
    expect(url).toBe("/api/schedules/2026-04-10/blocks/restore/")
    expect(options.method).toBe("POST")
    expect(JSON.parse(options.body)).toEqual({ blocks })
    expect(router.reload).toHaveBeenCalledWith({ only: ["blocks", "schedule"] })
  })
})
