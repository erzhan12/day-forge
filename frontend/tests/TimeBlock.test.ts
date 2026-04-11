import { describe, it, expect, vi, beforeEach } from "vitest"
import { mount } from "@vue/test-utils"

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

describe("TimeBlock", () => {
  beforeEach(() => {
    vi.clearAllMocks()
  })

  it("renders block title and times", () => {
    const wrapper = mount(TimeBlock, {
      props: { block: makeBlock(), date: "2026-04-10" },
    })
    expect(wrapper.text()).toContain("Test Block")
    expect(wrapper.text()).toContain("09:00")
    expect(wrapper.text()).toContain("10:00")
  })

  it("computes duration correctly", () => {
    const wrapper = mount(TimeBlock, {
      props: { block: makeBlock({ start_time: "09:00", end_time: "10:30" }), date: "2026-04-10" },
    })
    expect(wrapper.text()).toContain("1h 30m")
  })

  it("toggles completion on checkbox change", async () => {
    mockUpdateBlock.mockResolvedValue({ ok: true })
    const wrapper = mount(TimeBlock, {
      props: { block: makeBlock(), date: "2026-04-10" },
    })
    await wrapper.find(".checkbox").trigger("change")
    expect(mockUpdateBlock).toHaveBeenCalledWith(1, { is_completed: true })
  })

  it("shows error when toggle fails", async () => {
    mockUpdateBlock.mockResolvedValue({ ok: false })
    const wrapper = mount(TimeBlock, {
      props: { block: makeBlock(), date: "2026-04-10" },
    })
    await wrapper.find(".checkbox").trigger("change")
    // Wait for async handler
    await vi.dynamicImportSettled()
    expect(wrapper.text()).toContain("Failed to update")
  })

  it("enters edit mode on title click", async () => {
    const wrapper = mount(TimeBlock, {
      props: { block: makeBlock(), date: "2026-04-10" },
    })
    expect(wrapper.find(".title-input").exists()).toBe(false)
    await wrapper.find(".title").trigger("click")
    expect(wrapper.find(".title-input").exists()).toBe(true)
    expect((wrapper.find(".title-input").element as HTMLInputElement).value).toBe("Test Block")
  })

  it("saves title on enter and exits edit mode", async () => {
    mockUpdateBlock.mockResolvedValue({ ok: true })
    const wrapper = mount(TimeBlock, {
      props: { block: makeBlock(), date: "2026-04-10" },
    })
    await wrapper.find(".title").trigger("click")
    const input = wrapper.find(".title-input")
    await input.setValue("New Title")
    await input.trigger("keydown.enter")
    expect(mockUpdateBlock).toHaveBeenCalledWith(1, { title: "New Title" })
  })

  it("cancels editing on escape without saving", async () => {
    const wrapper = mount(TimeBlock, {
      props: { block: makeBlock(), date: "2026-04-10" },
    })
    await wrapper.find(".title").trigger("click")
    await wrapper.find(".title-input").trigger("keydown.escape")
    expect(wrapper.find(".title-input").exists()).toBe(false)
    expect(mockUpdateBlock).not.toHaveBeenCalled()
  })

  it("does not save if title unchanged", async () => {
    const wrapper = mount(TimeBlock, {
      props: { block: makeBlock(), date: "2026-04-10" },
    })
    await wrapper.find(".title").trigger("click")
    await wrapper.find(".title-input").trigger("keydown.enter")
    expect(mockUpdateBlock).not.toHaveBeenCalled()
  })

  it("calls delete after confirm", async () => {
    mockDeleteBlock.mockResolvedValue({ ok: true })
    vi.spyOn(window, "confirm").mockReturnValue(true)
    const wrapper = mount(TimeBlock, {
      props: { block: makeBlock(), date: "2026-04-10" },
    })
    await wrapper.find(".delete-btn").trigger("click")
    expect(mockDeleteBlock).toHaveBeenCalledWith(1)
  })

  it("does not delete if confirm cancelled", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(false)
    const wrapper = mount(TimeBlock, {
      props: { block: makeBlock(), date: "2026-04-10" },
    })
    await wrapper.find(".delete-btn").trigger("click")
    expect(mockDeleteBlock).not.toHaveBeenCalled()
  })

  it("shows completed styling", () => {
    const wrapper = mount(TimeBlock, {
      props: { block: makeBlock({ is_completed: true }), date: "2026-04-10" },
    })
    expect(wrapper.find(".time-block").classes()).toContain("completed")
    expect(wrapper.find(".title-completed").exists()).toBe(true)
  })

  it("shows error on failed title update", async () => {
    mockUpdateBlock.mockResolvedValue({ ok: false })
    const wrapper = mount(TimeBlock, {
      props: { block: makeBlock(), date: "2026-04-10" },
    })
    await wrapper.find(".title").trigger("click")
    await wrapper.find(".title-input").setValue("Changed")
    await wrapper.find(".title-input").trigger("keydown.enter")
    await vi.dynamicImportSettled()
    expect(wrapper.text()).toContain("Failed to update title")
  })
})
