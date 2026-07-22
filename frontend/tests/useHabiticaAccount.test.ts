// useHabiticaAccount — serialisation lock and read/write race guards.
//
// The composable coordinates three async operations against one account row,
// so its correctness rests on machinery that is invisible in the happy path:
//
//   - a UI-level lock (`accountOperationInFlight`) that serialises writes and
//     bounces reads, released in `finally` so a dropped response cannot wedge
//     the UI permanently;
//   - split commit tokens — writes share `latestAccountWriteSeq`, reads have
//     their own `statusReadSeq`;
//   - `writeCompletionTick`, which lets a read detect that a write committed
//     while the read was in flight. The read's payload is pre-write and
//     therefore staler than what the write already stored, so it must be
//     discarded rather than committed on top.
//
// All of these only manifest under interleaving, which is why every test here
// holds a request open with `defer()` instead of letting it resolve.

import { beforeEach, describe, expect, it, vi } from "vitest"

type Deferred<T> = {
  promise: Promise<T>
  resolve: (v: T) => void
}

function defer<T>(): Deferred<T> {
  let resolve!: (v: T) => void
  const promise = new Promise<T>((res) => {
    resolve = res
  })
  return { promise, resolve }
}

const requestJson = vi.fn()

vi.mock("../src/composables/useHttp", () => ({
  requestJson: (...args: unknown[]) => requestJson(...args),
}))

import { useHabiticaAccount } from "../src/composables/useHabiticaAccount"

const CREDS = { api_user_id: "user-id", api_token: "token" }
const CONNECTED = { connected: true, last_verified_at: null, api_user_id: "u" }

beforeEach(() => {
  requestJson.mockReset()
})

describe("useHabiticaAccount serialisation lock", () => {
  it("rejects a second connect while one is in flight, without a network call", async () => {
    const first = defer<unknown>()
    requestJson.mockReturnValueOnce(first.promise)

    const api = useHabiticaAccount()
    const inFlight = api.connect(CREDS)

    const rejected = await api.connect(CREDS)
    expect(rejected.ok).toBe(false)
    expect(rejected.errors?.detail).toContain("in progress")
    // The decisive assertion: the lock short-circuits BEFORE the request,
    // so a double-submit cannot reach the provider twice.
    expect(requestJson).toHaveBeenCalledTimes(1)

    first.resolve({ ok: true, status: 200, data: CONNECTED })
    await inFlight
  })

  it("bounces fetchAccountStatus while a write is in flight", async () => {
    const write = defer<unknown>()
    requestJson.mockReturnValueOnce(write.promise)

    const api = useHabiticaAccount()
    const inFlight = api.connect(CREDS)

    await api.fetchAccountStatus()
    expect(requestJson).toHaveBeenCalledTimes(1)

    write.resolve({ ok: true, status: 200, data: CONNECTED })
    await inFlight
  })

  it("releases the lock even when the commit guard drops the response", async () => {
    // Supersede the first write mid-flight so its `seq` check fails. The
    // early return happens inside `try`, so only the `finally` clears the
    // lock — without it the UI would be frozen for the rest of the session.
    const first = defer<unknown>()
    const second = defer<unknown>()
    requestJson.mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise)

    const api = useHabiticaAccount()
    const firstCall = api.connect(CREDS)

    // Force a newer write seq while the first is still open.
    api._internals.accountOperationInFlight.value = null
    const secondCall = api.connect(CREDS)

    first.resolve({ ok: true, status: 200, data: CONNECTED })
    await firstCall
    second.resolve({ ok: true, status: 200, data: CONNECTED })
    await secondCall

    expect(api._internals.accountOperationInFlight.value).toBeNull()

    // And the lock is genuinely usable again, not merely null-looking.
    requestJson.mockResolvedValueOnce({ ok: true, status: 200, data: CONNECTED })
    const after = await api.connect(CREDS)
    expect(after.ok).toBe(true)
  })

  it("releases the lock after a failed write", async () => {
    requestJson.mockResolvedValueOnce({ ok: false, status: 400, errors: {} })
    const api = useHabiticaAccount()

    await api.connect(CREDS)

    expect(api._internals.accountOperationInFlight.value).toBeNull()
    expect(api.state.loading).toBe(false)
  })
})

describe("useHabiticaAccount read/write ordering", () => {
  it("drops a status read that a write outran", async () => {
    // Read starts first, write commits while the read is still open. The
    // read's payload predates the write, so committing it would roll the UI
    // back to a stale connected state.
    const read = defer<unknown>()
    requestJson.mockReturnValueOnce(read.promise)

    const api = useHabiticaAccount()
    const readInFlight = api.fetchAccountStatus()

    // Simulate a write completing mid-read.
    api._internals.writeCompletionTick.value++

    read.resolve({
      ok: true,
      status: 200,
      data: { connected: false, last_verified_at: null, api_user_id: "" },
    })
    await readInFlight

    expect(api.state.status).toBeNull()
  })

  it("commits a status read when no write intervened", async () => {
    requestJson.mockResolvedValueOnce({ ok: true, status: 200, data: CONNECTED })
    const api = useHabiticaAccount()

    await api.fetchAccountStatus()

    expect(api.state.status).toEqual(CONNECTED)
  })
})

describe("useHabiticaAccount disconnect", () => {
  it("clears connected status and releases the lock on success", async () => {
    requestJson.mockResolvedValueOnce({ ok: true, status: 200, data: CONNECTED })
    const api = useHabiticaAccount()
    await api.connect(CREDS)
    expect(api.state.status?.connected).toBe(true)

    requestJson.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { connected: false, last_verified_at: null, api_user_id: "" },
    })
    const result = await api.disconnect()

    expect(result.ok).toBe(true)
    expect(api.state.status?.connected).toBe(false)
    expect(api._internals.accountOperationInFlight.value).toBeNull()
  })

  it("rejects disconnect while a connect is in flight", async () => {
    const write = defer<unknown>()
    requestJson.mockReturnValueOnce(write.promise)

    const api = useHabiticaAccount()
    const inFlight = api.connect(CREDS)

    const rejected = await api.disconnect()
    expect(rejected.ok).toBe(false)
    expect(requestJson).toHaveBeenCalledTimes(1)

    write.resolve({ ok: true, status: 200, data: CONNECTED })
    await inFlight
  })
})
