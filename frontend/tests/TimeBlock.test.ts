import { describe, it, expect, vi, beforeEach } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import { ref } from "vue"

// Mock useSchedule
const mockUpdateBlock = vi.fn()
const mockDeleteBlock = vi.fn()
vi.mock("../src/composables/useSchedule", () => ({
  useSchedule: () => ({
    updateBlock: mockUpdateBlock,
    deleteBlock: mockDeleteBlock,
  }),
}))

// TimeBlock now uses useActiveTheme, which reads usePage().props.
// Default to Classic for the existing tests; the dedicated theme
// reactivity test file exercises the reactive path explicitly.
vi.mock("@inertiajs/vue3", () => ({
  usePage: () => ({ props: { ui_preferences: { theme: "classic" } } }),
}))

import TimeBlock from "../src/components/TimeBlock.vue"
import type { TimeBlock as TimeBlockType } from "../src/types"

function makeBlock(overrides: Partial<TimeBlockType> = {}): TimeBlockType {
  return {
    id: 1,
    title: "Test Block",
    start_time: "09:00",
    end_time: "10:00",
    category: "work",
    is_completed: false,
    sort_order: 0,
    ...overrides,
  }
}

const mockPushUndo = vi.fn()
const mockSnapshotBlocks = vi.fn(() => [makeBlock()])

function mountWithProvide(props: {
  block: TimeBlockType
  date: string
  isCurrent?: boolean
  remainingMinutes?: number | null
}) {
  return mount(TimeBlock, {
    props,
    global: {
      provide: {
        undo: { pushUndo: mockPushUndo, snapshotBlocks: mockSnapshotBlocks },
        drag: {
          startDrag: vi.fn(),
          isDragging: ref(false),
          dragBlockId: ref(null),
          shiftedBlockIds: ref(new Set()),
        },
        scheduleContainer: ref(null),
      },
    },
  })
}

describe("TimeBlock", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUpdateBlock.mockReset()
    mockDeleteBlock.mockReset()
  })

  it("renders block title and times", () => {
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    expect(wrapper.text()).toContain("Test Block")
    expect(wrapper.text()).toContain("09:00")
    expect(wrapper.text()).toContain("10:00")
  })

  it("computes duration correctly", () => {
    const wrapper = mountWithProvide({ block: makeBlock({ start_time: "09:00", end_time: "10:30" }), date: "2026-04-10" })
    expect(wrapper.text()).toContain("1h 30m")
  })

  it("formats whole-hour durations without trailing minutes", () => {
    const oneHour = mountWithProvide({
      block: makeBlock({ start_time: "09:00", end_time: "10:00" }),
      date: "2026-04-10",
    })
    expect(oneHour.find(".duration").text()).toBe("1h")

    const twoHours = mountWithProvide({
      block: makeBlock({ start_time: "09:00", end_time: "11:00" }),
      date: "2026-04-10",
    })
    expect(twoHours.find(".duration").text()).toBe("2h")
  })

  it("keeps compact 30-minute blocks in compact layout", () => {
    const wrapper = mountWithProvide({
      block: makeBlock({ start_time: "09:00", end_time: "09:30" }),
      date: "2026-04-10",
    })
    expect(wrapper.find(".time-block").classes()).toContain("compact")
    expect(wrapper.find(".duration").exists()).toBe(false)
  })

  it("shows remaining time on an active compact block", () => {
    const wrapper = mountWithProvide({
      block: makeBlock({ start_time: "09:00", end_time: "09:30" }),
      date: "2026-04-10",
      isCurrent: true,
      remainingMinutes: 23,
    })

    expect(wrapper.find(".remaining-badge").text()).toBe("23m left")
  })

  it("shows remaining time on an active expanded block while preserving total duration", () => {
    const wrapper = mountWithProvide({
      block: makeBlock({ start_time: "09:00", end_time: "10:30" }),
      date: "2026-04-10",
      isCurrent: true,
      remainingMinutes: 60,
    })

    expect(wrapper.find(".duration").text()).toBe("1h 30m")
    expect(wrapper.find(".remaining-badge").text()).toBe("1h left")
  })

  it("omits remaining time for inactive blocks", () => {
    const wrapper = mountWithProvide({
      block: makeBlock(),
      date: "2026-04-10",
      isCurrent: false,
      remainingMinutes: 23,
    })

    expect(wrapper.find(".remaining-badge").exists()).toBe(false)
  })

  it("toggles completion on checkbox change", async () => {
    mockUpdateBlock.mockResolvedValue({ ok: true })
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    expect(mockUpdateBlock).toHaveBeenCalledWith(
      1,
      { is_completed: true },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
  })

  it("checkbox flips immediately on click before PATCH resolves", async () => {
    let resolveUpdate: (v: { ok: boolean }) => void = () => {}
    mockUpdateBlock.mockReturnValueOnce(
      new Promise<{ ok: boolean }>((res) => {
        resolveUpdate = res
      }),
    )
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    // Optimistic: checkbox reflects the new value before the PATCH resolves,
    // and shows the saving state while the request is in flight.
    expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.find(".time-block").classes()).toContain("completed")
    expect(wrapper.find(".checkbox").classes()).toContain("saving")
    resolveUpdate({ ok: true })
    await flushPromises()
    expect(mockPushUndo).toHaveBeenCalledTimes(1)
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "toggle", silent: true }),
    )
    expect(wrapper.text()).not.toContain("Failed to update")
  })

  it("retries on failure and succeeds on a later attempt", async () => {
    vi.useFakeTimers()
    try {
      mockUpdateBlock
        .mockResolvedValueOnce({ ok: false })
        .mockResolvedValueOnce({ ok: false })
        .mockResolvedValueOnce({ ok: true })
      const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
      await wrapper.find(".checkbox").trigger("change")
      await flushPromises()
      // After attempt 1 fails, checkbox stays flipped and saving class is present.
      expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(true)
      expect(wrapper.find(".checkbox").classes()).toContain("saving")
      expect(wrapper.text()).not.toContain("Failed to update")

      await vi.advanceTimersByTimeAsync(300)
      await flushPromises()
      await vi.advanceTimersByTimeAsync(1000)
      await flushPromises()

      expect(mockUpdateBlock).toHaveBeenCalledTimes(3)
      expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(true)
      expect(wrapper.find(".checkbox").classes()).not.toContain("saving")
      expect(wrapper.text()).not.toContain("Failed to update")
      expect(mockPushUndo).toHaveBeenCalledTimes(1)
    } finally {
      vi.useRealTimers()
    }
  })

  it("shows error when toggle fails", async () => {
    vi.useFakeTimers()
    try {
      mockUpdateBlock.mockResolvedValue({ ok: false })
      const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
      await wrapper.find(".checkbox").trigger("change")
      await flushPromises()
      // Mid-chain: stay flipped, no error yet.
      expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(true)
      expect(wrapper.text()).not.toContain("Failed to update")

      // Full backoff: 300 + 1000 + 3000 = 4300 ms across 4 attempts.
      await vi.advanceTimersByTimeAsync(4300)
      await flushPromises()

      expect(mockUpdateBlock).toHaveBeenCalledTimes(4)
      expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(false)
      expect(wrapper.text()).toContain("Failed to update")
      expect(wrapper.find(".checkbox").classes()).not.toContain("saving")
      expect(mockPushUndo).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it("a second click aborts the in-flight chain and targets the newest value", async () => {
    vi.useFakeTimers()
    try {
      // Chain 1 attempt 1 fails → parks in sleep(300). Chain 2 succeeds on attempt 1.
      mockUpdateBlock
        .mockResolvedValueOnce({ ok: false })
        .mockResolvedValueOnce({ ok: true })
      const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })

      // 1. Chain 1: optimistic → true
      await wrapper.find(".checkbox").trigger("change")
      // 2. Let attempt-1 resolve {ok:false} and park in sleep(300)
      await flushPromises()
      expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(true)

      // 3. Mid-sleep: second click starts chain 2 (optimistic → false), supersedes chain 1
      await wrapper.find(".checkbox").trigger("change")
      expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(false)

      // 4. Chain 2's attempt-1 resolves {ok:true}
      await flushPromises()
      expect(mockPushUndo).toHaveBeenCalledTimes(1)
      expect(wrapper.find(".checkbox").classes()).not.toContain("saving")
      expect(wrapper.text()).not.toContain("Failed to update")

      // 5. Chain 1's sleep(300) resolves; post-sleep guard must bail silently
      await vi.advanceTimersByTimeAsync(300)
      await flushPromises()
      expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(false)
      expect(mockPushUndo).toHaveBeenCalledTimes(1)
      expect(wrapper.text()).not.toContain("Failed to update")
    } finally {
      vi.useRealTimers()
    }
  })

  it("aborts an in-flight PATCH on re-toggle so a late success cannot pushUndo", async () => {
    // Signal-aware mock: pending promise rejects AbortError when signal aborts.
    mockUpdateBlock.mockImplementation(
      (
        _id: number,
        _data: Record<string, unknown>,
        options?: { signal?: AbortSignal },
      ) =>
        new Promise<{ ok: boolean }>((resolve, reject) => {
          const signal = options?.signal
          if (signal?.aborted) {
            reject(new DOMException("Aborted", "AbortError"))
            return
          }
          const onAbort = () => reject(new DOMException("Aborted", "AbortError"))
          signal?.addEventListener("abort", onAbort, { once: true })
          // First call stays pending until aborted; second resolves ok.
          if (mockUpdateBlock.mock.calls.length === 1) {
            // leave pending — aborted by second click
            return
          }
          signal?.removeEventListener("abort", onAbort)
          resolve({ ok: true })
        }),
    )
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(true)

    await wrapper.find(".checkbox").trigger("change")
    expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(false)
    await flushPromises()

    expect(mockPushUndo).toHaveBeenCalledTimes(1)
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "toggle", silent: true }),
    )
    expect(wrapper.text()).not.toContain("Failed to update")
    expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(false)
  })

  it("reverts to completed when uncheck exhausts all retries", async () => {
    vi.useFakeTimers()
    try {
      mockUpdateBlock.mockResolvedValue({ ok: false })
      const wrapper = mountWithProvide({
        block: makeBlock({ is_completed: true }),
        date: "2026-04-10",
      })
      await wrapper.find(".checkbox").trigger("change")
      await flushPromises()
      expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(false)

      await vi.advanceTimersByTimeAsync(4300)
      await flushPromises()

      expect(mockUpdateBlock).toHaveBeenCalledTimes(4)
      expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(true)
      expect(wrapper.find(".title-completed").exists()).toBe(true)
      expect(wrapper.text()).toContain("Failed to update")
      expect(mockPushUndo).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it("skips undo when unmounted mid-flight", async () => {
    // The onUnmounted hook aborts the in-flight PATCH and
    // bumps generation so a late resolve cannot pushUndo/revert/error
    // into a destroyed component. A pending PATCH that resolves ok after
    // unmount must hit the post-resolve generation guard and bail.
    let resolveUpdate: (v: { ok: boolean }) => void = () => {}
    mockUpdateBlock.mockReturnValueOnce(
      new Promise<{ ok: boolean }>((res) => {
        resolveUpdate = res
      }),
    )
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    // Unmount while the PATCH is still pending.
    wrapper.unmount()
    // Late success must not pushUndo (generation bumped on unmount).
    resolveUpdate({ ok: true })
    await flushPromises()
    expect(mockPushUndo).not.toHaveBeenCalled()
  })

  it("reverts to the live reloaded prop, not the pre-toggle value, after exhausting retries", async () => {
    // A mid-chain router.reload can change props.block.is_completed
    // before the failure revert fires. The revert reads the live prop,
    // not a serverValue captured when the toggle started — a regression
    // to the captured value would clobber a server-applied change here.
    vi.useFakeTimers()
    try {
      mockUpdateBlock.mockResolvedValue({ ok: false })
      const wrapper = mountWithProvide({
        block: makeBlock({ is_completed: false }),
        date: "2026-04-10",
      })
      // Toggle check → optimistic true; every attempt fails.
      await wrapper.find(".checkbox").trigger("change")
      await flushPromises()
      // Server actually applied the change; a reload lands mid-retry.
      await wrapper.setProps({ block: makeBlock({ is_completed: true }) })

      await vi.advanceTimersByTimeAsync(4300)
      await flushPromises()

      expect(mockUpdateBlock).toHaveBeenCalledTimes(4)
      // Revert reads the live prop (true), not captured serverValue (false).
      expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(true)
      expect(wrapper.text()).toContain("Failed to update")
      expect(mockPushUndo).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it("aborts and re-aligns to the new block when the row is reused for a different block", async () => {
    // Schedule.vue keys rows by index, so this instance can be reassigned to
    // a different block mid-retry. On id change the chain aborts (never PATCHes
    // the swapped-in id) and all local UI state re-aligns to the new block — no
    // stuck optimistic checked / saving spinner on the wrong row.
    vi.useFakeTimers()
    try {
      mockUpdateBlock.mockResolvedValue({ ok: false })
      const wrapper = mountWithProvide({
        block: makeBlock({ id: 1, is_completed: false }),
        date: "2026-04-10",
      })
      await wrapper.find(".checkbox").trigger("change") // optimistic check on block 1
      await flushPromises()
      expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(true)
      expect(wrapper.find(".checkbox").classes()).toContain("saving")

      // Instance reused for a different, not-completed block.
      await wrapper.setProps({ block: makeBlock({ id: 99, is_completed: false }) })

      await vi.advanceTimersByTimeAsync(4300)
      await flushPromises()

      // Never PATCHed the swapped-in block; UI re-aligned to the new block;
      // no error or undo leaked onto the wrong row.
      for (const call of mockUpdateBlock.mock.calls) {
        expect(call[0]).toBe(1)
      }
      expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(false)
      expect(wrapper.find(".checkbox").classes()).not.toContain("saving")
      expect(wrapper.text()).not.toContain("Failed to update")
      expect(mockPushUndo).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it("does not clobber a newer optimistic value when an older reload lands mid-flight", async () => {
    // With a chain in flight (saving), an older chain's success reload can flip
    // props.block.is_completed. The saving-guarded watcher must keep the newer
    // optimistic value rather than snapping the checkbox to the stale prop.
    mockUpdateBlock.mockReturnValue(new Promise<{ ok: boolean }>(() => {}))
    const wrapper = mountWithProvide({
      block: makeBlock({ id: 1, is_completed: false }),
      date: "2026-04-10",
    })
    await wrapper.find(".checkbox").trigger("change") // optimistic check, chain 1 pending
    await wrapper.find(".checkbox").trigger("change") // optimistic uncheck, chain 2 pending (saving)
    expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(false)
    // Older chain's reload flips the prop true mid-flight (same block id).
    await wrapper.setProps({ block: makeBlock({ id: 1, is_completed: true }) })
    // Guard preserves the newer optimistic uncheck.
    expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(false)
  })

  it("disables the checkbox while the schedule is disabled", async () => {
    // scheduleDisabled (provided by Schedule.vue during AI processing) must
    // natively disable the checkbox — otherwise a click flips the native
    // control with no reactive change, re-creating the desync it guards against.
    const wrapper = mount(TimeBlock, {
      props: { block: makeBlock(), date: "2026-04-10" },
      global: {
        provide: {
          undo: { pushUndo: mockPushUndo, snapshotBlocks: mockSnapshotBlocks },
          drag: {
            startDrag: vi.fn(),
            isDragging: ref(false),
            dragBlockId: ref(null),
            shiftedBlockIds: ref(new Set()),
          },
          scheduleContainer: ref(null),
          scheduleDisabled: ref(true),
        },
      },
    })
    expect((wrapper.find(".checkbox").element as HTMLInputElement).disabled).toBe(true)
    await wrapper.find(".checkbox").trigger("change")
    expect(mockUpdateBlock).not.toHaveBeenCalled()
  })

  it("disables the compact-layout checkbox while the schedule is disabled", async () => {
    // The compact (<=30m) branch renders a separate <input>; assert it also
    // carries the native disabled state (both branches bind :disabled="disabled").
    const wrapper = mount(TimeBlock, {
      props: {
        block: makeBlock({ start_time: "09:00", end_time: "09:25" }),
        date: "2026-04-10",
      },
      global: {
        provide: {
          undo: { pushUndo: mockPushUndo, snapshotBlocks: mockSnapshotBlocks },
          drag: {
            startDrag: vi.fn(),
            isDragging: ref(false),
            dragBlockId: ref(null),
            shiftedBlockIds: ref(new Set()),
          },
          scheduleContainer: ref(null),
          scheduleDisabled: ref(true),
        },
      },
    })
    expect(wrapper.find(".time-block").classes()).toContain("compact")
    expect((wrapper.find(".checkbox").element as HTMLInputElement).disabled).toBe(true)
    await wrapper.find(".checkbox").trigger("change")
    expect(mockUpdateBlock).not.toHaveBeenCalled()
  })

  it("labels a rapid re-toggle by the written value, not a stale prop", async () => {
    // unchecked → check (in-flight) → uncheck before any reload. The second
    // chain writes is_completed:false, so the undo label must be "Unchecked"
    // even though props.block.is_completed still reads false.
    let resolveFirst: (v: { ok: boolean }) => void = () => {}
    mockUpdateBlock
      .mockReturnValueOnce(
        new Promise<{ ok: boolean }>((res) => {
          resolveFirst = res
        }),
      )
      .mockResolvedValueOnce({ ok: true })
    const wrapper = mountWithProvide({
      block: makeBlock({ is_completed: false }),
      date: "2026-04-10",
    })
    await wrapper.find(".checkbox").trigger("change") // toggle 1: optimistic check
    await wrapper.find(".checkbox").trigger("change") // toggle 2: optimistic uncheck, supersedes
    await flushPromises() // chain 2 resolves ok → pushUndo "Unchecked"
    resolveFirst({ ok: true }) // chain 1's late success must bail (superseded)
    await flushPromises()
    expect(mockPushUndo).toHaveBeenCalledTimes(1)
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "toggle", description: 'Unchecked "Test Block"' }),
    )
  })

  it("reverts and clears saving when a non-abort error rejects the PATCH", async () => {
    // useHttp reads the response body outside its try/catch, so a disrupted
    // read rejects with a non-AbortError. That must be treated as a failed
    // attempt — retried, then reverted — never a stuck spinner / desync.
    vi.useFakeTimers()
    try {
      mockUpdateBlock.mockRejectedValue(new TypeError("network died mid-body"))
      const wrapper = mountWithProvide({
        block: makeBlock({ is_completed: false }),
        date: "2026-04-10",
      })
      await wrapper.find(".checkbox").trigger("change")
      await flushPromises()
      await vi.advanceTimersByTimeAsync(4300)
      await flushPromises()

      expect(mockUpdateBlock).toHaveBeenCalledTimes(4)
      expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(false)
      expect(wrapper.find(".checkbox").classes()).not.toContain("saving")
      expect(wrapper.text()).toContain("Failed to update")
      expect(mockPushUndo).not.toHaveBeenCalled()
    } finally {
      vi.useRealTimers()
    }
  })

  it("toggles completion on the compact-layout checkbox", async () => {
    // The compact (<=30m) and expanded branches render separate <input>s;
    // exercise the compact one so a regression in either branch is caught.
    mockUpdateBlock.mockResolvedValue({ ok: true })
    const wrapper = mountWithProvide({
      block: makeBlock({ start_time: "09:00", end_time: "09:30" }),
      date: "2026-04-10",
    })
    expect(wrapper.find(".time-block").classes()).toContain("compact")
    await wrapper.find(".checkbox").trigger("change")
    expect(mockUpdateBlock).toHaveBeenCalledWith(
      1,
      { is_completed: true },
      expect.objectContaining({ signal: expect.any(AbortSignal) }),
    )
    await flushPromises()
    expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(true)
  })

  it("enters edit mode on title click", async () => {
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    expect(wrapper.find(".title-input").exists()).toBe(false)
    await wrapper.find(".title").trigger("click")
    expect(wrapper.find(".title-input").exists()).toBe(true)
    expect((wrapper.find(".title-input").element as HTMLInputElement).value).toBe("Test Block")
  })

  it("saves title on enter and exits edit mode", async () => {
    mockUpdateBlock.mockResolvedValue({ ok: true })
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".title").trigger("click")
    const input = wrapper.find(".title-input")
    await input.setValue("New Title")
    await input.trigger("keydown.enter")
    expect(mockUpdateBlock).toHaveBeenCalledWith(1, { title: "New Title" })
  })

  it("does not double-save when blur fires after enter", async () => {
    // Regression for the ``@keydown.enter`` + ``@blur`` race. Both
    // bind to ``saveTitle``. Pressing Enter eventually unmounts the
    // input which fires blur, triggering a second invocation. Without
    // taking ``editing`` down BEFORE the network await, that second
    // call could proceed all the way to a duplicate PATCH + duplicate
    // undo entry.
    //
    // The end-to-end variant of this test lives at
    // frontend/scripts/playwright/timeblock-double-save.mjs — it caught
    // a sibling-bug that this unit test alone missed (a guard that
    // worked for concurrent re-entry but not for sequential re-entry
    // through a finally-cleared flag). Keep both: the unit test pins
    // the contract; the e2e script pins the real-browser timing.
    let resolveFirst: (v: { ok: boolean }) => void = () => {}
    mockUpdateBlock.mockReturnValueOnce(
      new Promise<{ ok: boolean }>((res) => {
        resolveFirst = res
      }),
    )
    const wrapper = mountWithProvide({
      block: makeBlock(),
      date: "2026-04-10",
    })
    await wrapper.find(".title").trigger("click")
    const input = wrapper.find(".title-input")
    await input.setValue("New Title")
    await input.trigger("keydown.enter")
    await input.trigger("blur")
    resolveFirst({ ok: true })
    await flushPromises()
    expect(mockUpdateBlock).toHaveBeenCalledTimes(1)
    expect(mockPushUndo).toHaveBeenCalledTimes(1)
  })

  it("cancels editing on escape without saving", async () => {
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".title").trigger("click")
    await wrapper.find(".title-input").trigger("keydown.escape")
    expect(wrapper.find(".title-input").exists()).toBe(false)
    expect(mockUpdateBlock).not.toHaveBeenCalled()
  })

  it("does not save if title unchanged", async () => {
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".title").trigger("click")
    await wrapper.find(".title-input").trigger("keydown.enter")
    expect(mockUpdateBlock).not.toHaveBeenCalled()
  })

  it("calls delete after confirm", async () => {
    mockDeleteBlock.mockResolvedValue({ ok: true })
    vi.spyOn(window, "confirm").mockReturnValue(true)
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".delete-btn").trigger("click")
    expect(mockDeleteBlock).toHaveBeenCalledWith(1)
  })

  it("does not delete if confirm cancelled", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false)
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".delete-btn").trigger("click")
    expect(mockDeleteBlock).not.toHaveBeenCalled()
  })

  it("shows completed styling", () => {
    const wrapper = mountWithProvide({ block: makeBlock({ is_completed: true }), date: "2026-04-10" })
    expect(wrapper.find(".time-block").classes()).toContain("completed")
    expect(wrapper.find(".title-completed").exists()).toBe(true)
  })

  it("shows error on failed title update", async () => {
    mockUpdateBlock.mockResolvedValue({ ok: false })
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".title").trigger("click")
    await wrapper.find(".title-input").setValue("Changed")
    await wrapper.find(".title-input").trigger("keydown.enter")
    await vi.dynamicImportSettled()
    expect(wrapper.text()).toContain("Failed to update title")
    // Failure path re-opens the input so the user can retry without
    // losing their typed value (paired with ``editing.value = true``
    // on the failure branch in saveTitle).
    expect(wrapper.find(".title-input").exists()).toBe(true)
  })

  it("renders drag handle", () => {
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    expect(wrapper.find(".drag-handle").exists()).toBe(true)
  })

  it("pushUndo called on successful title save", async () => {
    mockUpdateBlock.mockResolvedValue({ ok: true })
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".title").trigger("click")
    await wrapper.find(".title-input").setValue("New Title")
    await wrapper.find(".title-input").trigger("keydown.enter")
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "edit", silent: true }),
    )
  })

  it("pushUndo called on successful toggle", async () => {
    mockUpdateBlock.mockResolvedValue({ ok: true })
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "toggle", silent: true }),
    )
  })

  it("pushUndo called on successful delete", async () => {
    mockDeleteBlock.mockResolvedValue({ ok: true })
    vi.spyOn(window, "confirm").mockReturnValue(true)
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".delete-btn").trigger("click")
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "delete", silent: true }),
    )
  })

  it("pushUndo NOT called on failed update", async () => {
    mockUpdateBlock.mockResolvedValue({ ok: false })
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".title").trigger("click")
    await wrapper.find(".title-input").setValue("New")
    await wrapper.find(".title-input").trigger("keydown.enter")
    await vi.dynamicImportSettled()
    expect(mockPushUndo).not.toHaveBeenCalled()
  })

  // Issue #21: if the user navigates to a different date while a
  // mutation is in flight, the undo entry must still restore to the
  // date the mutation started on, not whatever ``props.date`` happens
  // to read at pushUndo time.

  it("toggle binds scheduleDate to the date active when the request started (issue #21)", async () => {
    let resolveUpdate: (v: { ok: boolean }) => void = () => {}
    mockUpdateBlock.mockReturnValueOnce(
      new Promise<{ ok: boolean }>((res) => {
        resolveUpdate = res
      }),
    )
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    await wrapper.setProps({ date: "2026-04-11" })
    resolveUpdate({ ok: true })
    await flushPromises()
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "toggle", scheduleDate: "2026-04-10" }),
    )
  })

  it("edit binds scheduleDate to the date active when the request started (issue #21)", async () => {
    let resolveUpdate: (v: { ok: boolean }) => void = () => {}
    mockUpdateBlock.mockReturnValueOnce(
      new Promise<{ ok: boolean }>((res) => {
        resolveUpdate = res
      }),
    )
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".title").trigger("click")
    await wrapper.find(".title-input").setValue("Renamed")
    await wrapper.find(".title-input").trigger("keydown.enter")
    await wrapper.setProps({ date: "2026-04-11" })
    resolveUpdate({ ok: true })
    await flushPromises()
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "edit", scheduleDate: "2026-04-10" }),
    )
  })

  it("delete binds scheduleDate to the date active when the request started (issue #21)", async () => {
    let resolveDelete: (v: { ok: boolean }) => void = () => {}
    mockDeleteBlock.mockReturnValueOnce(
      new Promise<{ ok: boolean }>((res) => {
        resolveDelete = res
      }),
    )
    vi.spyOn(window, "confirm").mockReturnValue(true)
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".delete-btn").trigger("click")
    await wrapper.setProps({ date: "2026-04-11" })
    resolveDelete({ ok: true })
    await flushPromises()
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "delete", scheduleDate: "2026-04-10" }),
    )
  })
})
