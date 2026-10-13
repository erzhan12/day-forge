import { beforeEach, afterEach, describe, expect, it, vi } from "vitest"
import { defineComponent, h, nextTick, provide, ref } from "vue"
import { mount } from "@vue/test-utils"
import { router } from "@inertiajs/vue3"
import { createScheduleRevision, provideScheduleRevision, runScheduleMutation, type ScheduleRevisionState } from "../src/composables/useScheduleRevision"
import { createScheduleWriteCoordinator, ScheduleWriteCoordinatorKey } from "../src/composables/scheduleWriteCoordinator"
import { useSchedule } from "../src/composables/useSchedule"
import { useUndo } from "../src/composables/useUndo"
import type { Schedule, TimeBlock } from "../src/types"
import { revisionEnvelope } from "./helpers/schedule"

vi.mock("@inertiajs/vue3", () => ({ router: { reload: vi.fn() } }))
const DATE = "2026-10-10"
const OTHER = "2026-10-11"
const payload = { title: "Work", start_time: "09:00", end_time: "10:00", category: "work" }
const block: TimeBlock = { id: 1, ...payload, is_completed: false, sort_order: 0 }
function response(ok: boolean, body: unknown, status = ok ? 200 : 400) {
  return { ok, status, text: async () => JSON.stringify(body) }
}
function deferred<T>() { let resolve!: (value: T) => void; const promise = new Promise<T>((r) => { resolve = r }); return { promise, resolve } }
function fixture(initialRevision = 3) {
  const input = ref({ date: DATE, user: 7 as number | null, schedule: { id: 1, date: DATE, status: "active", revision: initialRevision } as Schedule, blocks: [] as TimeBlock[] })
  const state = createScheduleRevision(() => input.value.date, () => input.value.schedule, { getBlocks: () => input.value.blocks, getUserId: () => input.value.user })
  return { input, state, api: useSchedule(() => input.value.date, state) }
}
function contextFixture() {
  const input = ref({ date: DATE, user: 7 as number | null, zone: "UTC", schedule: { id: 1, date: DATE, status: "active", revision: 3 } as Schedule, blocks: [] as TimeBlock[] })
  const state = createScheduleRevision(() => input.value.date, () => input.value.schedule, {
    getBlocks: () => input.value.blocks,
    getUserId: () => input.value.user,
    getContextKey: () => input.value.zone,
  })
  return { input, state }
}
function mountUndo(f: ReturnType<typeof fixture>) {
  let undo!: ReturnType<typeof useUndo>
  const wrapper = mount(defineComponent({ setup() { undo = useUndo(() => f.input.value.date, () => f.state.blocks.value, () => f.state.busy.value, f.state); return () => null } }))
  return { undo, wrapper }
}
function remountFixture() {
  const coordinator = createScheduleWriteCoordinator()
  const route = ref(DATE)
  const visit = ref(0)
  const pageProps = ref({ schedule: { id: 1, date: DATE, status: "active", revision: 3 } as Schedule, blocks: [] as TimeBlock[] })
  let owner!: ScheduleRevisionState
  const Page = defineComponent({
    setup() {
      owner = provideScheduleRevision(() => route.value, () => pageProps.value.schedule, {
        getBlocks: () => pageProps.value.blocks, getUserId: () => 7,
      })
      return () => h("main")
    },
  })
  const Root = defineComponent({
    setup() {
      provide(ScheduleWriteCoordinatorKey, coordinator)
      return () => h(Page, { key: `${route.value}:${visit.value}` })
    },
  })
  const wrapper = mount(Root)
  async function navigate(date: string, revision: number, blocks: TimeBlock[] = []) {
    route.value = date
    pageProps.value = { schedule: { id: date === DATE ? 1 : 2, date, status: "active", revision }, blocks }
    visit.value += 1
    await nextTick()
    return owner
  }
  return { coordinator, pageProps, wrapper, navigate, get owner() { return owner } }
}
beforeEach(() => {
  vi.clearAllMocks()
  vi.mocked(router.reload).mockImplementation((options) => { options?.onError?.({}); options?.onFinish?.({} as never) })
})
afterEach(() => vi.unstubAllGlobals())

describe("canonical schedule mutation owner", () => {
  it("installs a complete response before releasing the writer, without a POST/reload gap", async () => {
    const f = fixture()
    const fetchSpy = vi.fn().mockResolvedValue(response(true, { ...revisionEnvelope(DATE, 4), blocks: [block] }))
    vi.stubGlobal("fetch", fetchSpy)
    const result = await f.api.createBlock(payload)
    expect(f.input.value.schedule.revision).toBe(3)
    expect(f.state.blocks.value).toEqual([block])
    expect(f.state.schedule.value?.revision).toBe(4)
    expect(f.state.phase.value).toBe("idle")
    expect(f.state.capture(DATE)?.revision).toBe(4)
    expect(result.mutation).toMatchObject({ previousBlocks: [], previousRevision: 3, expectedRevision: 4, changed: true, date: DATE })
    expect(JSON.parse(fetchSpy.mock.calls[0][1].body)).toMatchObject({ expected_revision: 3 })
    expect(fetchSpy.mock.calls[0][1].headers["X-Schedule-User"]).toBe("7")
    expect(router.reload).not.toHaveBeenCalled()
  })
  it("permits only one page writer while the request is pending", async () => {
    const f = fixture(); const pending = deferred<ReturnType<typeof response>>()
    const fetchSpy = vi.fn().mockReturnValue(pending.promise); vi.stubGlobal("fetch", fetchSpy)
    const first = f.api.createBlock(payload)
    expect(f.state.phase.value).toBe("saving")
    expect((await f.api.reorderBlocks([])).code).toBe("schedule_synchronizing")
    expect(fetchSpy).toHaveBeenCalledOnce()
    pending.resolve(response(true, { ...revisionEnvelope(DATE, 4), blocks: [block] })); await first
    expect(f.state.busy.value).toBe(false)
  })
  it("retains a no-op/ask snapshot and marks it unchanged", async () => {
    const f = fixture()
    const result = await runScheduleMutation(f.state, DATE, async () => ({ ok: true, data: { ...revisionEnvelope(DATE, 3), blocks: null } }))
    expect(result.mutation?.changed).toBe(false)
    expect(f.state.capture(DATE)?.revision).toBe(3)
    expect(router.reload).not.toHaveBeenCalled()
  })
  it("does not regress canonical blocks when older props arrive", async () => {
    const f = fixture()
    await runScheduleMutation(f.state, DATE, async () => ({ ok: true, data: { ...revisionEnvelope(DATE, 5), blocks: [block] } }))
    f.input.value = { ...f.input.value, schedule: { ...f.input.value.schedule, revision: 4 }, blocks: [] }
    await nextTick()
    expect(f.state.revision.value).toBe(5)
    expect(f.state.blocks.value).toEqual([block])
  })
  it.each([400, 403, 404])("releases a definitely rejected %i write without reconciliation", async (status) => {
    const f = fixture()
    const result = await runScheduleMutation(f.state, DATE, async () => ({ ok: false, status }))
    expect(result.ok).toBe(false); expect(f.state.capture(DATE)?.revision).toBe(3)
    expect(router.reload).not.toHaveBeenCalled()
  })
  it("holds the conflict lease until reload callbacks finish and never retries the POST", async () => {
    const f = fixture(); let reload!: Parameters<typeof router.reload>[0]
    vi.mocked(router.reload).mockImplementation((options) => { reload = options })
    const fetchSpy = vi.fn().mockResolvedValue(response(false, { code: "schedule_changed" }, 409)); vi.stubGlobal("fetch", fetchSpy)
    const pending = f.api.createBlock(payload); await vi.waitFor(() => expect(f.state.phase.value).toBe("conflict"))
    expect((await f.api.deleteBlock(1)).code).toBe("schedule_synchronizing")
    expect(fetchSpy).toHaveBeenCalledOnce()
    f.input.value = { ...f.input.value, schedule: { ...f.input.value.schedule, revision: 4 }, blocks: [block] }
    await nextTick()
    expect(f.state.phase.value).toBe("conflict")
    reload?.onSuccess?.({} as never); reload?.onFinish?.({} as never)
    expect((await pending).code).toBe("schedule_changed")
    expect(f.state.phase.value).toBe("idle"); expect(f.state.blocks.value).toEqual([block])
  })
  it.each([undefined, 500, 200])("reconciles unknown result with status %s and retains the gate on reload failure", async (status) => {
    const f = fixture(); const invalidated = vi.fn(); f.state.subscribeInvalidation(invalidated)
    const result = await runScheduleMutation(f.state, DATE, async () => ({ ok: false, status, errors: { detail: "Lost response" } }))
    expect(result.ok).toBe(false); expect(f.state.phase.value).toBe("synchronizing")
    expect(f.state.capture(DATE)).toBeNull(); expect(invalidated).toHaveBeenCalledWith(DATE, "unknown")
    expect(router.reload).toHaveBeenCalledOnce()
  })
  it("keeps confirmed POST success distinct from failed fallback reload", async () => {
    const f = fixture()
    const result = await runScheduleMutation(f.state, DATE, async () => ({ ok: true, data: { id: 1 } }))
    expect(result).toMatchObject({ ok: true, code: "schedule_sync_failed" })
    expect(result.synchronizationError).toMatch(/Saved/)
    expect(result.mutation).toBeUndefined(); expect(f.state.busy.value).toBe(true)
  })
  it("does not create historical undo metadata from a fallback GET revision", async () => {
    const f = fixture()
    vi.mocked(router.reload).mockImplementation((options) => {
      f.input.value = { ...f.input.value, schedule: { ...f.input.value.schedule, revision: 5 }, blocks: [block] }
      options?.onSuccess?.({} as never); options?.onFinish?.({} as never)
    })
    const result = await runScheduleMutation(f.state, DATE, async () => ({ ok: true, data: { id: 1 } }))
    expect(result).toMatchObject({ ok: true, code: "schedule_reconciled" }); expect(result.mutation).toBeUndefined()
    expect(f.state.capture(DATE)?.revision).toBe(5)
  })
  it("does not label a later external revision as the accepted operation after auxiliary reload", async () => {
    const f = fixture()
    vi.mocked(router.reload).mockImplementation((options) => {
      f.input.value = { ...f.input.value, schedule: { ...f.input.value.schedule, revision: 5 }, blocks: [{ ...block, title: "External" }] }
      options?.onSuccess?.({} as never); options?.onFinish?.({} as never)
    })
    const result = await runScheduleMutation(f.state, DATE, async () => ({ ok: true, data: { ...revisionEnvelope(DATE, 4), blocks: [block] } }), { only: ["review", "schedule", "blocks"] })
    expect(result.ok).toBe(true); expect(result.mutation).toBeUndefined()
    expect(f.state.revision.value).toBe(5)
  })
  it("isolates late responses even after navigating away and back", async () => {
    const f = fixture(); const pending = deferred<{ok: boolean; data: Record<string, unknown>}>()
    const resultPromise = runScheduleMutation(f.state, DATE, () => pending.promise)
    f.input.value = { ...f.input.value, date: OTHER, schedule: { ...f.input.value.schedule, date: OTHER, revision: 8 } }; await nextTick()
    f.input.value = { ...f.input.value, date: DATE, schedule: { ...f.input.value.schedule, date: DATE, revision: 10 } }; await nextTick()
    pending.resolve({ ok: true, data: { ...revisionEnvelope(DATE, 50), blocks: [block] } })
    const result = await resultPromise
    expect(result.mutation).toBeUndefined(); expect(f.state.capture(DATE)?.revision).toBe(10)
    expect(router.reload).not.toHaveBeenCalled()
  })
  it("discards old-user 401 responses without clearing the new user's page", async () => {
    const f = fixture(); const pending = deferred<{ok: boolean; status: number}>()
    const write = runScheduleMutation(f.state, DATE, () => pending.promise)
    f.input.value = { ...f.input.value, user: 8, schedule: { ...f.input.value.schedule, revision: 0 } }; await nextTick()
    pending.resolve({ ok: false, status: 401 }); await write
    expect(f.state.capture(DATE)?.revision).toBe(0)
  })
  it("batches separately replaced auth and schedule props before bootstrapping the new user", async () => {
    const f = fixture(40)
    f.input.value.user = 8
    expect(f.state.begin(DATE)).toBeNull()
    f.input.value.schedule = { ...f.input.value.schedule, revision: 0 }
    await nextTick()
    expect(f.state.capture(DATE)?.revision).toBe(0)
  })
  it("quarantines auth-only props until the new user's schedule object arrives", async () => {
    const f = fixture(40)
    f.input.value.user = 8; await nextTick()
    expect(f.state.capture(DATE)).toBeNull()
    expect(f.state.blocks.value).toEqual([])
    f.input.value.schedule = { ...f.input.value.schedule, revision: 0 }; await nextTick()
    expect(f.state.capture(DATE)?.revision).toBe(0)
  })
  it("clears canonical state and rejects writes on invalid session or logout", async () => {
    const f = fixture()
    await runScheduleMutation(f.state, DATE, async () => ({ ok: false, status: 401, code: "session_invalid" }))
    expect(f.state.schedule.value).toBeNull(); expect(f.state.blocks.value).toEqual([])
    expect(f.state.capture(DATE)).toBeNull()
    expect(router.reload).not.toHaveBeenCalled()
  })
})

describe("app-root write handoff", () => {
  it("holds remounted A after an old return GET and reloads A after the late commit", async () => {
    const f = remountFixture()
    const oldOwner = f.owner
    const post = deferred<{ ok: boolean; data: Record<string, unknown> }>()
    const send = vi.fn(() => post.promise)
    const write = runScheduleMutation(oldOwner, DATE, send)
    await f.navigate(OTHER, 8)
    const newOwner = await f.navigate(DATE, 3)
    expect(newOwner).not.toBe(oldOwner)
    expect(newOwner.capture(DATE)).toBeNull()
    expect(newOwner.phase.value).toBe("synchronizing")
    expect(router.reload).not.toHaveBeenCalled()

    let reload!: Parameters<typeof router.reload>[0]
    vi.mocked(router.reload).mockImplementation((options) => { reload = options })
    post.resolve({ ok: true, data: { ...revisionEnvelope(DATE, 4), blocks: [block] } })
    expect((await write).mutation).toBeUndefined()
    await vi.waitFor(() => expect(router.reload).toHaveBeenCalledOnce())
    expect(newOwner.capture(DATE)).toBeNull()
    f.pageProps.value = { schedule: { id: 1, date: DATE, status: "active", revision: 4 }, blocks: [block] }
    await nextTick()
    reload.onSuccess?.({} as never)
    reload.onFinish?.({} as never)
    await vi.waitFor(() => expect(newOwner.capture(DATE)?.revision).toBe(4))
    expect(newOwner.blocks.value).toEqual([block])
    expect(send).toHaveBeenCalledOnce()
    f.wrapper.unmount()
  })

  it("retains the accepted revision floor when the POST settles before a stale navigation GET remounts A", async () => {
    const f = remountFixture()
    const post = deferred<{ ok: boolean; data: Record<string, unknown> }>()
    const write = runScheduleMutation(f.owner, DATE, () => post.promise)
    post.resolve({ ok: true, data: { ...revisionEnvelope(DATE, 4), blocks: [block] } })
    await write
    expect(f.owner.capture(DATE)?.revision).toBe(4)
    await f.navigate(OTHER, 8)
    const newOwner = await f.navigate(DATE, 3)
    await vi.waitFor(() => expect(router.reload).toHaveBeenCalledOnce())
    expect(newOwner.capture(DATE)).toBeNull()
    f.wrapper.unmount()
  })

  it("does not reload B when A settles, then refreshes A on a stale return visit", async () => {
    const f = remountFixture()
    const post = deferred<{ ok: boolean; data: Record<string, unknown> }>()
    const write = runScheduleMutation(f.owner, DATE, () => post.promise)
    const bOwner = await f.navigate(OTHER, 8)
    post.resolve({ ok: true, data: { ...revisionEnvelope(DATE, 4), blocks: [block] } })
    await write
    expect(bOwner.capture(OTHER)?.revision).toBe(8)
    expect(router.reload).not.toHaveBeenCalled()
    const aOwner = await f.navigate(DATE, 3)
    await vi.waitFor(() => expect(router.reload).toHaveBeenCalledOnce())
    expect(aOwner.capture(DATE)).toBeNull()
    f.wrapper.unmount()
  })

  it("releases a remounted writer after a definitely rejected old write", async () => {
    const f = remountFixture()
    const post = deferred<{ ok: boolean; status: number }>()
    const write = runScheduleMutation(f.owner, DATE, () => post.promise)
    await f.navigate(OTHER, 8)
    const newOwner = await f.navigate(DATE, 3)
    expect(newOwner.capture(DATE)).toBeNull()
    post.resolve({ ok: false, status: 400 })
    await write
    await vi.waitFor(() => expect(newOwner.capture(DATE)?.revision).toBe(3))
    expect(router.reload).not.toHaveBeenCalled()
    f.wrapper.unmount()
  })

  it("keeps the writer gated when a nominally successful reconciliation still returns below the accepted revision", async () => {
    const f = remountFixture()
    const post = deferred<{ ok: boolean; data: Record<string, unknown> }>()
    const write = runScheduleMutation(f.owner, DATE, () => post.promise)
    await f.navigate(OTHER, 8)
    const newOwner = await f.navigate(DATE, 3)
    vi.mocked(router.reload).mockImplementation((options) => {
      options?.onSuccess?.({} as never)
      options?.onFinish?.({} as never)
    })
    post.resolve({ ok: true, data: { ...revisionEnvelope(DATE, 4), blocks: [block] } })
    await write
    await vi.waitFor(() => expect(router.reload).toHaveBeenCalledOnce())
    await nextTick()
    expect(newOwner.phase.value).toBe("synchronizing")
    expect(newOwner.capture(DATE)).toBeNull()
    f.wrapper.unmount()
  })

  it("keeps a remounted writer closed when fresh props arrive before handoff reload finishes", async () => {
    const f = remountFixture()
    const post = deferred<{ ok: boolean; data: Record<string, unknown> }>()
    const write = runScheduleMutation(f.owner, DATE, () => post.promise)
    await f.navigate(OTHER, 8)
    const newOwner = await f.navigate(DATE, 3)
    let reload!: Parameters<typeof router.reload>[0]
    vi.mocked(router.reload).mockImplementation((options) => { reload = options })
    post.resolve({ ok: true, data: { ...revisionEnvelope(DATE, 4), blocks: [block] } })
    await write
    await vi.waitFor(() => expect(router.reload).toHaveBeenCalledOnce())
    f.pageProps.value = { schedule: { id: 1, date: DATE, status: "active", revision: 4 }, blocks: [block] }
    await nextTick()
    expect(newOwner.capture(DATE)).toBeNull()
    expect((await runScheduleMutation(newOwner, DATE, async () => ({ ok: true }))).code).toBe("schedule_synchronizing")
    reload.onSuccess?.({} as never)
    reload.onFinish?.({} as never)
    await vi.waitFor(() => expect(newOwner.capture(DATE)?.revision).toBe(4))
    f.wrapper.unmount()
  })

  it("includes auxiliary review fields when an Analytics write settles after its owner departed", async () => {
    const f = remountFixture()
    const post = deferred<{ ok: boolean; data: Record<string, unknown> }>()
    const write = runScheduleMutation(f.owner, DATE, () => post.promise, { only: ["review", "streak"] })
    await f.navigate(OTHER, 8)
    await f.navigate(DATE, 3)
    vi.mocked(router.reload).mockImplementation(() => {})
    post.resolve({ ok: true, data: { ...revisionEnvelope(DATE, 4), blocks: [block] } })
    await write
    await vi.waitFor(() => expect(router.reload).toHaveBeenCalledOnce())
    expect(vi.mocked(router.reload).mock.calls[0][0]?.only).toEqual(expect.arrayContaining(["schedule", "blocks", "review", "streak"]))
    f.wrapper.unmount()
  })

  it("retains review fields when Analytics commits before a stale return GET remounts it", async () => {
    const f = remountFixture()
    vi.mocked(router.reload).mockImplementation((options) => {
      f.pageProps.value = { schedule: { id: 1, date: DATE, status: "reviewed", revision: 4 }, blocks: [block] }
      options?.onSuccess?.({} as never)
      options?.onFinish?.({} as never)
    })
    await runScheduleMutation(f.owner, DATE,
      async () => ({ ok: true, data: { ...revisionEnvelope(DATE, 4), blocks: [block] } }),
      { only: ["review", "streak"] })
    expect(f.owner.capture(DATE)?.revision).toBe(4)
    await f.navigate(OTHER, 8)
    vi.mocked(router.reload).mockImplementation(() => {})
    const newOwner = await f.navigate(DATE, 3)
    await vi.waitFor(() => expect(router.reload).toHaveBeenCalledTimes(2))
    expect(vi.mocked(router.reload).mock.calls[1][0]?.only).toEqual(expect.arrayContaining(["review", "streak"]))
    expect(newOwner.capture(DATE)).toBeNull()
    f.wrapper.unmount()
  })

  it("does not let a disposed owner clear a newer account's root coordinator", async () => {
    const coordinator = createScheduleWriteCoordinator()
    const input = ref({ date: DATE, user: 7 as number | null,
      schedule: { id: 1, date: DATE, status: "active", revision: 3 } as Schedule })
    const oldOwner = createScheduleRevision(() => input.value.date, () => input.value.schedule,
      { getUserId: () => input.value.user, coordinator })
    const post = deferred<{ ok: boolean; data: Record<string, unknown> }>()
    const write = runScheduleMutation(oldOwner, DATE, () => post.promise)
    oldOwner.reset("dispose")
    input.value.user = 8
    await nextTick()
    const newAccountWrite = coordinator.track(8, DATE)
    post.resolve({ ok: true, data: { ...revisionEnvelope(DATE, 4), blocks: [block] } })
    await write
    expect(coordinator.inspect(8, DATE).pending).toEqual([newAccountWrite.done])
    newAccountWrite.settle("rejected")
  })

  it("reconciles an uncertain departed write and keeps the new writer closed if the read fails", async () => {
    const f = remountFixture()
    const post = deferred<{ ok: boolean; status?: number }>()
    const write = runScheduleMutation(f.owner, DATE, () => post.promise)
    await f.navigate(OTHER, 8)
    const newOwner = await f.navigate(DATE, 3)
    post.resolve({ ok: false, status: 500 })
    await write
    await vi.waitFor(() => expect(router.reload).toHaveBeenCalledOnce())
    expect(newOwner.capture(DATE)).toBeNull()
    expect(newOwner.phase.value).toBe("synchronizing")
    f.wrapper.unmount()
  })

  it("drops old session tickets so a later same-user page cannot inherit them", async () => {
    const f = remountFixture()
    const post = deferred<{ ok: boolean; data: Record<string, unknown> }>()
    const write = runScheduleMutation(f.owner, DATE, () => post.promise)
    await f.navigate(OTHER, 8)
    f.coordinator.clear()
    const newOwner = await f.navigate(DATE, 3)
    expect(newOwner.capture(DATE)?.revision).toBe(3)
    post.resolve({ ok: true, data: { ...revisionEnvelope(DATE, 4), blocks: [block] } })
    await write
    expect(newOwner.capture(DATE)?.revision).toBe(3)
    expect(router.reload).not.toHaveBeenCalled()
    f.wrapper.unmount()
  })
})

describe("timezone context reconciliation", () => {
  it("waits for an old write before reading and keeps the gate until that read is accepted", async () => {
    const f = contextFixture()
    const oldWrite = deferred<{ ok: boolean; data: Record<string, unknown> }>()
    const write = runScheduleMutation(f.state, DATE, () => oldWrite.promise)
    let reload!: Parameters<typeof router.reload>[0]
    vi.mocked(router.reload).mockImplementation((options) => { reload = options })

    f.input.value.zone = "Asia/Qatar"
    await nextTick()
    expect(f.state.phase.value).toBe("synchronizing")
    expect(f.state.capture(DATE)).toBeNull()
    expect(router.reload).not.toHaveBeenCalled()

    // A fresh-looking props object may arrive before the old POST commits.
    f.input.value.schedule = { ...f.input.value.schedule, revision: 3 }
    await nextTick()
    expect(f.state.capture(DATE)).toBeNull()

    oldWrite.resolve({ ok: true, data: { ...revisionEnvelope(DATE, 4), blocks: [block] } })
    expect((await write).mutation).toBeUndefined()
    await vi.waitFor(() => expect(router.reload).toHaveBeenCalledOnce())
    expect(f.state.capture(DATE)).toBeNull()

    f.input.value.schedule = { ...f.input.value.schedule, revision: 4 }
    f.input.value.blocks = [block]
    await nextTick()
    expect(f.state.capture(DATE)).toBeNull()
    reload.onSuccess?.({} as never)
    reload.onFinish?.({} as never)
    await vi.waitFor(() => expect(f.state.phase.value).toBe("idle"))
    expect(f.state.capture(DATE)?.revision).toBe(4)
    expect(f.state.blocks.value).toEqual([block])
  })

  it("invalidates the first context read across an A-B-A switch", async () => {
    const f = contextFixture()
    const oldWrite = deferred<{ ok: boolean; data: Record<string, unknown> }>()
    const write = runScheduleMutation(f.state, DATE, () => oldWrite.promise)
    const reloads: Parameters<typeof router.reload>[0][] = []
    vi.mocked(router.reload).mockImplementation((options) => { reloads.push(options) })
    f.input.value.zone = "Asia/Qatar"
    await nextTick()
    f.input.value.zone = "UTC"
    await nextTick()
    oldWrite.resolve({ ok: true, data: { ...revisionEnvelope(DATE, 4), blocks: [block] } })
    await write
    await vi.waitFor(() => expect(reloads).toHaveLength(1))
    f.input.value.schedule = { ...f.input.value.schedule, revision: 4 }
    f.input.value.blocks = [block]
    await nextTick()
    reloads[0].onSuccess?.({} as never)
    reloads[0].onFinish?.({} as never)
    await vi.waitFor(() => expect(f.state.capture(DATE)?.revision).toBe(4))
  })

  it("keeps the context gate on read failure but lets a new date bootstrap", async () => {
    const f = contextFixture()
    vi.mocked(router.reload).mockImplementation((options) => {
      options?.onError?.({})
      options?.onFinish?.({} as never)
    })
    f.input.value.zone = "Asia/Qatar"
    await vi.waitFor(() => expect(router.reload).toHaveBeenCalledOnce())
    expect(f.state.capture(DATE)).toBeNull()
    f.input.value = { ...f.input.value, date: OTHER,
      schedule: { ...f.input.value.schedule, date: OTHER, revision: 0 }, blocks: [] }
    await nextTick()
    expect(f.state.capture(OTHER)?.revision).toBe(0)
  })

  it("does not carry an old user's pending-write gate into the new account", async () => {
    const f = contextFixture()
    const oldWrite = deferred<{ ok: boolean; data: Record<string, unknown> }>()
    const write = runScheduleMutation(f.state, DATE, () => oldWrite.promise)
    f.input.value.zone = "Asia/Qatar"
    await nextTick()
    expect(f.state.capture(DATE)).toBeNull()
    f.input.value = { ...f.input.value, user: 8,
      schedule: { ...f.input.value.schedule, revision: 0 }, blocks: [] }
    await nextTick()
    expect(f.state.capture(DATE)?.revision).toBe(0)
    expect(router.reload).not.toHaveBeenCalled()
    oldWrite.resolve({ ok: true, data: { ...revisionEnvelope(DATE, 4), blocks: [block] } })
    await write
    expect(f.state.capture(DATE)?.revision).toBe(0)
  })
})

describe("historical undo chain", () => {
  it("sends historical expected_revision and rebases only the contiguous A→B→undo B→undo A chain", async () => {
    const f = fixture(0); const { undo, wrapper } = mountUndo(f)
    const fetchSpy = vi.fn()
      .mockResolvedValueOnce(response(true, { ...revisionEnvelope(DATE, 1), blocks: [block] }))
      .mockResolvedValueOnce(response(true, { ...revisionEnvelope(DATE, 2), blocks: [{ ...block, title: "B" }] }))
      .mockResolvedValueOnce(response(true, { ...revisionEnvelope(DATE, 3), blocks: [{ ...block, id: 2 }] }))
      .mockResolvedValueOnce(response(true, { ...revisionEnvelope(DATE, 4), blocks: [] }))
    vi.stubGlobal("fetch", fetchSpy)
    const a = (await f.api.createBlock(payload)).mutation!
    undo.pushUndo({ description: "A", type: "add", previousBlocks: a.previousBlocks, scheduleDate: DATE, previous_revision: a.previousRevision, expected_revision: a.expectedRevision })
    const b = (await f.api.updateBlock(1, { title: "B" })).mutation!
    undo.pushUndo({ description: "B", type: "edit", previousBlocks: b.previousBlocks, scheduleDate: DATE, previous_revision: b.previousRevision, expected_revision: b.expectedRevision })
    await undo.performUndo()
    expect(undo.undoStack.value).toHaveLength(1)
    expect(undo.undoStack.value[0].expected_revision).toBe(3)
    expect(undo.undoStack.value[0].previous_revision).toBe(0)
    await undo.performUndo()
    expect(undo.undoStack.value).toHaveLength(0)
    expect(fetchSpy.mock.calls.map((call) => JSON.parse(call[1].body).expected_revision)).toEqual([0, 1, 2, 3])
    wrapper.unmount()
  })
  it("clears old history on a new external revision instead of rebasing from GET", async () => {
    const f = fixture(); const { undo, wrapper } = mountUndo(f)
    undo.pushUndo({ description: "Local", type: "add", previousBlocks: [], scheduleDate: DATE, previous_revision: 2, expected_revision: 3 })
    f.input.value = { ...f.input.value, schedule: { ...f.input.value.schedule, revision: 4 }, blocks: [block] }; await nextTick()
    expect(undo.canUndo.value).toBe(false)
    expect(undo.undoStack.value).toHaveLength(0)
    wrapper.unmount()
  })
  it("invalidates history on unknown write result even when fresh GET has the same revision", async () => {
    const f = fixture(); const { undo, wrapper } = mountUndo(f)
    undo.pushUndo({ description: "Local", type: "add", previousBlocks: [], scheduleDate: DATE, previous_revision: 2, expected_revision: 3 })
    vi.mocked(router.reload).mockImplementation((options) => {
      f.input.value = { ...f.input.value, schedule: { ...f.input.value.schedule } }
      options?.onSuccess?.({} as never); options?.onFinish?.({} as never)
    })
    await runScheduleMutation(f.state, DATE, async () => ({ ok: false }))
    expect(undo.undoStack.value).toHaveLength(0)
    expect(f.state.capture(DATE)?.revision).toBe(3)
    wrapper.unmount()
  })
  it("does not retry a historical restore against the latest revision", async () => {
    const f = fixture(); const { undo, wrapper } = mountUndo(f)
    undo.pushUndo({ description: "Local", type: "add", previousBlocks: [], scheduleDate: DATE, previous_revision: 2, expected_revision: 3 })
    await runScheduleMutation(f.state, DATE, async () => ({ ok: true, data: { ...revisionEnvelope(DATE, 4), blocks: [block] } }))
    const fetchSpy = vi.fn(); vi.stubGlobal("fetch", fetchSpy)
    await undo.performUndo()
    expect(fetchSpy).not.toHaveBeenCalled()
    expect(undo.undoStack.value).toHaveLength(0)
    wrapper.unmount()
  })
  it("keeps new-user history and toast when an old undo resolves after an account switch", async () => {
    const f = fixture(); const { undo, wrapper } = mountUndo(f)
    undo.pushUndo({ description: "Old AI", type: "ai", previousBlocks: [], scheduleDate: DATE, previous_revision: 2, expected_revision: 3 })
    const pending = deferred<ReturnType<typeof response>>()
    vi.stubGlobal("fetch", vi.fn().mockReturnValue(pending.promise))
    const restore = undo.performUndo()
    f.input.value = { ...f.input.value, user: 8, schedule: { ...f.input.value.schedule, revision: 1 } }; await nextTick()
    undo.pushUndo({ description: "New user edit", type: "add", previousBlocks: [], scheduleDate: DATE, previous_revision: 0, expected_revision: 1 })
    pending.resolve(response(true, { ...revisionEnvelope(DATE, 4), blocks: [] }))
    await restore
    expect(undo.undoStack.value.map((action) => action.description)).toEqual(["New user edit"])
    expect(undo.currentToast.value?.description).toBe("New user edit")
    wrapper.unmount()
  })
  it("rejects confirmed metadata delivered after a same-date user change with the same revision", async () => {
    const f = fixture(); const { undo, wrapper } = mountUndo(f)
    const old = f.state.capture(DATE)!
    f.input.value = { ...f.input.value, user: 8, schedule: { ...f.input.value.schedule } }; await nextTick()
    undo.pushUndo({ description: "Old result", type: "add", previousBlocks: [], scheduleDate: DATE,
      previous_revision: 2, expected_revision: 3, generation: old.generation })
    expect(undo.undoStack.value).toHaveLength(0)
    wrapper.unmount()
  })
  it("rejects actions with missing historical revision instead of filling it from the current page", () => {
    const f = fixture(); const { undo, wrapper } = mountUndo(f)
    undo.pushUndo({ description: "Unsafe", type: "add", previousBlocks: [], scheduleDate: DATE } as never)
    expect(undo.undoStack.value).toHaveLength(0)
    wrapper.unmount()
  })
  it("clears all dates' history on user/session cleanup", () => {
    const f = fixture(); const { undo, wrapper } = mountUndo(f)
    undo.pushUndo({ description: "Local", type: "add", previousBlocks: [], scheduleDate: DATE, previous_revision: 2, expected_revision: 3 })
    f.state.reset("session")
    expect(undo.undoStack.value).toHaveLength(0); expect(undo.currentToast.value).toBeNull()
    wrapper.unmount()
  })
})
