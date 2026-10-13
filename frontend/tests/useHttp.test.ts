import { afterEach, describe, expect, it, vi } from "vitest"
import { requestJson } from "../src/composables/useHttp"

afterEach(() => vi.unstubAllGlobals())

describe("mutation transport outcomes", () => {
  it("binds a schedule write to the account that supplied its snapshot", async () => {
    const fetch = vi.fn().mockResolvedValue({ ok: true, status: 200, text: () => Promise.resolve("{}") })
    vi.stubGlobal("fetch", fetch)
    await requestJson("/api/blocks/1/", "PATCH", {}, { expectedUserId: 42 })
    expect(fetch.mock.calls[0][1].headers["X-Schedule-User"]).toBe("42")
  })

  it("recognizes a login redirect instead of treating its HTML 200 as a mutation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, redirected: true,
      url: "http://localhost:5173/accounts/login/?next=/api/blocks/1/",
      text: () => Promise.resolve("<html>Sign in</html>"),
    }))
    expect(await requestJson("/api/blocks/1/", "PATCH", {})).toMatchObject({
      ok: false, status: 401, code: "session_invalid",
    })
  })

  it("recognizes an explicit unauthenticated response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 401 }))
    expect(await requestJson("/api/blocks/1/", "PATCH", {})).toMatchObject({ code: "session_invalid" })
  })

  it("keeps a CSRF rejection distinct from session invalidation", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 403, text: () => Promise.resolve("CSRF verification failed"),
    }))
    const result = await requestJson("/api/blocks/1/", "PATCH", {})
    expect(result).toMatchObject({ ok: false, status: 403 })
    expect(result.code).toBeUndefined()
  })

  it("preserves an explicit integration credential failure without invalidating the session", async () => {
    const body = {
      code: "integration_credentials_error",
      errors: { detail: "Invalid Todoist credentials" },
      meta: { account_state: "connected", resource_state: "credentials_error" },
    }
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 401, text: () => Promise.resolve(JSON.stringify(body)),
    }))
    expect(await requestJson("/api/todoist/tasks/2026-10-10/", "GET")).toMatchObject({
      ok: false, status: 401, code: "integration_credentials_error", data: body,
      errors: body.errors,
    })
  })

  it("requires the full credential error contract before distinguishing a 401", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 401,
      text: () => Promise.resolve(JSON.stringify({ code: "integration_credentials_error" })),
    }))
    expect(await requestJson("/api/todoist/tasks/2026-10-10/", "GET")).toMatchObject({
      code: "session_invalid",
    })
  })

  it("keeps explicit missing-account metadata on errors for provider adapters", async () => {
    const body = {
      code: "integration_account_missing", errors: { detail: "No account configured" },
      meta: { account_state: "disconnected", resource_state: "unavailable" },
    }
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: false, status: 503, text: () => Promise.resolve(JSON.stringify(body)),
    }))
    expect(await requestJson("/api/calendar/events/2026-10-10/", "GET")).toMatchObject({
      ok: false, status: 503, code: body.code, data: body,
    })
  })

  it.each(["null", "[]", '"ready"'])("rejects a non-object success body %s", async (body) => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, text: () => Promise.resolve(body),
    }))
    expect(await requestJson("/api/calendar/events/2026-10-10/", "GET")).toMatchObject({
      ok: false, status: 200, errors: { detail: "Invalid server response." },
    })
  })

  it("returns an uncertain outcome when the body is lost after success headers", async () => {
    const fetch = vi.fn().mockResolvedValue({
      ok: true, status: 200, text: () => Promise.reject(new TypeError("stream lost")),
    })
    vi.stubGlobal("fetch", fetch)
    expect(await requestJson("/api/blocks/1/", "PATCH", {})).toMatchObject({
      ok: false, status: 200,
      errors: { detail: expect.stringContaining("check whether the change was saved") },
    })
    expect(fetch).toHaveBeenCalledOnce()
  })

  it("propagates cancellation while reading a response body", async () => {
    const abort = new DOMException("Aborted", "AbortError")
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({
      ok: true, status: 200, text: () => Promise.reject(abort),
    }))
    await expect(requestJson("/api/calendar/events/2026-10-10/", "GET")).rejects.toBe(abort)
  })
})
