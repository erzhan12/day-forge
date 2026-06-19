// Tests for useTodoistAccount.ts — serialisation lock, lock release on
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

import { useTodoistAccount } from "../src/composables/useTodoistAccount"

const STATUS_CONNECTED = {
  connected: true,
  last_verified_at: "2026-05-07T09:00:00+00:00",
}

const STATUS_DISCONNECTED = {
  connected: false,
  last_verified_at: null,
}

describe("useTodoistAccount serialisation lock", () => {
  beforeEach(() => {
    requestJsonMock.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("disconnect during connect is rejected without a network call", async () => {
    const connectDeferred = defer<{ ok: boolean; data?: object }>()
    requestJsonMock.mockReturnValueOnce(connectDeferred.promise)

    const account = useTodoistAccount()
    const connectPromise = account.connect({ token: "secret-token" })

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

    const account = useTodoistAccount()
    await account.connect({ token: "good-token" })
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

    const account = useTodoistAccount()
    await account.connect({ token: "wrong-token" })
    expect(account._internals.accountOperationInFlight.value).toBeNull()

    const disconnectResult = await account.disconnect()
    expect(disconnectResult.ok).toBe(true)
  })

  it("lock released after AbortError; disconnect then accepted", async () => {
    const aborted = new DOMException("aborted", "AbortError")
    requestJsonMock
      .mockImplementationOnce(() => Promise.reject(aborted))
      .mockResolvedValueOnce({ ok: true, data: STATUS_DISCONNECTED })

    const account = useTodoistAccount()
    await account.connect({ token: "some-token" })
    expect(account._internals.accountOperationInFlight.value).toBeNull()

    const disconnectResult = await account.disconnect()
    expect(disconnectResult.ok).toBe(true)
  })

  it("status read is rejected without network call while a mutation is in flight", async () => {
    const connectDeferred = defer<{ ok: boolean; data?: object }>()
    requestJsonMock.mockReturnValueOnce(connectDeferred.promise)

    const account = useTodoistAccount()
    const connectPromise = account.connect({ token: "some-token" })

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
    const account = useTodoistAccount()
    await account.fetchAccountStatus()
    expect(account.state.status?.connected).toBe(false)
  })
})

describe("useTodoistAccount commit tokens", () => {
  beforeEach(() => {
    requestJsonMock.mockReset()
  })

  it("two connects resolving in reverse order: only the latest commits", async () => {
    const c1 = defer<{ ok: boolean; data?: object }>()
    const c2 = defer<{ ok: boolean; data?: object }>()
    requestJsonMock.mockReturnValueOnce(c1.promise).mockReturnValueOnce(c2.promise)

    const account = useTodoistAccount()
    // Lock-bypass by directly invoking connect twice; the test simulates
    // the (otherwise impossible) lock-leak case via a manual null between
    // the two calls.
    const p1 = account.connect({ token: "first-token" })
    account._internals.accountOperationInFlight.value = null
    const p2 = account.connect({ token: "second-token" })

    c2.resolve({
      ok: true,
      data: { ...STATUS_CONNECTED, last_verified_at: "2026-05-08T09:00:00+00:00" },
    })
    c1.resolve({
      ok: true,
      data: { ...STATUS_CONNECTED, last_verified_at: "2026-05-07T09:00:00+00:00" },
    })

    await p2
    await p1

    expect(account.state.status?.last_verified_at).toBe("2026-05-08T09:00:00+00:00")
  })

  it("late read after committed write is dropped by writeCompletionTick", async () => {
    const readDeferred = defer<{ ok: boolean; data?: object }>()
    const writeDeferred = defer<{ ok: boolean; data?: object }>()

    requestJsonMock
      .mockReturnValueOnce(readDeferred.promise)
      .mockReturnValueOnce(writeDeferred.promise)

    const account = useTodoistAccount()
    const readPromise = account.fetchAccountStatus()
    const writePromise = account.connect({ token: "after-write-token" })

    // Resolve the WRITE first — it commits and bumps writeCompletionTick.
    writeDeferred.resolve({
      ok: true,
      data: { ...STATUS_CONNECTED, last_verified_at: "2026-05-09T09:00:00+00:00" },
    })
    await writePromise

    // Now resolve the STALE pre-write read. The tick guard must drop it.
    readDeferred.resolve({
      ok: true,
      data: STATUS_DISCONNECTED,
    })
    await readPromise

    expect(account.state.status?.last_verified_at).toBe("2026-05-09T09:00:00+00:00")
    expect(account.state.status?.connected).toBe(true)
  })
})
