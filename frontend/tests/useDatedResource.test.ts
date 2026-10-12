import { beforeEach, describe, expect, it, vi } from "vitest"
import { effectScope, ref } from "vue"

const requestJson = vi.fn()
vi.mock("../src/composables/useHttp", () => ({
  requestJson: (...args: unknown[]) => requestJson(...args),
}))

import { useCalendar } from "../src/composables/useCalendar"
import { useGoogleCalendar } from "../src/composables/useGoogleCalendar"
import { useTodoist } from "../src/composables/useTodoist"
import { useHabitica } from "../src/composables/useHabitica"

type Row = { id?: string; external_uid?: string }
type Harness = {
  state: {
    loading: boolean; error: string | null; connected: boolean; statusKnown: boolean
    accountState: string; resourceState: string
  }
  rows: () => Row[]
  fetch: (date: string) => Promise<void>
  refresh: (date: string) => Promise<void>
  status: () => Promise<void>
  invalidate: () => void
  dispose: () => void
  complete?: (id: string) => Promise<void>
}

const task = (id: string) => ({ id, title: id, priority: 1, ui_priority: "P4", due_date: null })
const habit = (id: string) => ({ id, title: id, type: "todo" as const, due_date: null, completed: false })
const event = (id: string) => ({ external_uid: id, title: id, start: "2026-01-01T10:00:00Z", end: "2026-01-01T11:00:00Z", calendar_name: "Test", all_day: false, account_label: "" })
const connected = { account_state: "connected", resource_state: "ready" }
const disconnected = { account_state: "disconnected", resource_state: "unavailable" }

const adapters: { name: string; make: (context?: () => string) => Harness; data: Record<string, unknown>; rows: Row[] }[] = [
  {
    name: "Apple", data: { events: [event("a")] }, rows: [event("a")],
    make: (context) => { const api = useCalendar(context); return { state: api.state, rows: () => api.state.events, fetch: api.fetchEvents, refresh: api.refreshEvents, status: api.fetchAccountStatus, invalidate: () => api.invalidateAccount(), dispose: api.dispose } },
  },
  {
    name: "Google", data: { events: [event("a")], account_errors: [] }, rows: [event("a")],
    make: (context) => { const api = useGoogleCalendar(context); return { state: api.state, rows: () => api.state.events, fetch: api.fetchEvents, refresh: api.refreshEvents, status: api.fetchAccountStatus, invalidate: () => api.invalidateAccount(), dispose: api.dispose } },
  },
  {
    name: "Todoist", data: { tasks: [task("a")] }, rows: [task("a")],
    make: (context) => { const api = useTodoist(context); return { state: api.state, rows: () => api.state.tasks, fetch: api.fetchTasks, refresh: api.refreshTasks, status: api.fetchAccountStatus, invalidate: () => api.invalidateAccount(), dispose: api.dispose, complete: api.completeTask } },
  },
  {
    name: "Habitica", data: { tasks: [habit("a")] }, rows: [habit("a")],
    make: (context) => { const api = useHabitica(context); return { state: api.state, rows: () => api.state.tasks, fetch: api.fetchTasks, refresh: api.refreshTasks, status: api.fetchAccountStatus, invalidate: () => api.invalidateAccount(), dispose: api.dispose, complete: api.completeTask } },
  },
]

function deferred<T>() {
  let resolve!: (value: T) => void
  let reject!: (reason: unknown) => void
  const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej })
  return { promise, resolve, reject }
}

beforeEach(() => requestJson.mockReset())

for (const adapter of adapters) {
  describe(`${adapter.name} dated resource`, () => {
    it.each([
      [401, "credentials_error"], [502, "provider_error"], [504, "unavailable"],
    ] as const)("uses explicit account metadata on %i", async (status, resourceState) => {
      requestJson.mockResolvedValue({ ok: false, status, data: { meta: { account_state: "connected", resource_state: resourceState } }, errors: { detail: "failed" } })
      const api = adapter.make()
      await api.fetch("2026-01-01")
      expect(api.state.accountState).toBe("connected")
      expect(api.state.resourceState).toBe(resourceState)
      expect(api.state.connected).toBe(true)
      expect(api.state.error).toBeTruthy()
    })

    it("accepts valid rows and a disconnected verdict", async () => {
      requestJson.mockResolvedValueOnce({ ok: true, status: 200, data: { ...adapter.data, meta: connected } })
        .mockResolvedValueOnce({ ok: false, status: 503, data: { meta: disconnected }, errors: {} })
      const api = adapter.make()
      await api.fetch("2026-01-01")
      expect(api.rows()).toEqual(adapter.rows)
      expect(api.state.accountState).toBe("connected")
      await api.refresh("2026-01-01")
      expect(api.rows()).toEqual([])
      expect(api.state.accountState).toBe("disconnected")
      expect(api.state.error).toBeNull()
    })

    it.each([401, 502, 503, undefined])("does not derive account state from bare %s", async (status) => {
      requestJson.mockResolvedValue({ ok: false, status, errors: { detail: "ambiguous" } })
      const api = adapter.make()
      await api.fetch("2026-01-01")
      expect(api.state.accountState).toBe("unknown")
      expect(api.state.statusKnown).toBe(false)
      expect(api.state.connected).toBe(false)
      expect(api.state.error).toBeTruthy()
    })

    it("preserves same-date rows on failure and clears them on date change", async () => {
      requestJson.mockResolvedValueOnce({ ok: true, status: 200, data: adapter.data })
        .mockResolvedValue({ ok: false, errors: { detail: "offline" } })
      const api = adapter.make()
      await api.fetch("2026-01-01")
      await api.refresh("2026-01-01")
      expect(api.rows()).toEqual(adapter.rows)
      await api.refresh("2026-01-02")
      expect(api.rows()).toEqual([])
      expect(api.state.resourceState).toBe("network_error")
    })

    it("rejects a malformed success verdict without changing account state", async () => {
      requestJson.mockResolvedValue({ ok: true, status: 200, data: { ...adapter.data, meta: { account_state: "disconnected", resource_state: "ready" } } })
      const api = adapter.make()
      await api.fetch("2026-01-01")
      expect(api.rows()).toEqual([])
      expect(api.state.accountState).toBe("unknown")
      expect(api.state.error).toBe("Invalid server response.")
    })

    it("drops stale results and aborts on explicit disconnect", async () => {
      const first = deferred<unknown>()
      requestJson.mockReturnValueOnce(first.promise)
      const api = adapter.make()
      const pending = api.fetch("2026-01-01")
      const signal = requestJson.mock.calls[0][3].signal as AbortSignal
      api.invalidate()
      expect(signal.aborted).toBe(true)
      first.resolve({ ok: true, status: 200, data: adapter.data })
      await pending
      expect(api.rows()).toEqual([])
      expect(api.state.accountState).toBe("disconnected")
    })

    it("a status read cannot overwrite a newer resource verdict", async () => {
      const oldStatus = deferred<unknown>()
      requestJson.mockReturnValueOnce(oldStatus.promise)
        .mockResolvedValueOnce({ ok: true, status: 200, data: adapter.data })
      const api = adapter.make()
      const status = api.status()
      await api.fetch("2026-01-01")
      oldStatus.resolve({ ok: true, status: 200, data: { connected: false, accounts: [] } })
      await status
      expect(api.state.accountState).toBe("connected")
    })

    it("scope disposal aborts the request without an error", async () => {
      const pendingResponse = deferred<unknown>()
      requestJson.mockReturnValueOnce(pendingResponse.promise)
      const scope = effectScope()
      const api = scope.run(() => adapter.make())!
      const pending = api.fetch("2026-01-01")
      const signal = requestJson.mock.calls[0][3].signal as AbortSignal
      scope.stop()
      expect(signal.aborted).toBe(true)
      pendingResponse.reject(new DOMException("Aborted", "AbortError"))
      await pending
      expect(api.state.error).toBeNull()
      expect(api.rows()).toEqual([])
    })
  })
}

it("Google retains successful accounts and their partial errors", async () => {
  const google = useGoogleCalendar()
  requestJson.mockResolvedValue({ ok: true, status: 200, data: { events: [event("a")], account_errors: [{ account_id: 1, email: "a@example.com", error: "reconnect_required" }], meta: connected } })
  await google.fetchEvents("2026-01-01")
  expect(google.state.events).toHaveLength(1)
  expect(google.state.accountErrors).toHaveLength(1)
  expect(google.state.error).toBeNull()
})

for (const adapter of adapters.filter((item) => item.name === "Todoist" || item.name === "Habitica")) {
  it(`${adapter.name} rejects completion after disposal`, async () => {
    const api = adapter.make()
    api.dispose()
    await api.complete!("a")
    expect(requestJson).not.toHaveBeenCalled()
  })

  it(`${adapter.name} disconnect prevents a late completion rollback`, async () => {
    const api = adapter.make()
    requestJson.mockResolvedValueOnce({ ok: true, status: 200, data: adapter.data })
    await api.fetch("2026-01-01")
    const completingResponse = deferred<unknown>()
    requestJson.mockReturnValueOnce(completingResponse.promise)
      .mockResolvedValueOnce({ ok: false, status: 503, data: { meta: disconnected }, errors: {} })
    const completing = api.complete!("a")
    const signal = requestJson.mock.calls[1][3].signal as AbortSignal
    await api.refresh("2026-01-01")
    expect(signal.aborted).toBe(true)
    completingResponse.resolve({ ok: false, status: 502, errors: {} })
    await completing
    expect(api.rows()).toEqual([])
    expect(api.state.accountState).toBe("disconnected")
  })

  it(`${adapter.name} completion's own disconnected verdict clears the source`, async () => {
    const api = adapter.make()
    requestJson.mockResolvedValueOnce({ ok: true, status: 200, data: adapter.data })
    await api.fetch("2026-01-01")
    requestJson.mockResolvedValueOnce({ ok: false, status: 503, data: { meta: disconnected }, errors: {} })
    await api.complete!("a")
    expect(api.rows()).toEqual([])
    expect(api.state.accountState).toBe("disconnected")
    expect(api.state.error).toBeNull()
  })

  it(`${adapter.name} completion keeps a session 401 distinct from provider credentials`, async () => {
    const api = adapter.make()
    requestJson.mockResolvedValueOnce({ ok: true, status: 200, data: adapter.data })
    await api.fetch("2026-01-01")
    requestJson.mockResolvedValueOnce({ ok: false, status: 401, code: "session_invalid", errors: { detail: "Session expired. Sign in again." } })
    await api.complete!("a")
    expect(api.rows()).toEqual(adapter.rows)
    expect(api.state.error).toBe("Session expired. Sign in again.")
  })

  it(`${adapter.name} releases a completed ID after the provider confirms its absence`, async () => {
    const api = adapter.make()
    requestJson.mockResolvedValueOnce({ ok: true, status: 200, data: adapter.data })
    await api.fetch("2026-01-01")
    requestJson.mockResolvedValueOnce({ ok: true, status: 200 })
    await api.complete!("a")
    requestJson.mockResolvedValueOnce({ ok: true, status: 200, data: { tasks: [] } })
    await api.refresh("2026-01-01")
    requestJson.mockResolvedValueOnce({ ok: true, status: 200, data: adapter.data })
    await api.refresh("2026-01-01")
    expect(api.rows()).toEqual(adapter.rows)
  })

  it(`${adapter.name} completion filters an older GET and ignores A to B to A acknowledgement`, async () => {
    const context = ref("A")
    const api = adapter.make(() => context.value)
    requestJson.mockResolvedValueOnce({ ok: true, status: 200, data: adapter.data })
    await api.fetch("2026-01-01")
    const complete = deferred<unknown>()
    const staleGet = deferred<unknown>()
    requestJson.mockReturnValueOnce(complete.promise).mockReturnValueOnce(staleGet.promise)
    const completing = api.complete!("a")
    const loading = api.refresh("2026-01-01")
    staleGet.resolve({ ok: true, status: 200, data: adapter.data })
    await loading
    expect(api.rows()).toEqual([])
    complete.resolve({ ok: true, status: 200 })
    await completing
    expect(api.rows()).toEqual([])

    context.value = "B"
    context.value = "A"
    requestJson.mockResolvedValueOnce({ ok: true, status: 200, data: adapter.data })
    await api.fetch("2026-01-01")
    const oldAck = deferred<unknown>()
    requestJson.mockReturnValueOnce(oldAck.promise)
    const anotherCompletion = api.complete!("a")
    context.value = "B"
    context.value = "A"
    requestJson.mockResolvedValueOnce({ ok: true, status: 200, data: adapter.data })
    await api.fetch("2026-01-01")
    oldAck.resolve({ ok: true, status: 200 })
    await anotherCompletion
    expect(api.rows()).toEqual(adapter.rows)
  })
}
