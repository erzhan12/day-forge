import { afterEach, describe, expect, it, vi } from "vitest"
import { mount, VueWrapper } from "@vue/test-utils"

import Timeline4a from "../src/components/Timeline4a.vue"
import type { TimeBlock } from "../src/types"

let wrapper: VueWrapper | null = null

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

const BLOCK: TimeBlock = {
  id: 1,
  title: "Work",
  start_time: "09:00",
  end_time: "10:00",
  category: "work",
  is_completed: false,
  sort_order: 0,
}

function mountTimeline(overrides: Record<string, unknown> = {}) {
  Element.prototype.scrollIntoView = vi.fn()
  wrapper = mount(Timeline4a, {
    props: {
      blocks: [BLOCK],
      date: "2026-08-22",
      scheduleWindow: { start: "06:00", end: "23:00" },
      nowMinutes: 10 * 60,
      nowDate: "2026-08-22",
      pxPerMinute: 1.6,
      disabled: false,
      ...overrides,
    },
  })
  return wrapper
}

describe("Timeline4a now-line", () => {
  it("shows the now-line when nowDate matches the viewed date", () => {
    mountTimeline()
    expect(wrapper!.find('[data-testid="now-line-4a"]').exists()).toBe(true)
  })

  it("hides the now-line when viewing a different date", () => {
    mountTimeline({ date: "2026-08-21", nowDate: "2026-08-22", nowMinutes: 10 * 60 })
    expect(wrapper!.find('[data-testid="now-line-4a"]').exists()).toBe(false)
  })
})

describe("Timeline4a absolute axis", () => {
  it("positions a block from the axis origin at 1.6 px/min, not flow layout", () => {
    mountTimeline({
      timelineOriginMinutes: 6 * 60,
      timelineEndMinutes: 23 * 60,
      pxPerMinute: 1.6,
    })
    const item = wrapper!.get(".time-block-4a").element.parentElement as HTMLElement
    expect(item.style.top).toBe(`${(9 * 60 - 6 * 60) * 1.6}px`)
    expect(item.style.height).toBe(`${60 * 1.6}px`)
  })

  it("sizes the canvas from axis end minus origin", () => {
    mountTimeline({
      timelineOriginMinutes: 6 * 60,
      timelineEndMinutes: 23 * 60,
      pxPerMinute: 1.6,
    })
    expect(wrapper!.get('[data-testid="timeline-4a"]').element.style.height).toBe(
      `${(23 * 60 - 6 * 60) * 1.6}px`,
    )
  })

  it("gives an out-of-window early block a non-negative top", () => {
    mountTimeline({
      blocks: [{ ...BLOCK, start_time: "05:00", end_time: "06:00" }],
      timelineOriginMinutes: 5 * 60,
      timelineEndMinutes: 23 * 60,
      pxPerMinute: 1.6,
    })
    const item = wrapper!.get(".time-block-4a").element.parentElement as HTMLElement
    expect(Number.parseFloat(item.style.top)).toBeGreaterThanOrEqual(0)
  })

  it("does not render spacer slots", () => {
    mountTimeline({
      timelineOriginMinutes: 6 * 60,
      timelineEndMinutes: 23 * 60,
    })
    const items = wrapper!.findAll(".timeline-item")
    expect(items.length).toBeGreaterThan(0)
    for (const item of items) {
      const hasBlock = item.find(".time-block-4a").exists()
      const hasGap = item.find(".gap-slot-4a").exists()
      expect(hasBlock || hasGap).toBe(true)
    }
  })
})
