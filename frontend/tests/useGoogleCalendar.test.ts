// Tests for useGoogleCalendar.ts (feature 0022) — composite events payload
// (events + account_errors), 503 status mapping, and the dual commit-token
// stale-response guard.

import { beforeEach, describe, expect, it, vi } from "vitest"

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

import { useGoogleCalendar } from "../src/composables/useGoogleCalendar"

function eventPayload(uid: string, title: string) {
  return {
    title,
    start: "2026-05-07T14:00:00+00:00",
    end: "2026-05-07T15:00:00+00:00",
    calendar_name: "Team",
    all_day: false,
    external_uid: uid,
    account_label: "alice@gmail.com",
  }
}

describe("useGoogleCalendar.fetchEvents", () => {
  beforeEach(() => requestJsonMock.mockReset())

  it("happy path sets events and accountErrors", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: {
        events: [eventPayload("g1@google", "Standup")],
        account_errors: [
          { account_id: 2, email: "bad@gmail.com", error: "reconnect_required" },
        ],
      },
    })
    const cal = useGoogleCalendar()
    await cal.fetchEvents("2026-05-07")
    expect(cal.state.events).toHaveLength(1)
    expect(cal.state.connected).toBe(true)
    expect(cal.state.accountErrors).toHaveLength(1)
    expect(cal.state.accountErrors[0].error).toBe("reconnect_required")
    expect(cal.state.error).toBeNull()
  })

  it("defaults account_errors to [] when absent", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { events: [] },
    })
    const cal = useGoogleCalendar()
    await cal.fetchEvents("2026-05-07")
    expect(cal.state.accountErrors).toEqual([])
  })

  it("503 flips connected=false without an error message", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 503,
      errors: { detail: "No Google Calendar account configured" },
    })
    const cal = useGoogleCalendar()
    await cal.fetchEvents("2026-05-07")
    expect(cal.state.connected).toBe(false)
    expect(cal.state.error).toBeNull()
    expect(cal.state.events).toEqual([])
    expect(cal.state.accountErrors).toEqual([])
  })

  it("401 sets an authorization-expired error (whole-request failure)", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      errors: { detail: "Google authorization failed" },
    })
    const cal = useGoogleCalendar()
    await cal.fetchEvents("2026-05-07")
    expect(cal.state.error).toMatch(/authorization expired/i)
  })

  it("502/504 surface a generic unavailable message", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 504,
      errors: { detail: "timed out" },
    })
    const cal = useGoogleCalendar()
    await cal.fetchEvents("2026-05-07")
    expect(cal.state.error).toMatch(/unavailable/i)
  })

  it("clears stale events and accountErrors on a whole-request failure", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: {
        events: [eventPayload("g1@google", "Standup")],
        account_errors: [
          { account_id: 2, email: "x@gmail.com", error: "reconnect_required" },
        ],
      },
    })
    const cal = useGoogleCalendar()
    await cal.fetchEvents("2026-05-07")
    expect(cal.state.events).toHaveLength(1)
    expect(cal.state.accountErrors).toHaveLength(1)

    // A later whole-request failure must clear both so the non-suppressing
    // panel doesn't render stale events beside the new error banner.
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 502,
      errors: { detail: "down" },
    })
    await cal.fetchEvents("2026-05-08")
    expect(cal.state.events).toEqual([])
    expect(cal.state.accountErrors).toEqual([])
    expect(cal.state.error).toMatch(/unavailable/i)
  })

  it("drops a stale interleaved fetch (commits the most recent date)", async () => {
    const d1 = defer<{ ok: boolean; data?: object; status?: number }>()
    const d2 = defer<{ ok: boolean; data?: object; status?: number }>()
    requestJsonMock.mockReturnValueOnce(d1.promise).mockReturnValueOnce(d2.promise)

    const cal = useGoogleCalendar()
    const p1 = cal.fetchEvents("2026-05-01")
    const p2 = cal.fetchEvents("2026-05-02")
    d2.resolve({ ok: true, status: 200, data: { events: [eventPayload("d2", "Day 2")] } })
    d1.resolve({ ok: true, status: 200, data: { events: [eventPayload("d1", "Day 1")] } })
    await p2
    await p1

    expect(cal.state.events).toHaveLength(1)
    expect(cal.state.events[0].title).toBe("Day 2")
  })
})

describe("useGoogleCalendar.fetchAccountStatus", () => {
  beforeEach(() => requestJsonMock.mockReset())

  it("seeds connected from a non-empty account list", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { accounts: [{ id: 1, email: "a@gmail.com", last_verified_at: null }] },
    })
    const cal = useGoogleCalendar()
    await cal.fetchAccountStatus()
    expect(cal.state.connected).toBe(true)
    expect(cal.state.statusKnown).toBe(true)
  })

  it("leaves connected=false for an empty account list", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { accounts: [] },
    })
    const cal = useGoogleCalendar()
    await cal.fetchAccountStatus()
    expect(cal.state.connected).toBe(false)
  })
})
