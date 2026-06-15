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
    expect(mockUpdateBlock).toHaveBeenCalledWith(1, { is_completed: true })
  })

  it("shows error when toggle fails", async () => {
    mockUpdateBlock.mockResolvedValue({ ok: false })
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    // Wait for async handler
    await vi.dynamicImportSettled()
    expect(wrapper.text()).toContain("Failed to update")
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
