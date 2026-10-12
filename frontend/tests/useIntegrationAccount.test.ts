import { effectScope, reactive } from "vue"
import { beforeEach, describe, expect, it, vi } from "vitest"
import type { ApiResult } from "../src/composables/useHttp"

const requestJsonMock = vi.fn()
vi.mock("../src/composables/useHttp", () => ({
  requestJson: (...args: unknown[]) => requestJsonMock(...args),
}))

import { useIntegrationAccount } from "../src/composables/useIntegrationAccount"
import { useCalendarAccount } from "../src/composables/useCalendarAccount"
import { useGoogleAccount } from "../src/composables/useGoogleAccount"

function deferred<T>() {
  let resolve!: (value: T) => void
  const promise = new Promise<T>((done) => { resolve = done })
  return { promise, resolve }
}

beforeEach(() => requestJsonMock.mockReset())

describe("shared account request lifecycle", () => {
  it("keeps a disconnect result when an older status request ignores abort", async () => {
    const oldRead = deferred<ApiResult>()
    requestJsonMock
      .mockReturnValueOnce(oldRead.promise)
      .mockResolvedValueOnce({ ok: true, data: { connected: false } })

    const account = useCalendarAccount()
    const read = account.fetchAccountStatus()
    const readSignal = requestJsonMock.mock.calls[0][3].signal as AbortSignal
    const result = await account.disconnect()
    expect(result.ok).toBe(true)
    expect(readSignal.aborted).toBe(true)

    oldRead.resolve({ ok: true, data: { connected: true } })
    await read
    expect(account.state.status?.connected).toBe(false)
    expect(account.state.error).toBeNull()
  })

  it("aborts an active write on scope disposal and ignores its late success", async () => {
    const lateWrite = deferred<ApiResult>()
    requestJsonMock.mockReturnValueOnce(lateWrite.promise)
    const scope = effectScope()
    const account = scope.run(() => useCalendarAccount())!
    const write = account.connect({ apple_id: "a@example.com", password: "secret" })
    const signal = requestJsonMock.mock.calls[0][3].signal as AbortSignal
    expect(account.state.loading).toBe(true)

    scope.stop()
    expect(signal.aborted).toBe(true)
    expect(account.state.loading).toBe(false)
    expect(account._internals.accountOperationInFlight.value).toBeNull()

    lateWrite.resolve({ ok: true, data: { connected: true } })
    expect((await write).ok).toBe(false)
    expect(account.state.status).toBeNull()
    expect(account.state.error).toBeNull()
    expect((await account.disconnect()).ok).toBe(false)
    expect(requestJsonMock).toHaveBeenCalledTimes(1)
  })

  it("disposes an active Google list read without committing late accounts", async () => {
    const lateRead = deferred<ApiResult>()
    requestJsonMock.mockReturnValueOnce(lateRead.promise)
    const scope = effectScope()
    const account = scope.run(() => useGoogleAccount())!
    const read = account.fetchAccounts()
    const signal = requestJsonMock.mock.calls[0][3].signal as AbortSignal

    scope.stop()
    expect(signal.aborted).toBe(true)
    lateRead.resolve({ ok: true, data: { accounts: [{ id: 1, email: "a@gmail.com" }] } })
    await read
    expect(account.state.accounts).toEqual([])
  })

  it("clears loading and lock on AbortError without setting an error", async () => {
    requestJsonMock.mockRejectedValueOnce(new DOMException("aborted", "AbortError"))
    const state = reactive({ value: null as string | null, loading: false, error: null as string | null })
    const account = useIntegrationAccount({
      state,
      readUrl: "/api/test/account/",
      accept: (data) => { state.value = data?.value as string },
      lockMessage: "Busy",
    })

    const result = await account.write("disconnect", "/api/test/account/", "DELETE")
    expect(result).toEqual({ ok: false, errors: { detail: "Cancelled" } })
    expect(state).toMatchObject({ value: null, loading: false, error: null })
    expect(account.operationInFlight.value).toBeNull()
  })
})
