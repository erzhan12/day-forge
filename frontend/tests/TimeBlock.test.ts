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

function mountWithProvide(props: { block: TimeBlockType; date: string }) {
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
      expect.objectContaining({ type: "edit" }),
    )
  })

  it("pushUndo called on successful toggle", async () => {
    mockUpdateBlock.mockResolvedValue({ ok: true })
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "toggle" }),
    )
  })

  it("keeps toggle undo bound to the date that started the update", async () => {
    let resolveUpdate!: (value: { ok: true }) => void
    mockUpdateBlock.mockReturnValueOnce(
      new Promise((resolve) => {
        resolveUpdate = resolve
      }),
    )
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")

    await wrapper.setProps({ block: makeBlock(), date: "2026-04-11" })
    resolveUpdate({ ok: true })
    await flushPromises()

    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "toggle", scheduleDate: "2026-04-10" }),
    )
  })

  it("pushUndo called on successful delete", async () => {
    mockDeleteBlock.mockResolvedValue({ ok: true })
    vi.spyOn(window, "confirm").mockReturnValue(true)
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".delete-btn").trigger("click")
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "delete" }),
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
})
