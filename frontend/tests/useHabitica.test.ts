// Habitica account verdicts come from explicit response metadata. Completion
// rolls back one row without replacing a concurrent refresh's full list.

import { describe, it, expect, vi, beforeEach } from "vitest"

const requestJson = vi.fn()

// Indirect through an arrow so the hoisted factory doesn't capture the
// binding before initialisation (same shape as useTodoist.test.ts).
vi.mock("../src/composables/useHttp", () => ({
  requestJson: (...args: unknown[]) => requestJson(...args),
}))

import { useHabitica } from "../src/composables/useHabitica"
import type { HabiticaTask } from "../src/types/habitica"

// No `as HabiticaTask` cast: the annotation alone must typecheck, so a field
// rename or addition on the interface breaks this factory instead of silently
// producing objects that do not match the real shape.
function task(id: string, title = `Task ${id}`): HabiticaTask {
  return { id, title, type: "todo", due_date: null, completed: false }
}

const TODAY = "2026-07-22"

beforeEach(() => {
  requestJson.mockReset()
})

describe("useHabitica connected-state elevation", () => {
  it("resolves disconnected on 503 without elevating connected", async () => {
    requestJson.mockResolvedValue({ ok: false, status: 503, data: { meta: { account_state: "disconnected", resource_state: "unavailable" } }, errors: {} })
    const { state, fetchTasks } = useHabitica()
    await fetchTasks(TODAY)

    expect(state.connected).toBe(false)
    expect(state.statusKnown).toBe(true)
  })

  it.each([401, 500, 502, 504])(
    "uses explicit connected metadata on %i",
    async (status) => {
      requestJson.mockResolvedValue({ ok: false, status, data: { meta: { account_state: "connected", resource_state: status === 401 ? "credentials_error" : "provider_error" } }, errors: {} })
      const { state, fetchTasks } = useHabitica()
      await fetchTasks(TODAY)

      expect(state.connected).toBe(true)
      expect(state.statusKnown).toBe(true)
      expect(state.error).toBeTruthy()
    },
  )

  it("does NOT elevate connected when the failure carries no status", async () => {
    // A network failure has no account verdict.
    requestJson.mockResolvedValue({
      ok: false,
      errors: { detail: "Network error" },
    })
    const { state, fetchTasks } = useHabitica()
    await fetchTasks(TODAY)

    expect(state.connected).toBe(false)
    expect(state.statusKnown).toBe(false)
    expect(state.error).toBeTruthy()
  })

  it("does NOT elevate connected on 400 (returned before the account check)", async () => {
    // A malformed date 400s ahead of the account-existence lookup, so it
    // proves nothing about whether the row exists.
    requestJson.mockResolvedValue({ ok: false, status: 400, errors: {} })
    const { state, fetchTasks } = useHabitica()
    await fetchTasks(TODAY)

    expect(state.connected).toBe(false)
    expect(state.statusKnown).toBe(false)
  })

  it("sets connected and commits tasks on success", async () => {
    requestJson.mockResolvedValue({
      ok: true,
      status: 200,
      data: { tasks: [task("1"), task("2")] },
    })
    const { state, fetchTasks } = useHabitica()
    await fetchTasks(TODAY)

    expect(state.connected).toBe(true)
    expect(state.statusKnown).toBe(true)
    expect(state.tasks.map((t) => t.id)).toEqual(["1", "2"])
    expect(state.error).toBeNull()
  })
})

describe("useHabitica completeTask", () => {
  async function seed(ids: string[]) {
    requestJson.mockResolvedValue({
      ok: true,
      status: 200,
      data: { tasks: ids.map((id) => task(id)) },
    })
    const api = useHabitica()
    await api.fetchTasks(TODAY)
    requestJson.mockReset()
    return api
  }

  it("removes the task optimistically and keeps it gone on ack", async () => {
    const { state, completeTask } = await seed(["1", "2", "3"])
    requestJson.mockResolvedValue({ ok: true, status: 200 })

    await completeTask("2")

    expect(state.tasks.map((t) => t.id)).toEqual(["1", "3"])
    expect(state.error).toBeNull()
  })

  it("re-inserts at the ORIGINAL index on failure", async () => {
    const { state, completeTask } = await seed(["1", "2", "3"])
    requestJson.mockResolvedValue({ ok: false, status: 502, errors: {} })

    await completeTask("2")

    // Position matters: appending would silently reorder the user's list.
    expect(state.tasks.map((t) => t.id)).toEqual(["1", "2", "3"])
    expect(state.error).toBeTruthy()
  })

  it("does not duplicate when a concurrent refresh already re-added the task", async () => {
    const { state, completeTask } = await seed(["1", "2"])
    requestJson.mockImplementation(async () => {
      // Simulate a refresh landing mid-flight that re-inserts the task.
      state.tasks = [task("1"), task("2")]
      return { ok: false, status: 502, errors: {} }
    })

    await completeTask("2")

    expect(state.tasks.filter((t) => t.id === "2")).toHaveLength(1)
  })

  it("leaves connection state untouched on completion failure", async () => {
    const { state, completeTask } = await seed(["1"])
    const before = {
      connected: state.connected,
      statusKnown: state.statusKnown,
    }
    requestJson.mockResolvedValue({ ok: false, status: 502, errors: {} })

    await completeTask("1")

    expect(state.connected).toBe(before.connected)
    expect(state.statusKnown).toBe(before.statusKnown)
  })
})

describe("useHabitica refreshTasks", () => {
  it("forces a cache bypass and does not flip the loading skeleton", async () => {
    requestJson.mockResolvedValue({
      ok: true,
      status: 200,
      data: { tasks: [] },
    })
    const { state, refreshTasks } = useHabitica()

    const pending = refreshTasks(TODAY)
    expect(state.loading).toBe(false)
    await pending

    const url = requestJson.mock.calls[0][0] as string
    expect(url).toContain("refresh=1")
  })

  it("fetchTasks does NOT force a cache bypass", async () => {
    requestJson.mockResolvedValue({
      ok: true,
      status: 200,
      data: { tasks: [] },
    })
    const { fetchTasks } = useHabitica()
    await fetchTasks(TODAY)

    expect(requestJson.mock.calls[0][0]).not.toContain("refresh=1")
  })
})

// Fallback-literal guard (feature 0037): pin the exact fallback string at
// BOTH call sites (_fetchTasks + completeTask). A `default`-branch status
// (500) makes statusToMessage return null so control reaches the shared
// helper; 500 also elevates `connected` (>= 401) so the error surfaces.
describe("useHabitica fallback-literal guard", () => {
  it("fetchTasks surfaces the exact fallback literal on an empty errors map", async () => {
    requestJson.mockResolvedValueOnce({ ok: false, status: 500, errors: {} })
    const { state, fetchTasks } = useHabitica()
    await fetchTasks(TODAY)
    expect(state.error).toBe("Habitica fetch failed")
  })

  it("completeTask surfaces the exact fallback literal on an empty errors map", async () => {
    const api = useHabitica()
    api.state.tasks = [task("A")]
    requestJson.mockResolvedValueOnce({ ok: false, status: 500, errors: {} })
    await api.completeTask("A")
    expect(api.state.error).toBe("Habitica fetch failed")
  })
})
