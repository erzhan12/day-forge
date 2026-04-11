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
    expect(router.reload).toHaveBeenCalledWith({ only: ["blocks"] })
  })

  it("returns errors on 400", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false,
      status: 400,
      json: () => Promise.resolve({ errors: { title: "Required" } }),
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
      json: () => Promise.reject(new Error("not json")),
    }))

    const { deleteBlock } = useSchedule("2026-04-10")
    const result = await deleteBlock(1)

    expect(result.ok).toBe(false)
    expect(result.errors?.detail).toMatch(/500/)
  })
})
