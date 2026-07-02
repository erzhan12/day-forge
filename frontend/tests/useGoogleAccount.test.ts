// Tests for useGoogleAccount.ts (feature 0022) — list + multi-row disconnect,
// disconnect adopts the refreshed list, and the serialisation lock.

import { beforeEach, describe, expect, it, vi } from "vitest"

const requestJsonMock = vi.fn()

vi.mock("../src/composables/useHttp", () => ({
  requestJson: (...args: unknown[]) => requestJsonMock(...args),
}))

import { useGoogleAccount } from "../src/composables/useGoogleAccount"

describe("useGoogleAccount", () => {
  beforeEach(() => requestJsonMock.mockReset())

  it("fetchAccounts populates the account list", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: {
        accounts: [
          { id: 1, email: "a@gmail.com", last_verified_at: null },
          { id: 2, email: "b@gmail.com", last_verified_at: "2026-05-01T00:00:00Z" },
        ],
      },
    })
    const acc = useGoogleAccount()
    await acc.fetchAccounts()
    expect(acc.state.accounts.map((a) => a.email)).toEqual([
      "a@gmail.com",
      "b@gmail.com",
    ])
  })

  it("disconnect adopts the refreshed list returned by the DELETE", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { accounts: [{ id: 2, email: "b@gmail.com", last_verified_at: null }] },
    })
    const acc = useGoogleAccount()
    const result = await acc.disconnect(1)
    expect(result.ok).toBe(true)
    expect(acc.state.accounts.map((a) => a.id)).toEqual([2])
  })

  it("a disconnect in flight blocks a concurrent fetchAccounts (serialisation lock)", async () => {
    let resolveDelete!: (v: unknown) => void
    requestJsonMock.mockReturnValueOnce(
      new Promise((res) => {
        resolveDelete = res
      }),
    )
    const acc = useGoogleAccount()
    const p = acc.disconnect(1)
    // While the disconnect is mid-flight, a read must bounce off the lock and
    // not issue a second request.
    await acc.fetchAccounts()
    expect(requestJsonMock).toHaveBeenCalledTimes(1)
    resolveDelete({ ok: true, status: 200, data: { accounts: [] } })
    await p
  })

  it("connect() performs a full-page redirect to the OAuth start", () => {
    const acc = useGoogleAccount()
    const orig = window.location
    // jsdom location is read-only; redefine href setter for the assertion.
    const hrefSet = vi.fn()
    Object.defineProperty(window, "location", {
      configurable: true,
      value: { ...orig, set href(v: string) { hrefSet(v) } },
    })
    acc.connect()
    expect(hrefSet).toHaveBeenCalledWith("/api/calendar/google/connect/")
    Object.defineProperty(window, "location", { configurable: true, value: orig })
  })
})
