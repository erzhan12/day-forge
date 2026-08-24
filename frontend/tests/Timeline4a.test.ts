import { afterEach, describe, expect, it, vi } from "vitest"
import { mount, VueWrapper } from "@vue/test-utils"

import Timeline4a from "../src/components/Timeline4a.vue"
import type { TimeBlock } from "../src/types"
import {
  DEFAULT_SCHEDULE_WINDOW,
  STUB_MINUTES,
  computeRenderBounds,
} from "../src/utils/scheduleTime"

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
      pxPerMinute: 2,
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
  it("positions a block from the axis origin at 2 px/min, not flow layout", () => {
    mountTimeline({
      timelineOriginMinutes: 6 * 60,
      timelineEndMinutes: 23 * 60,
      pxPerMinute: 2,
    })
    const item = wrapper!.get(".time-block-4a").element.parentElement as HTMLElement
    expect(item.style.top).toBe(`${(9 * 60 - 6 * 60) * 2}px`)
    expect(item.style.height).toBe(`${60 * 2}px`)
  })

  it("sizes the canvas from axis end minus origin", () => {
    mountTimeline({
      timelineOriginMinutes: 6 * 60,
      timelineEndMinutes: 23 * 60,
      pxPerMinute: 2,
    })
    expect(wrapper!.get('[data-testid="timeline-4a"]').element.style.height).toBe(
      `${(23 * 60 - 6 * 60) * 2}px`,
    )
  })

  it("gives an out-of-window early block a non-negative top", () => {
    mountTimeline({
      blocks: [{ ...BLOCK, start_time: "05:00", end_time: "06:00" }],
      timelineOriginMinutes: 5 * 60,
      timelineEndMinutes: 23 * 60,
      pxPerMinute: 2,
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

const AFTERNOON: TimeBlock = {
  ...BLOCK,
  start_time: "14:00",
  end_time: "15:00",
}

function gapItem(index: number): HTMLElement {
  const gaps = wrapper!.findAll(".gap-slot-4a")
  return gaps[index].element.parentElement as HTMLElement
}

describe("Timeline4a edge stubs (0017)", () => {
  const px = 2

  it("collapses the leading gap to a 30-minute stub above a late first block", () => {
    const bounds = computeRenderBounds([AFTERNOON], null, DEFAULT_SCHEDULE_WINDOW)
    mountTimeline({
      blocks: [AFTERNOON],
      timelineOriginMinutes: bounds.renderStart,
      timelineEndMinutes: bounds.renderEnd,
      nowDate: null,
      nowMinutes: null,
      pxPerMinute: px,
    })
    const leading = gapItem(0)
    expect(Number.parseFloat(leading.style.top)).toBe(0)
    expect(leading.style.height).toBe(`${STUB_MINUTES * px}px`)
    expect(wrapper!.text()).toContain("earlier")
    expect(wrapper!.text()).toContain("06:00 – 14:00")
  })

  it("collapses the trailing gap to a 30-minute stub after an early last block", () => {
    const bounds = computeRenderBounds([AFTERNOON], null, DEFAULT_SCHEDULE_WINDOW)
    mountTimeline({
      blocks: [AFTERNOON],
      timelineOriginMinutes: bounds.renderStart,
      timelineEndMinutes: bounds.renderEnd,
      nowDate: null,
      nowMinutes: null,
      pxPerMinute: px,
    })
    const trailing = gapItem(wrapper!.findAll(".gap-slot-4a").length - 1)
    expect(trailing.style.height).toBe(`${STUB_MINUTES * px}px`)
    expect(wrapper!.text()).toContain("later")
    expect(wrapper!.text()).toContain("15:00 – 23:00")
  })

  it("emits the full semantic leading range from a compressed stub", async () => {
    const bounds = computeRenderBounds([AFTERNOON], null, DEFAULT_SCHEDULE_WINDOW)
    mountTimeline({
      blocks: [AFTERNOON],
      timelineOriginMinutes: bounds.renderStart,
      timelineEndMinutes: bounds.renderEnd,
      nowDate: null,
      nowMinutes: null,
      pxPerMinute: px,
    })
    await wrapper!.findAll(".gap-slot")[0].trigger("click")
    expect(wrapper!.emitted("add-here")).toEqual([
      [{ start_time: "06:00", end_time: "14:00" }],
    ])
  })

  it("places the now-line inside the leading stub when now is before the compressed origin", () => {
    const bounds = computeRenderBounds([AFTERNOON], null, DEFAULT_SCHEDULE_WINDOW)
    mountTimeline({
      blocks: [AFTERNOON],
      timelineOriginMinutes: bounds.renderStart,
      timelineEndMinutes: bounds.renderEnd,
      nowMinutes: 10 * 60,
      nowDate: "2026-08-22",
      pxPerMinute: px,
    })
    const nowLine = wrapper!.get('[data-testid="now-line-4a"]').element as HTMLElement
    // 10:00 sits halfway through the semantic 06:00–14:00 leading gap, mapped
    // onto the 30-minute stub (origin-shift, not a linear pre-origin top).
    expect(nowLine.style.top).toBe(`${0.5 * STUB_MINUTES * px}px`)
  })

  it("keeps a mid-day gap at full scale", () => {
    const morning: TimeBlock = { ...BLOCK, id: 1, start_time: "09:00", end_time: "10:00" }
    const afternoon: TimeBlock = { ...BLOCK, id: 2, start_time: "12:00", end_time: "13:00", sort_order: 10 }
    const bounds = computeRenderBounds([morning, afternoon], null, DEFAULT_SCHEDULE_WINDOW)
    mountTimeline({
      blocks: [morning, afternoon],
      timelineOriginMinutes: bounds.renderStart,
      timelineEndMinutes: bounds.renderEnd,
      nowDate: null,
      nowMinutes: null,
      pxPerMinute: px,
    })
    const mid = wrapper!.findAll(".timeline-item").find((item) => {
      const slot = item.find(".gap-slot")
      return slot.exists() && slot.text().includes("10:00 – 12:00")
    })
    expect(mid).toBeTruthy()
    expect((mid!.element as HTMLElement).style.height).toBe(`${120 * px}px`)
  })

  it("uses compact render bounds when the parent omits an explicit axis", () => {
    mountTimeline({
      blocks: [AFTERNOON],
      nowDate: null,
      nowMinutes: null,
      pxPerMinute: px,
    })
    const bounds = computeRenderBounds([AFTERNOON], null, DEFAULT_SCHEDULE_WINDOW)
    expect(wrapper!.get('[data-testid="timeline-4a"]').element.style.height).toBe(
      `${(bounds.renderEnd - bounds.renderStart) * px}px`,
    )
    expect(gapItem(0).style.height).toBe(`${STUB_MINUTES * px}px`)
  })
})
