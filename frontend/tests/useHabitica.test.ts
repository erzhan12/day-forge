// useHabitica — connected-state elevation and optimistic-complete rollback.
//
// Two things here are load-bearing and were previously untested:
//
// 1. The `connected` elevation guard. `fetchTasks` deliberately diverges from
//    useCalendar: a non-503 error elevates `connected` so the error surfaces
//    past the `!connected` panel gate. The precondition is "a definitive HTTP
//    status proves the account row exists" — so the branches where that
//    precondition is FALSE (no status at all, or a 400 returned before the
//    account check) must NOT elevate. This is the exact feature-0020
//    regression recorded in tasks/lessons.md: the original coded it as a bare
//    `else`, which swallowed the no-status case and showed the panel to a
//    disconnected user after a mere network blip.
//
// 2. `completeTask`'s surgical rollback. On failure it re-inserts the single
//    removed task at its original index rather than restoring a whole-list
//    snapshot, which would resurrect stale rows and drop tasks a concurrent
//    refresh added.

import { describe, it, expect, vi, beforeEach } from "vitest"

const requestJson = vi.fn()

// Indirect through an arrow so the hoisted factory doesn't capture the
// binding before initialisation (same shape as useTodoist.test.ts).
vi.mock("../src/composables/useHttp", () => ({
  requestJson: (...args: unknown[]) => requestJson(...args),
}))

import { useHabitica } from "../src/composables/useHabitica"
import type { HabiticaTask } from "../src/types/habitica"

function task(id: string, title = `Task ${id}`): HabiticaTask {
  return { id, title, due_date: null, task_type: "todo" } as HabiticaTask
}

const TODAY = "2026-07-22"

beforeEach(() => {
  requestJson.mockReset()
})

describe("useHabitica connected-state elevation", () => {
  it("resolves disconnected on 503 without elevating connected", async () => {
    requestJson.mockResolvedValue({ ok: false, status: 503, errors: {} })
    const { state, fetchTasks } = useHabitica()
    await fetchTasks(TODAY)

    expect(state.connected).toBe(false)
    expect(state.statusKnown).toBe(true)
  })

  it.each([401, 500, 502, 504])(
    "elevates connected on %i (a real status proves the row exists)",
    async (status) => {
      requestJson.mockResolvedValue({ ok: false, status, errors: {} })
      const { state, fetchTasks } = useHabitica()
      await fetchTasks(TODAY)

      expect(state.connected).toBe(true)
      expect(state.statusKnown).toBe(true)
      expect(state.error).toBeTruthy()
    },
  )

  it("does NOT elevate connected when the failure carries no status", async () => {
    // useHttp returns {ok:false, errors} with NO status on a network/parse
    // failure. Elevating here would show the panel to a user who may not be
    // connected at all — the feature-0020 regression (tasks/lessons.md).
    requestJson.mockResolvedValue({
      ok: false,
      errors: { detail: "Network error" },
    })
    const { state, fetchTasks } = useHabitica()
    await fetchTasks(TODAY)

    expect(state.connected).toBe(false)
    expect(state.statusKnown).toBe(true)
    expect(state.error).toBeTruthy()
  })

  it("does NOT elevate connected on 400 (returned before the account check)", async () => {
    // A malformed date 400s ahead of the account-existence lookup, so it
    // proves nothing about whether the row exists.
    requestJson.mockResolvedValue({ ok: false, status: 400, errors: {} })
    const { state, fetchTasks } = useHabitica()
    await fetchTasks(TODAY)

    expect(state.connected).toBe(false)
    expect(state.statusKnown).toBe(true)
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
    const before = { connected: state.connected, statusKnown: state.statusKnown }
    requestJson.mockResolvedValue({ ok: false, status: 502, errors: {} })

    await completeTask("1")

    expect(state.connected).toBe(before.connected)
    expect(state.statusKnown).toBe(before.statusKnown)
  })
})

describe("useHabitica refreshTasks", () => {
  it("forces a cache bypass and does not flip the loading skeleton", async () => {
    requestJson.mockResolvedValue({ ok: true, status: 200, data: { tasks: [] } })
    const { state, refreshTasks } = useHabitica()

    const pending = refreshTasks(TODAY)
    expect(state.loading).toBe(false)
    await pending

    const url = requestJson.mock.calls[0][0] as string
    expect(url).toContain("refresh=1")
  })

  it("fetchTasks does NOT force a cache bypass", async () => {
    requestJson.mockResolvedValue({ ok: true, status: 200, data: { tasks: [] } })
    const { fetchTasks } = useHabitica()
    await fetchTasks(TODAY)

    expect(requestJson.mock.calls[0][0]).not.toContain("refresh=1")
  })
})
