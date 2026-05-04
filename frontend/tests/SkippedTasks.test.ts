import { describe, it, expect, beforeEach, vi, afterEach } from "vitest"
import { mount, flushPromises } from "@vue/test-utils"
import SkippedTasks from "../src/components/SkippedTasks.vue"
import type { TimeBlock } from "../src/types"

function block(
  id: number,
  start: string,
  end: string,
  completed: boolean,
): TimeBlock {
  return {
    id,
    title: `b${id}`,
    start_time: start,
    end_time: end,
    category: "work",
    is_completed: completed,
    sort_order: 0,
  }
}

const PAST = "2026-04-01"
const TODAY = "2026-05-03"

describe("SkippedTasks", () => {
  beforeEach(() => {
    vi.useFakeTimers()
    vi.setSystemTime(new Date(2026, 4, 3, 12, 0)) // 2026-05-03 12:00 local
  })

  afterEach(() => {
    vi.useRealTimers()
  })

  it("past day with mix lists every uncompleted block", () => {
    const wrapper = mount(SkippedTasks, {
      props: {
        date: PAST,
        blocks: [
          block(1, "09:00", "10:00", true),
          block(2, "10:00", "11:00", false),
          block(3, "14:00", "15:00", false),
        ],
      },
    })
    const rows = wrapper.findAll(".skipped-row")
    expect(rows.length).toBe(2)
    expect(wrapper.text()).toContain("b2")
    expect(wrapper.text()).toContain("b3")
  })

  it("today: blocks ending before now are listed", () => {
    const wrapper = mount(SkippedTasks, {
      props: {
        date: TODAY,
        blocks: [
          block(1, "09:00", "10:00", false), // ended at 10:00, before noon
          block(2, "10:00", "11:00", false),
        ],
      },
    })
    expect(wrapper.findAll(".skipped-row").length).toBe(2)
  })

  it("today: future-window uncompleted blocks are NOT listed", () => {
    const wrapper = mount(SkippedTasks, {
      props: {
        date: TODAY,
        blocks: [
          block(1, "09:00", "10:00", false),
          block(2, "14:00", "15:00", false), // still in the future
        ],
      },
    })
    const rows = wrapper.findAll(".skipped-row")
    expect(rows.length).toBe(1)
    expect(rows[0].text()).toContain("b1")
  })

  it("today: when no blocks are skipped, the section is hidden", () => {
    const wrapper = mount(SkippedTasks, {
      props: {
        date: TODAY,
        blocks: [block(1, "14:00", "15:00", false)],
      },
    })
    expect(wrapper.find(".skipped-tasks").exists()).toBe(false)
  })

  it("today: list updates as time advances past a block's end", async () => {
    const wrapper = mount(SkippedTasks, {
      props: {
        date: TODAY,
        blocks: [
          block(1, "09:00", "10:00", false),
          block(2, "12:30", "13:00", false), // ends after current 12:00
        ],
      },
    })
    expect(wrapper.findAll(".skipped-row").length).toBe(1)

    // Advance system clock past 13:00 and trigger the 1-min interval.
    vi.setSystemTime(new Date(2026, 4, 3, 13, 30))
    vi.advanceTimersByTime(60_000)
    await flushPromises()

    expect(wrapper.findAll(".skipped-row").length).toBe(2)
  })
})
