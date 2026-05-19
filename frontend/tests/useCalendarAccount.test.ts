// Tests for useCalendarAccount.ts — serialisation lock, lock release on
// success / failure / abort, commit-token belt-and-suspenders, read
// cannot supersede a write, late read dropped by writeCompletionTick.

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

import { useCalendarAccount } from "../src/composables/useCalendarAccount"

const STATUS_CONNECTED = {
  connected: true,
  apple_id: "alice@example.com",
  base_url: "https://caldav.icloud.com/",
  last_verified_at: "2026-05-07T09:00:00+00:00",
  default_base_url: "https://caldav.icloud.com/",
}

const STATUS_DISCONNECTED = {
  connected: false,
  apple_id: null,
  base_url: null,
  last_verified_at: null,
  default_base_url: "https://caldav.icloud.com/",
}

describe("useCalendarAccount serialisation lock", () => {
  beforeEach(() => {
    requestJsonMock.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("disconnect during connect is rejected without a network call", async () => {
    const connectDeferred = defer<{ ok: boolean; data?: object }>()
    requestJsonMock.mockReturnValueOnce(connectDeferred.promise)

    const account = useCalendarAccount()
    const connectPromise = account.connect({
      apple_id: "alice@example.com",
      password: "secret",
    })

    // Lock is set to "connect" while the first request is pending.
    expect(account._internals.accountOperationInFlight.value).toBe("connect")

    const disconnectResult = await account.disconnect()
    expect(disconnectResult.ok).toBe(false)
    expect(disconnectResult.errors?.detail).toMatch(/in progress/i)
    // Mock was only called once — the lock blocked disconnect from making a network call.
    expect(requestJsonMock).toHaveBeenCalledTimes(1)

    connectDeferred.resolve({ ok: true, data: STATUS_CONNECTED })
    await connectPromise
    expect(account._internals.accountOperationInFlight.value).toBeNull()
  })

  it("lock released after successful connect; disconnect then accepted", async () => {
    requestJsonMock
      .mockResolvedValueOnce({ ok: true, data: STATUS_CONNECTED })
      .mockResolvedValueOnce({ ok: true, data: STATUS_DISCONNECTED })

    const account = useCalendarAccount()
    await account.connect({ apple_id: "a@b.com", password: "x" })
    expect(account._internals.accountOperationInFlight.value).toBeNull()

    const disconnectResult = await account.disconnect()
    expect(disconnectResult.ok).toBe(true)
    expect(requestJsonMock).toHaveBeenCalledTimes(2)
  })

  it("lock released after failed connect; disconnect then accepted (regression-catches lock-leak)", async () => {
    requestJsonMock
      .mockResolvedValueOnce({
        ok: false,
        status: 401,
        errors: { detail: "Invalid credentials" },
      })
      .mockResolvedValueOnce({ ok: true, data: STATUS_DISCONNECTED })

    const account = useCalendarAccount()
    await account.connect({ apple_id: "a@b.com", password: "wrong" })
    expect(account._internals.accountOperationInFlight.value).toBeNull()

    const disconnectResult = await account.disconnect()
    expect(disconnectResult.ok).toBe(true)
  })

  it("lock released after AbortError; disconnect then accepted", async () => {
    const aborted = new DOMException("aborted", "AbortError")
    requestJsonMock
      .mockImplementationOnce(() => Promise.reject(aborted))
      .mockResolvedValueOnce({ ok: true, data: STATUS_DISCONNECTED })

    const account = useCalendarAccount()
    await account.connect({ apple_id: "a@b.com", password: "x" })
    expect(account._internals.accountOperationInFlight.value).toBeNull()

    const disconnectResult = await account.disconnect()
    expect(disconnectResult.ok).toBe(true)
  })

  it("status read is rejected without network call while a mutation is in flight", async () => {
    const connectDeferred = defer<{ ok: boolean; data?: object }>()
    requestJsonMock.mockReturnValueOnce(connectDeferred.promise)

    const account = useCalendarAccount()
    const connectPromise = account.connect({
      apple_id: "a@b.com",
      password: "x",
    })

    await account.fetchAccountStatus()
    // Only the connect call hit the mock.
    expect(requestJsonMock).toHaveBeenCalledTimes(1)

    connectDeferred.resolve({ ok: true, data: STATUS_CONNECTED })
    await connectPromise
  })

  it("fetchAccountStatus works on the happy path (no mutation in flight)", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      data: STATUS_DISCONNECTED,
    })
    const account = useCalendarAccount()
    await account.fetchAccountStatus()
    expect(account.state.status?.connected).toBe(false)
  })
})

describe("useCalendarAccount commit tokens", () => {
  beforeEach(() => {
    requestJsonMock.mockReset()
  })

  it("two connects resolving in reverse order: only the latest commits", async () => {
    const c1 = defer<{ ok: boolean; data?: object }>()
    const c2 = defer<{ ok: boolean; data?: object }>()
    requestJsonMock.mockReturnValueOnce(c1.promise).mockReturnValueOnce(c2.promise)

    const account = useCalendarAccount()
    // Lock-bypass by directly invoking connect twice; the test simulates
    // the (otherwise impossible) lock-leak case via a manual null between
    // the two calls.
    const p1 = account.connect({ apple_id: "first@b.com", password: "x" })
    account._internals.accountOperationInFlight.value = null
    const p2 = account.connect({ apple_id: "second@b.com", password: "x" })

    c2.resolve({
      ok: true,
      data: { ...STATUS_CONNECTED, apple_id: "second@b.com" },
    })
    c1.resolve({
      ok: true,
      data: { ...STATUS_CONNECTED, apple_id: "first@b.com" },
    })

    await p2
    await p1

    expect(account.state.status?.apple_id).toBe("second@b.com")
  })

  it("late read after committed write is dropped by writeCompletionTick", async () => {
    const readDeferred = defer<{ ok: boolean; data?: object }>()
    const writeDeferred = defer<{ ok: boolean; data?: object }>()

    requestJsonMock
      .mockReturnValueOnce(readDeferred.promise)
      .mockReturnValueOnce(writeDeferred.promise)

    const account = useCalendarAccount()
    const readPromise = account.fetchAccountStatus()
    const writePromise = account.connect({
      apple_id: "after-write@b.com",
      password: "x",
    })

    // Resolve the WRITE first — it commits and bumps writeCompletionTick.
    writeDeferred.resolve({
      ok: true,
      data: { ...STATUS_CONNECTED, apple_id: "after-write@b.com" },
    })
    await writePromise

    // Now resolve the STALE pre-write read. The tick guard must drop it.
    readDeferred.resolve({
      ok: true,
      data: STATUS_DISCONNECTED,
    })
    await readPromise

    expect(account.state.status?.apple_id).toBe("after-write@b.com")
    expect(account.state.status?.connected).toBe(true)
  })
})
