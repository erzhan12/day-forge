import { describe, it, expect, vi, beforeEach } from "vitest"

vi.mock("@inertiajs/vue3", () => ({
  router: { reload: vi.fn() },
}))

import { useAI } from "../src/composables/useAI"
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

describe("useAI.submitCommand", () => {
  beforeEach(() => {
    vi.restoreAllMocks()
    vi.mocked(router.reload).mockClear()
    document.cookie = "XSRF-TOKEN=; expires=Thu, 01 Jan 1970 00:00:00 GMT"
    // Module-level refs persist across tests; reset healthy/error state.
    const { lastError, lastExplanation, apiHealthy, clearError } = useAI()
    clearError()
    lastExplanation.value = null
    apiHealthy.value = true
    void lastError
  })

  it("sends command with CSRF header and JSON body", async () => {
    document.cookie = "XSRF-TOKEN=csrf-xyz"
    const fetchSpy = vi
      .fn()
      .mockResolvedValue(okJson({ blocks: [], explanation: "ok" }))
    vi.stubGlobal("fetch", fetchSpy)

    const { submitCommand } = useAI()
    const result = await submitCommand("2026-04-18", "add standup")

    expect(result.ok).toBe(true)
    expect(result.explanation).toBe("ok")
    expect(fetchSpy).toHaveBeenCalledOnce()
    const [url, options] = fetchSpy.mock.calls[0]
    expect(url).toBe("/api/ai/schedules/2026-04-18/command/")
    expect(options.method).toBe("POST")
    expect(options.headers["X-XSRF-TOKEN"]).toBe("csrf-xyz")
    expect(JSON.parse(options.body)).toEqual({ command: "add standup" })
    expect(router.reload).toHaveBeenCalledWith({ only: ["blocks"] })
  })

  it("toggles isProcessing around the call", async () => {
    let captured = false
    vi.stubGlobal(
      "fetch",
      vi.fn().mockImplementation(() => {
        // Snapshot isProcessing while the promise is pending.
        captured = useAI().isProcessing.value
        return Promise.resolve(okJson({}))
      }),
    )

    const { submitCommand, isProcessing } = useAI()
    await submitCommand("2026-04-18", "hi")
    expect(captured).toBe(true)
    expect(isProcessing.value).toBe(false)
  })

  it("records explanation on success", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(okJson({ blocks: [], explanation: "Added" })),
    )
    const { submitCommand, lastExplanation } = useAI()
    await submitCommand("2026-04-18", "add")
    expect(lastExplanation.value).toBe("Added")
  })

  it("flips apiHealthy to false on 503", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(errJson(503, { errors: { detail: "no key" } })),
    )

    const { submitCommand, apiHealthy, lastError } = useAI()
    const result = await submitCommand("2026-04-18", "hi")

    expect(result.ok).toBe(false)
    expect(apiHealthy.value).toBe(false)
    expect(lastError.value).toMatch(/unavailable/i)
  })

  it("restores apiHealthy on next success", async () => {
    const { submitCommand, apiHealthy } = useAI()

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(errJson(502, { errors: { detail: "boom" } })),
    )
    await submitCommand("2026-04-18", "hi")
    expect(apiHealthy.value).toBe(false)

    vi.stubGlobal(
      "fetch",
      vi.fn().mockResolvedValue(okJson({ blocks: [], explanation: "ok" })),
    )
    await submitCommand("2026-04-18", "hi")
    expect(apiHealthy.value).toBe(true)
  })

  it("400 does not flip apiHealthy", async () => {
    vi.stubGlobal(
      "fetch",
      vi
        .fn()
        .mockResolvedValue(errJson(400, { errors: { command: "too long" } })),
    )
    const { submitCommand, apiHealthy } = useAI()
    await submitCommand("2026-04-18", "hi")
    expect(apiHealthy.value).toBe(true)
  })

  it("reports network errors", async () => {
    vi.stubGlobal(
      "fetch",
      vi.fn().mockRejectedValue(new TypeError("offline")),
    )
    const { submitCommand, lastError, apiHealthy } = useAI()
    const result = await submitCommand("2026-04-18", "hi")
    expect(result.ok).toBe(false)
    expect(lastError.value).toMatch(/network/i)
    expect(apiHealthy.value).toBe(false)
  })
})
