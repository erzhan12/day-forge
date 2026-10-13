// Per-date tasks, explicit account metadata, stale-response guards, and
// optimistic completion. Ambiguous HTTP errors leave account state unchanged.

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

import { useTodoist } from "../src/composables/useTodoist"

function taskPayload(
  id: string,
  title: string,
  priority = 1,
  ui_priority = "P4",
) {
  return {
    id,
    title,
    priority,
    ui_priority,
    due_date: "2026-05-07",
  }
}

describe("useTodoist.fetchTasks", () => {
  beforeEach(() => {
    requestJsonMock.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("passes the GET body footgun args (undefined body, signal in 4th)", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { tasks: [] },
    })
    const todoist = useTodoist()
    await todoist.fetchTasks("2026-05-07")

    expect(requestJsonMock).toHaveBeenCalledTimes(1)
    const [url, method, body, opts] = requestJsonMock.mock.calls[0]
    expect(url).toBe("/api/todoist/tasks/2026-05-07/")
    expect(method).toBe("GET")
    expect(body).toBeUndefined()
    expect(opts).toMatchObject({ signal: expect.any(AbortSignal) })
  })

  it("leaves today and overdue scope to the server", async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 5, 18, 12, 0, 0))
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { tasks: [] },
    })
    const todoist = useTodoist()
    await todoist.fetchTasks("2026-06-18")

    expect(requestJsonMock.mock.calls[0][0]).toBe(
      "/api/todoist/tasks/2026-06-18/",
    )
    vi.useRealTimers()
  })

  it("commits the most recent fetch (cross-date race)", async () => {
    const d1 = defer<{ ok: boolean; data?: object; status?: number }>()
    const d2 = defer<{ ok: boolean; data?: object; status?: number }>()
    requestJsonMock
      .mockReturnValueOnce(d1.promise)
      .mockReturnValueOnce(d2.promise)

    const todoist = useTodoist()
    const p1 = todoist.fetchTasks("2026-05-01")
    const p2 = todoist.fetchTasks("2026-05-02")

    d2.resolve({
      ok: true,
      status: 200,
      data: { tasks: [taskPayload("d2", "Day 2")] },
    })
    d1.resolve({
      ok: true,
      status: 200,
      data: { tasks: [taskPayload("d1", "Day 1")] },
    })

    await p2
    await p1

    expect(todoist.state.tasks).toHaveLength(1)
    expect(todoist.state.tasks[0].title).toBe("Day 2")
    expect(todoist.state.connected).toBe(true)
    expect(todoist.state.statusKnown).toBe(true)
  })

  it("drops the stale same-date fetch (same-date / stale-seq race)", async () => {
    const d1 = defer<{ ok: boolean; data?: object; status?: number }>()
    const d2 = defer<{ ok: boolean; data?: object; status?: number }>()
    requestJsonMock
      .mockReturnValueOnce(d1.promise)
      .mockReturnValueOnce(d2.promise)

    const todoist = useTodoist()
    const p1 = todoist.fetchTasks("2026-05-07")
    const p2 = todoist.fetchTasks("2026-05-07")

    d2.resolve({
      ok: true,
      status: 200,
      data: { tasks: [taskPayload("second", "Second")] },
    })
    d1.resolve({
      ok: true,
      status: 200,
      data: { tasks: [taskPayload("first", "First")] },
    })

    await p2
    await p1

    expect(todoist.state.tasks).toHaveLength(1)
    expect(todoist.state.tasks[0].title).toBe("Second")
  })

  it("503 flips connected=false (statusKnown=true) without an error message", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 503,
      data: { meta: { account_state: "disconnected", resource_state: "unavailable" } },
      errors: { detail: "No Todoist account configured" },
    })
    const todoist = useTodoist()
    await todoist.fetchTasks("2026-05-07")
    expect(todoist.state.connected).toBe(false)
    expect(todoist.state.statusKnown).toBe(true)
    expect(todoist.state.error).toBeNull()
    expect(todoist.state.tasks).toEqual([])
  })

  it("first-load 401 sets connected=true + statusKnown=true + a credentials error", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 401,
      data: { meta: { account_state: "connected", resource_state: "credentials_error" } },
      errors: { detail: "Todoist credentials invalid" },
    })
    const todoist = useTodoist()
    // The resource response carries an explicit connected account verdict.
    await todoist.fetchTasks("2026-05-07")
    expect(todoist.state.connected).toBe(true)
    expect(todoist.state.statusKnown).toBe(true)
    expect(todoist.state.error).toMatch(/credentials invalid/i)
  })

  it("first-load 500 sets connected=true + statusKnown=true + an error", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      data: { meta: { account_state: "connected", resource_state: "provider_error" } },
      errors: {
        detail: "Todoist service is misconfigured. Contact the administrator.",
      },
    })
    const todoist = useTodoist()
    await todoist.fetchTasks("2026-05-07")
    expect(todoist.state.connected).toBe(true)
    expect(todoist.state.statusKnown).toBe(true)
    expect(todoist.state.error).toBe(
      "Todoist service is misconfigured. Contact the administrator.",
    )
  })

  it("first-load 502 sets connected=true + statusKnown=true + an unavailable message", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 502,
      data: { meta: { account_state: "connected", resource_state: "provider_error" } },
      errors: { detail: "bad gateway" },
    })
    const todoist = useTodoist()
    await todoist.fetchTasks("2026-05-07")
    expect(todoist.state.connected).toBe(true)
    expect(todoist.state.statusKnown).toBe(true)
    expect(todoist.state.error).toMatch(/unavailable/i)
  })

  it("first-load 504 sets connected=true + statusKnown=true + an unavailable message", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 504,
      data: { meta: { account_state: "connected", resource_state: "provider_error" } },
      errors: { detail: "timed out" },
    })
    const todoist = useTodoist()
    await todoist.fetchTasks("2026-05-07")
    expect(todoist.state.connected).toBe(true)
    expect(todoist.state.statusKnown).toBe(true)
    expect(todoist.state.error).toMatch(/unavailable/i)
  })

  it("first-load network failure (no status) leaves connected=false but surfaces the error", async () => {
    // A network error has no account verdict.
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      errors: { detail: "Network error. Please check your connection." },
    })
    const todoist = useTodoist()
    await todoist.fetchTasks("2026-05-07")
    expect(todoist.state.connected).toBe(false)
    expect(todoist.state.statusKnown).toBe(false)
    expect(todoist.state.error).toBe(
      "Network error. Please check your connection.",
    )
  })

  it("network failure does NOT revert an already-connected session", async () => {
    requestJsonMock
      .mockResolvedValueOnce({ ok: true, status: 200, data: { tasks: [] } })
      .mockResolvedValueOnce({
        ok: false,
        errors: { detail: "Network error. Please check your connection." },
      })
    const todoist = useTodoist()
    await todoist.fetchTasks("2026-05-07")
    expect(todoist.state.connected).toBe(true)
    await todoist.fetchTasks("2026-05-08")
    expect(todoist.state.connected).toBe(true)
    expect(todoist.state.statusKnown).toBe(true)
    expect(todoist.state.error).toBe(
      "Network error. Please check your connection.",
    )
  })

  it("first-load 400 (malformed date) does NOT elevate connected", async () => {
    // An invalid date has no account verdict.
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 400,
      errors: { detail: "Invalid date format." },
    })
    const todoist = useTodoist()
    await todoist.fetchTasks("not-a-date")
    expect(todoist.state.connected).toBe(false)
    expect(todoist.state.statusKnown).toBe(false)
    expect(todoist.state.error).toBe("Invalid date format.")
  })

  it("AbortError from a superseded request leaves connected/statusKnown untouched", async () => {
    const aborted = new DOMException("aborted", "AbortError")
    requestJsonMock
      .mockImplementationOnce(() => Promise.reject(aborted))
      .mockResolvedValueOnce({
        ok: true,
        status: 200,
        data: { tasks: [taskPayload("ok", "OK")] },
      })

    const todoist = useTodoist()
    const p1 = todoist.fetchTasks("2026-05-07")
    const p2 = todoist.fetchTasks("2026-05-08")
    await p1
    await p2

    expect(todoist.state.error).toBeNull()
    expect(todoist.state.tasks[0].title).toBe("OK")
    expect(todoist.state.connected).toBe(true)
    expect(todoist.state.statusKnown).toBe(true)
  })

  it("stale-commit-guard early-return leaves connected/statusKnown untouched", async () => {
    // The stale (first) fetch resolves with an error AFTER a newer fetch has
    // already committed an ok result. The stale error must be dropped by the
    // dual commit guard — neither connected nor statusKnown reverts.
    const d1 = defer<{
      ok: boolean
      data?: object
      status?: number
      errors?: object
    }>()
    const d2 = defer<{ ok: boolean; data?: object; status?: number }>()
    requestJsonMock
      .mockReturnValueOnce(d1.promise)
      .mockReturnValueOnce(d2.promise)

    const todoist = useTodoist()
    const p1 = todoist.fetchTasks("2026-05-01")
    const p2 = todoist.fetchTasks("2026-05-02")

    d2.resolve({
      ok: true,
      status: 200,
      data: { tasks: [taskPayload("d2", "Day 2")] },
    })
    await p2
    // Newer fetch already committed.
    expect(todoist.state.connected).toBe(true)
    expect(todoist.state.statusKnown).toBe(true)

    // Stale fetch resolves late with a 503 — must be dropped (no flip to
    // connected=false, no error).
    d1.resolve({
      ok: false,
      status: 503,
      data: { meta: { account_state: "disconnected", resource_state: "unavailable" } },
      errors: { detail: "No Todoist account configured" },
    })
    await p1

    expect(todoist.state.connected).toBe(true)
    expect(todoist.state.statusKnown).toBe(true)
    expect(todoist.state.error).toBeNull()
    expect(todoist.state.tasks[0].title).toBe("Day 2")
  })
})

describe("useTodoist.fetchAccountStatus", () => {
  beforeEach(() => {
    requestJsonMock.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("fetchTasks and fetchAccountStatus do not cancel each other", async () => {
    const dStatus = defer<{ ok: boolean; data?: object; status?: number }>()
    const dTasks = defer<{ ok: boolean; data?: object; status?: number }>()
    requestJsonMock
      .mockReturnValueOnce(dStatus.promise)
      .mockReturnValueOnce(dTasks.promise)

    const todoist = useTodoist()
    const pStatus = todoist.fetchAccountStatus()
    const pTasks = todoist.fetchTasks("2026-05-07")

    dTasks.resolve({ ok: true, status: 200, data: { tasks: [] } })
    dStatus.resolve({
      ok: true,
      status: 200,
      data: { connected: true, last_verified_at: null },
    })

    await pStatus
    await pTasks
    await nextTick()

    expect(todoist.state.connected).toBe(true)
    expect(todoist.state.statusKnown).toBe(true)
    expect(todoist.state.tasks).toEqual([])
  })
})

describe("useTodoist.completeTask", () => {
  beforeEach(() => {
    requestJsonMock.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("optimistically removes the row and keeps it removed on ok", async () => {
    requestJsonMock.mockResolvedValueOnce({ ok: true, status: 200, data: {} })
    const todoist = useTodoist()
    todoist.state.tasks = [taskPayload("A", "A"), taskPayload("B", "B")]

    await todoist.completeTask("A")

    expect(todoist.state.tasks.map((t) => t.id)).toEqual(["B"])
    expect(todoist.state.error).toBeNull()
    // POST shape: (url, "POST", undefined) — no body, no GET footgun.
    const [url, method, body] = requestJsonMock.mock.calls[0]
    expect(url).toBe("/api/todoist/tasks/A/complete/")
    expect(method).toBe("POST")
    expect(body).toBeUndefined()
  })

  it.each([
    [401, /credentials invalid/i],
    [502, /unavailable/i],
    [504, /unavailable/i],
  ])(
    "rolls back (task re-inserted at its index) + sets error on %i; leaves connected/statusKnown",
    async (status, messageRe) => {
      requestJsonMock.mockResolvedValueOnce({
        ok: false,
        status,
        ...(status === 401 ? { code: "integration_credentials_error", data: { meta: { account_state: "connected", resource_state: "credentials_error" } } } : {}),
        errors: { detail: "boom" },
      })
      const todoist = useTodoist()
      todoist.state.tasks = [taskPayload("A", "A"), taskPayload("B", "B")]
      todoist.state.connected = true
      todoist.state.statusKnown = true

      await todoist.completeTask("A")

      expect(todoist.state.tasks.map((t) => t.id)).toEqual(["A", "B"])
      expect(todoist.state.error).toMatch(messageRe)
      // Completion failure must NOT touch connection state.
      expect(todoist.state.connected).toBe(true)
      expect(todoist.state.statusKnown).toBe(true)
    },
  )

  it("rolls back and surfaces a no-status network error", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      errors: { detail: "Network error. Please check your connection." },
    })
    const todoist = useTodoist()
    todoist.state.tasks = [taskPayload("A", "A"), taskPayload("B", "B")]

    await todoist.completeTask("A")

    expect(todoist.state.tasks.map((t) => t.id)).toEqual(["A", "B"])
    expect(todoist.state.error).toBe(
      "Network error. Please check your connection.",
    )
  })

  it("failure after a concurrent refresh does not clobber the refreshed list (P1 race)", async () => {
    const dComplete = defer<{ ok: boolean; status?: number; errors?: object }>()
    requestJsonMock.mockReturnValueOnce(dComplete.promise)
    const todoist = useTodoist()
    todoist.state.tasks = [taskPayload("A", "A"), taskPayload("B", "B")]

    const p = todoist.completeTask("A")
    // Optimistic remove → [B].
    expect(todoist.state.tasks.map((t) => t.id)).toEqual(["B"])
    // A concurrent refreshTasks commit lands → [B, C].
    todoist.state.tasks = [taskPayload("B", "B"), taskPayload("C", "C")]
    // Complete POST then fails.
    dComplete.resolve({
      ok: false,
      status: 502,
      errors: { detail: "bad gateway" },
    })
    await p

    // A surgically re-inserted at its index, C preserved — NOT [A, B]
    // (which a stale whole-list restore would produce, dropping C).
    expect(todoist.state.tasks.map((t) => t.id)).toEqual(["A", "B", "C"])
  })

  it("success after a concurrent refresh re-added the task keeps it removed (P1 race, success side)", async () => {
    const dComplete = defer<{ ok: boolean; status?: number; data?: object }>()
    requestJsonMock.mockReturnValueOnce(dComplete.promise)
    const todoist = useTodoist()
    todoist.state.tasks = [taskPayload("A", "A"), taskPayload("B", "B")]

    const p = todoist.completeTask("A")
    expect(todoist.state.tasks.map((t) => t.id)).toEqual(["B"])
    // Refresh raced ahead of the close → re-added A: [A, B, C].
    todoist.state.tasks = [
      taskPayload("A", "A"),
      taskPayload("B", "B"),
      taskPayload("C", "C"),
    ]
    dComplete.resolve({ ok: true, status: 200, data: {} })
    await p

    // The step-4 idempotent re-filter drops the re-added A → [B, C].
    expect(todoist.state.tasks.map((t) => t.id)).toEqual(["B", "C"])
  })
})

describe("useTodoist.refreshTasks", () => {
  beforeEach(() => {
    requestJsonMock.mockReset()
  })

  afterEach(() => {
    vi.restoreAllMocks()
  })

  it("appends only refresh=1 even for browser-local today", async () => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 5, 18, 12, 0, 0))
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { tasks: [] },
    })
    const todoist = useTodoist()
    await todoist.refreshTasks("2026-06-18")

    expect(requestJsonMock.mock.calls[0][0]).toBe(
      "/api/todoist/tasks/2026-06-18/?refresh=1",
    )
    vi.useRealTimers()
  })

  it("appends only refresh=1 for a non-today date", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: true,
      status: 200,
      data: { tasks: [] },
    })
    const todoist = useTodoist()
    await todoist.refreshTasks("2025-02-12")

    expect(requestJsonMock.mock.calls[0][0]).toBe(
      "/api/todoist/tasks/2025-02-12/?refresh=1",
    )
  })

  it("shares the dual commit guard with fetchTasks (a superseded refresh is dropped)", async () => {
    const d1 = defer<{ ok: boolean; data?: object; status?: number }>()
    const d2 = defer<{ ok: boolean; data?: object; status?: number }>()
    requestJsonMock
      .mockReturnValueOnce(d1.promise)
      .mockReturnValueOnce(d2.promise)

    const todoist = useTodoist()
    const p1 = todoist.refreshTasks("2026-05-01")
    const p2 = todoist.fetchTasks("2026-05-02")

    d2.resolve({
      ok: true,
      status: 200,
      data: { tasks: [taskPayload("d2", "Day 2")] },
    })
    d1.resolve({
      ok: true,
      status: 200,
      data: { tasks: [taskPayload("d1", "Day 1")] },
    })

    await p2
    await p1

    expect(todoist.state.tasks).toHaveLength(1)
    expect(todoist.state.tasks[0].title).toBe("Day 2")
  })

  it("stays silent: loading never flips true and rows stay populated until the atomic commit", async () => {
    const dRefresh = defer<{ ok: boolean; data?: object; status?: number }>()
    requestJsonMock.mockReturnValueOnce(dRefresh.promise)
    const todoist = useTodoist()
    todoist.state.tasks = [taskPayload("A", "A"), taskPayload("B", "B")]
    todoist.state.connected = true
    todoist.state.statusKnown = true

    const p = todoist.refreshTasks("2026-05-07")
    // Mid-flight: no skeleton flash — loading stays false, rows remain.
    expect(todoist.state.loading).toBe(false)
    expect(todoist.state.tasks).toHaveLength(2)

    dRefresh.resolve({
      ok: true,
      status: 200,
      data: { tasks: [taskPayload("C", "C")] },
    })
    await p

    expect(todoist.state.loading).toBe(false)
    expect(todoist.state.tasks.map((t) => t.id)).toEqual(["C"])
  })
})

// Fallback-literal guard (feature 0037): pin the exact fallback string at
// BOTH call sites (_fetchTasks + completeTask). A `default`-branch status
// (500) makes statusToMessage return null so control reaches the shared
// helper; 500 also elevates `connected` (>= 401) so the error surfaces.
describe("useTodoist fallback-literal guard", () => {
  beforeEach(() => requestJsonMock.mockReset())

  it("fetchTasks surfaces the exact fallback literal on an empty errors map", async () => {
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      errors: {},
    })
    const todoist = useTodoist()
    await todoist.fetchTasks("2026-05-07")
    expect(todoist.state.error).toBe("Todoist fetch failed")
  })

  it("completeTask surfaces the exact fallback literal on an empty errors map", async () => {
    const todoist = useTodoist()
    todoist.state.tasks = [taskPayload("A", "A")]
    requestJsonMock.mockResolvedValueOnce({
      ok: false,
      status: 500,
      errors: {},
    })
    await todoist.completeTask("A")
    expect(todoist.state.error).toBe("Todoist fetch failed")
  })
})
