// Tests for useCalendar.ts — events fetch, stale-response guards
// (cross-date and same-date), status-fetch independence, AbortError swallow.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { nextTick } from "vue"

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

import { useCalendar } from "../src/composables/useCalendar"

function eventPayload(uid: string, title: string) {
  return {
    title,
    start: "2026-05-07T14:00:00+00:00",
    end: "2026-05-07T15:00:00+00:00",
    calendar_name: "Personal",
    all_day: false,
    external_uid: uid,
    account_label: "", // Apple emits the empty sentinel (feature 0022)
  }
}

describe("useCalendar.fetchEvents", () => {
  beforeEach(() => {
    requestJsonMock.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("commits the most recent fetch (cross-date race)", async () => {
    const d1 = defer<{ ok: boolean; data?: object; status?: number }>()
    const d2 = defer<{ ok: boolean; data?: object; status?: number }>()
    requestJsonMock
      .mockReturnValueOnce(d1.promise)
      .mockReturnValueOnce(d2.promise)

    const calendar = useCalendar()
    const p1 = calendar.fetchEvents("2026-05-01")
    const p2 = calendar.fetchEvents("2026-05-02")

    d2.resolve({
      ok: true,
      status: 200,
      data: { events: [eventPayload("d2", "Day 2")] },
    })
    d1.resolve({
      ok: true,
      status: 200,
      data: { events: [eventPayload("d1", "Day 1")] },
    })

    await p2
    await p1

    expect(calendar.state.events).toHaveLength(1)
    expect(calendar.state.events[0].title).toBe("Day 2")
  })

  it("commits the most recent fetch (same-date race)", async () => {
    const d1 = defer<{ ok: boolean; data?: object; status?: number }>()
    const d2 = defer<{ ok: boolean; data?: object; status?: number }>()
    requestJsonMock
      .mockReturnValueOnce(d1.promise)
      .mockReturnValueOnce(d2.promise)

    const calendar = useCalendar()
    const p1 = calendar.fetchEvents("2026-05-07")
    const p2 = calendar.fetchEvents("2026-05-07")

    d2.resolve({
      ok: true,
      status: 200,
      data: { events: [eventPayload("second", "Second")] },
    })
    d1.resolve({
      ok: true,
      status: 200,
      data: { events: [eventPayload("first", "First")] },
    })

    await p2
    await p1

    expect(calendar.state.events).toHaveLength(1)
    expect(calendar.state.events[0].title).toBe("Second")
  })

  it("503 flips connected=false without an error message", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 503,
      errors: { detail: "No CalDAV account configured" },
    })
    const calendar = useCalendar()
    await calendar.fetchEvents("2026-05-07")
    expect(calendar.state.connected).toBe(false)
    expect(calendar.state.error).toBeNull()
    expect(calendar.state.events).toEqual([])
  })

  it("401 sets a credentials error", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      errors: { detail: "Invalid Apple Calendar credentials" },
    })
    const calendar = useCalendar()
    await calendar.fetchEvents("2026-05-07")
    expect(calendar.state.error).toMatch(/credentials invalid/i)
  })

  it("502 / 504 surface a generic unavailable message", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 504,
      errors: { detail: "timed out" },
    })
    const calendar = useCalendar()
    await calendar.fetchEvents("2026-05-07")
    expect(calendar.state.error).toMatch(/unavailable/i)
  })

  it("AbortError from a superseded request does not leak into state.error", async () => {
    const aborted = new DOMException("aborted", "AbortError")
    requestJsonMock
      .mockImplementationOnce(() => Promise.reject(aborted))
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: { events: [eventPayload("ok", "OK")] },
      })

    const calendar = useCalendar()
    const p1 = calendar.fetchEvents("2026-05-07")
    const p2 = calendar.fetchEvents("2026-05-08")
    await p1
    await p2

    expect(calendar.state.error).toBeNull()
    expect(calendar.state.events[0].title).toBe("OK")
  })
})

describe("useCalendar.refreshEvents", () => {
  beforeEach(() => {
    requestJsonMock.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("appends refresh=1 to the events URL", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { events: [] },
    })
    const calendar = useCalendar()
    await calendar.refreshEvents("2026-05-07")

    expect(requestJsonMock.mock.calls[0][0]).toBe(
      "/api/calendar/events/2026-05-07/?refresh=1",
    )
  })

  it("stays silent: loading never flips true and events stay populated until the atomic commit", async () => {
    const dRefresh = defer<{ ok: boolean; data?: object; status?: number }>()
    requestJsonMock.mockReturnValueOnce(dRefresh.promise)
    const calendar = useCalendar()
    calendar.state.events = [eventPayload("A", "A"), eventPayload("B", "B")]
    calendar.state.connected = true
    calendar.state.statusKnown = true

    const p = calendar.refreshEvents("2026-05-07")
    expect(calendar.state.loading).toBe(false)
    expect(calendar.state.events).toHaveLength(2)

    dRefresh.resolve({
      ok: true,
      status: 200,
      data: { events: [eventPayload("C", "C")] },
    })
    await p

    expect(calendar.state.loading).toBe(false)
    expect(calendar.state.events.map((e) => e.external_uid)).toEqual(["C"])
  })

  it("shares the dual commit guard with fetchEvents (a superseded refresh is dropped)", async () => {
    const d1 = defer<{ ok: boolean; data?: object; status?: number }>()
    const d2 = defer<{ ok: boolean; data?: object; status?: number }>()
    requestJsonMock
      .mockReturnValueOnce(d1.promise)
      .mockReturnValueOnce(d2.promise)

    const calendar = useCalendar()
    const p1 = calendar.refreshEvents("2026-05-01")
    const p2 = calendar.fetchEvents("2026-05-02")

    d2.resolve({
      ok: true,
      status: 200,
      data: { events: [eventPayload("d2", "Day 2")] },
    })
    d1.resolve({
      ok: true,
      status: 200,
      data: { events: [eventPayload("d1", "Day 1")] },
    })

    await p2
    await p1

    expect(calendar.state.events).toHaveLength(1)
    expect(calendar.state.events[0].title).toBe("Day 2")
  })

  it("aborts an in-flight fetchEvents when refreshEvents supersedes it", async () => {
    const d1 = defer<{ ok: boolean; data?: object; status?: number }>()
    const d2 = defer<{ ok: boolean; data?: object; status?: number }>()
    requestJsonMock
      .mockReturnValueOnce(d1.promise)
      .mockReturnValueOnce(d2.promise)

    const calendar = useCalendar()
    const p1 = calendar.fetchEvents("2026-05-07")
    const firstSignal = requestJsonMock.mock.calls[0][3]?.signal as AbortSignal
    expect(firstSignal.aborted).toBe(false)

    const p2 = calendar.refreshEvents("2026-05-07")
    expect(firstSignal.aborted).toBe(true)

    // Prior request rejects with AbortError — must not touch state.
    d1.reject(new DOMException("aborted", "AbortError"))
    d2.resolve({
      ok: true,
      status: 200,
      data: { events: [eventPayload("fresh", "Fresh")] },
    })
    await p1
    await p2

    expect(calendar.state.error).toBeNull()
    expect(calendar.state.events[0].title).toBe("Fresh")
  })

  it("silent refresh on a non-503 error leaves last-good events untouched", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { events: [eventPayload("keep", "Keep")] },
    })
    const calendar = useCalendar()
    await calendar.fetchEvents("2026-05-07")
    expect(calendar.state.events).toHaveLength(1)

    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 504,
      errors: { detail: "timed out" },
    })
    await calendar.refreshEvents("2026-05-07")

    expect(calendar.state.events).toHaveLength(1)
    expect(calendar.state.events[0].title).toBe("Keep")
    expect(calendar.state.error).toMatch(/unavailable/i)
  })

  it("silent refresh that aborts an in-flight load blanks on non-503 failure", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { events: [eventPayload("dayA", "Day A")] },
    })
    const calendar = useCalendar()
    await calendar.fetchEvents("2026-05-07")
    expect(calendar.state.events[0].title).toBe("Day A")

    const dLoad = defer<{
      ok: boolean
      data?: object
      status?: number
      errors?: object
    }>()
    const dRefresh = defer<{
      ok: boolean
      data?: object
      status?: number
      errors?: object
    }>()
    requestJsonMock
      .mockReturnValueOnce(dLoad.promise)
      .mockReturnValueOnce(dRefresh.promise)

    const pLoad = calendar.fetchEvents("2026-05-08")
    expect(calendar.state.loading).toBe(true)

    const pRefresh = calendar.refreshEvents("2026-05-08")
    dLoad.reject(new DOMException("aborted", "AbortError"))
    dRefresh.resolve({
      ok: false,
      status: 504,
      errors: { detail: "timed out" },
    })
    await pLoad
    await pRefresh

    expect(calendar.state.events).toEqual([])
    expect(calendar.state.error).toMatch(/unavailable/i)
  })
})

describe("useCalendar.fetchAccountStatus", () => {
  beforeEach(() => {
    requestJsonMock.mockReset()
  })

  it("fetchEvents and fetchAccountStatus do not cancel each other", async () => {
    const dStatus = defer<{ ok: boolean; data?: object; status?: number }>()
    const dEvents = defer<{ ok: boolean; data?: object; status?: number }>()
    requestJsonMock
      .mockReturnValueOnce(dStatus.promise)
      .mockReturnValueOnce(dEvents.promise)

    const calendar = useCalendar()
    const pStatus = calendar.fetchAccountStatus()
    const pEvents = calendar.fetchEvents("2026-05-07")

    dEvents.resolve({ ok: true, status: 200, data: { events: [] } })
    dStatus.resolve({
      ok: true,
      status: 200,
      data: {
        connected: true,
        apple_id: "a@b.com",
        base_url: "https://x/",
        last_verified_at: null,
        default_base_url: "https://x/",
      },
    })

    await pStatus
    await pEvents
    await nextTick()

    expect(calendar.state.connected).toBe(true)
    expect(calendar.state.events).toEqual([])
  })
})

// Fallback-literal guard (feature 0037): pin the exact fallback string. A
// `default`-branch status (500) makes statusToMessage return null, so
// control falls through to the shared helper; `errors: {}` yields the
// fallback. A 401/502 mock would assert statusToMessage instead and guard
// nothing here. fetchEvents + refreshEvents share the _fetchEvents code path
// (the one extractErrorMessage call), so testing fetchEvents covers both.
describe("useCalendar fallback-literal guard", () => {
  beforeEach(() => requestJsonMock.mockReset())

  it("fetchEvents surfaces the exact fallback literal on an empty errors map", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      errors: {},
    })
    const calendar = useCalendar()
    await calendar.fetchEvents("2026-05-07")
    expect(calendar.state.error).toBe("Calendar fetch failed")
  })
})
