// Tests for useDailyExportToken.ts — status load, create (one-time raw
// disclosure), duplicate-create (token_exists), uncertain-outcome recovery,
// revoke/recreate, generation gating against stale responses, and dispose
// clearing the raw token from memory.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

type Deferred<T> = {
  promise: Promise<T>
  resolve: (v: T) => void
  reject: (e: unknown) => void
}

function defer<T>(): Deferred<T> {
  let resolve!: (v: T) => void
  let reject!: (e: unknown) => void
  const promise = new Promise<T>((res, rej) => {
    resolve = res
    reject = rej
  })
  return { promise, resolve, reject }
}

const requestJsonMock = vi.fn()

vi.mock("../src/composables/useHttp", () => ({
  requestJson: (...args: unknown[]) => requestJsonMock(...args),
}))

import { useDailyExportToken } from "../src/composables/useDailyExportToken"

describe("useDailyExportToken status", () => {
  beforeEach(() => requestJsonMock.mockReset())

  it("loads absent status", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      data: { has_token: false, created_at: null },
    })
    const token = useDailyExportToken()
    await token.fetchStatus()
    expect(token.state.hasToken).toBe(false)
    expect(token.state.createdAt).toBeNull()
  })

  it("loads active status without ever exposing a raw value", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      data: { has_token: true, created_at: "2026-08-29T09:00:00+00:00" },
    })
    const token = useDailyExportToken()
    await token.fetchStatus()
    expect(token.state.hasToken).toBe(true)
    expect(token.state.createdAt).toBe("2026-08-29T09:00:00+00:00")
    expect(token.state.rawToken).toBeNull()
  })

  it("surfaces a status load error", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      errors: { detail: "boom" },
    })
    const token = useDailyExportToken()
    await token.fetchStatus()
    expect(token.state.error).toBe("boom")
  })
})

describe("useDailyExportToken creation", () => {
  beforeEach(() => requestJsonMock.mockReset())

  it("reveals the raw token exactly once on success", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 201,
      data: { token: "dfx_abc123", has_token: true, created_at: "2026-08-29T09:00:00+00:00" },
    })
    const token = useDailyExportToken()
    const result = await token.createToken(42)
    expect(result.ok).toBe(true)
    expect(token.state.rawToken).toBe("dfx_abc123")
    expect(token.state.hasToken).toBe(true)
    expect(requestJsonMock).toHaveBeenCalledWith(
      "/api/user/export-token/", "POST", undefined, { expectedUserId: 42 },
    )
  })

  it("duplicate create (token_exists) refreshes status instead of fabricating a value", async () => {
    requestJsonMock
      .mockResolvedValueOnce({
        ok: false,
        status: 409,
        code: "token_exists",
        errors: { detail: "A token already exists." },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: { has_token: true, created_at: "2026-08-20T09:00:00+00:00" },
      })
    const token = useDailyExportToken()
    const result = await token.createToken(42)
    expect(result.ok).toBe(false)
    expect(token.state.rawToken).toBeNull()
    expect(token.state.hasToken).toBe(true)
    expect(token.state.createdAt).toBe("2026-08-20T09:00:00+00:00")
    expect(requestJsonMock).toHaveBeenCalledTimes(2)
  })

  it("an uncertain network failure refreshes status rather than assuming failure", async () => {
    requestJsonMock
      .mockResolvedValueOnce({
        ok: false,
        errors: { detail: "Network error. Please check your connection." },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: { has_token: true, created_at: "2026-08-20T09:00:00+00:00" },
      })
    const token = useDailyExportToken()
    await token.createToken(42)
    expect(token.state.hasToken).toBe(true)
    expect(token.state.rawToken).toBeNull()
    expect(requestJsonMock).toHaveBeenCalledTimes(2)
  })

  it("an interrupted response refreshes status", async () => {
    requestJsonMock
      .mockResolvedValueOnce({
        ok: false,
        status: 201,
        errors: {
          detail: "Server response was interrupted. Refresh to check whether the change was saved.",
        },
      })
      .mockResolvedValueOnce({
        ok: true,
        data: { has_token: true, created_at: "2026-08-20T09:00:00+00:00" },
      })
    const token = useDailyExportToken()
    await token.createToken(42)
    expect(token.state.hasToken).toBe(true)
    expect(requestJsonMock).toHaveBeenCalledTimes(2)
  })

  it("an ordinary validation failure surfaces its message without refetching", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 400,
      errors: { detail: "Nope." },
    })
    const token = useDailyExportToken()
    await token.createToken(42)
    expect(token.state.error).toBe("Nope.")
    expect(requestJsonMock).toHaveBeenCalledTimes(1)
  })

  it("does not fire a second create while one is in flight", async () => {
    const deferred = defer<{ ok: boolean }>()
    requestJsonMock.mockReturnValueOnce(deferred.promise)
    const token = useDailyExportToken()
    const first = token.createToken(42)
    const second = await token.createToken(42)
    expect(second.ok).toBe(false)
    expect(requestJsonMock).toHaveBeenCalledTimes(1)
    deferred.resolve({ ok: true, data: { token: "dfx_x", created_at: "now" } })
    await first
  })
})

describe("useDailyExportToken revocation", () => {
  beforeEach(() => requestJsonMock.mockReset())

  it("revoke clears the raw token and active status", async () => {
    requestJsonMock
      .mockResolvedValueOnce({
        ok: true,
        data: { token: "dfx_abc", created_at: "2026-08-29T09:00:00+00:00" },
      })
      .mockResolvedValueOnce({ ok: true })
    const token = useDailyExportToken()
    await token.createToken(42)
    expect(token.state.rawToken).toBe("dfx_abc")

    const result = await token.revokeToken(42)
    expect(result.ok).toBe(true)
    expect(token.state.rawToken).toBeNull()
    expect(token.state.hasToken).toBe(false)
    expect(token.state.createdAt).toBeNull()
  })

  it("revoke is idempotent on failure-free absence (204 either way)", async () => {
    requestJsonMock.mockResolvedValueOnce({ ok: true })
    const token = useDailyExportToken()
    const result = await token.revokeToken(42)
    expect(result.ok).toBe(true)
  })

  it("dismissRawToken clears only the raw value", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      data: { token: "dfx_abc", created_at: "now" },
    })
    const token = useDailyExportToken()
    await token.createToken(42)
    token.dismissRawToken()
    expect(token.state.rawToken).toBeNull()
    expect(token.state.hasToken).toBe(true)
  })
})

describe("useDailyExportToken generation gating and disposal", () => {
  beforeEach(() => requestJsonMock.mockReset())

  it("a stale status read resolving after a create commit does not overwrite it", async () => {
    const readDeferred = defer<{ ok: boolean; data?: object }>()
    const createDeferred = defer<{ ok: boolean; data?: object }>()
    requestJsonMock
      .mockReturnValueOnce(readDeferred.promise)
      .mockReturnValueOnce(createDeferred.promise)

    const token = useDailyExportToken()
    const readPromise = token.fetchStatus()
    const createPromise = token.createToken(42)

    createDeferred.resolve({ ok: true, data: { token: "dfx_new", created_at: "now" } })
    await createPromise
    readDeferred.resolve({ ok: true, data: { has_token: false, created_at: null } })
    await readPromise

    expect(token.state.rawToken).toBe("dfx_new")
    expect(token.state.hasToken).toBe(true)
  })

  it("dispose() clears the raw token and drops any still-pending response", async () => {
    const deferred = defer<{ ok: boolean; data?: object }>()
    requestJsonMock.mockReturnValueOnce(deferred.promise)

    const token = useDailyExportToken()
    const createPromise = token.createToken(42)
    token.dispose()
    deferred.resolve({ ok: true, data: { token: "dfx_late", created_at: "now" } })
    await createPromise

    expect(token.state.rawToken).toBeNull()
  })

  it("dispose() immediately clears an already-revealed raw token", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      data: { token: "dfx_abc", created_at: "now" },
    })
    const token = useDailyExportToken()
    await token.createToken(42)
    expect(token.state.rawToken).toBe("dfx_abc")
    token.dispose()
    expect(token.state.rawToken).toBeNull()
  })
})
