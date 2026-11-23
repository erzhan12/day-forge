import { afterEach, describe, expect, it, vi } from "vitest"
import { mount, VueWrapper } from "@vue/test-utils"
import { makeCategories, makeScheduleProvides } from "./helpers/schedule"

import Timeline4a from "../src/components/Timeline4a.vue"
import { createTimelinePresentation, type TimelinePresentationInput, type TimelinePresentation } from "../src/composables/useTimelinePresentation"
import type { TimeBlock } from "../src/types"
import {
  DEFAULT_SCHEDULE_WINDOW,
  STUB_MINUTES,
  computeRenderBounds,
  minutesToTime,
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

type TimelineFixture = Partial<TimelinePresentationInput> & { presentation?: TimelinePresentation }

function mountTimeline(overrides: TimelineFixture = {}) {
  Element.prototype.scrollIntoView = vi.fn()
  const input = {
    blocks: [BLOCK],
    date: "2026-08-22",
    window: DEFAULT_SCHEDULE_WINDOW,
    nowMinutes: 10 * 60,
    nowDate: "2026-08-22",
    pxPerMinute: 2,
    layoutMode: "stack" as const,
    ...overrides,
  }
  wrapper = mount(Timeline4a, {
    props: {
      date: input.date,
      currentHHMM: input.nowMinutes === null ? "" : minutesToTime(input.nowMinutes),
      presentation: input.presentation ?? createTimelinePresentation(input),
      disabled: false,
      categories: makeCategories(),
    },
    global: { provide: makeScheduleProvides() },
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

describe("Timeline4a stack axis (0106)", () => {
  it("keeps drag geometry frozen when the parent updates the clock and scale", async () => {
    const input: TimelinePresentationInput = {
      blocks: [BLOCK], date: "2026-08-22", window: DEFAULT_SCHEDULE_WINDOW,
      nowMinutes: 630, nowDate: "2026-08-22", pxPerMinute: 1.6, layoutMode: "stack",
      drag: {
        isDragging: true, previewBlocks: [], dragBlockId: 1,
        frozenRenderBounds: computeRenderBounds([BLOCK], 630, DEFAULT_SCHEDULE_WINDOW),
        frozenNowMinutes: 630, frozenPxPerMinute: 1.6,
        frozenTimelineOriginMinutes: null, frozenWindow: DEFAULT_SCHEDULE_WINDOW,
      },
    }
    const model = createTimelinePresentation(input)
    mountTimeline({ presentation: model, nowMinutes: 630 })
    const initialHeight = wrapper!.get('[data-testid="timeline-4a"]').element.style.height
    const initialBlockTop = (wrapper!.get(".time-block-4a").element.parentElement as HTMLElement).style.top
    await wrapper!.setProps({
      presentation: createTimelinePresentation({ ...input, pxPerMinute: 2, nowMinutes: 645 }),
      currentHHMM: "10:45",
    })
    expect(wrapper!.get('[data-testid="timeline-4a"]').element.style.height).toBe(initialHeight)
    expect((wrapper!.get(".time-block-4a").element.parentElement as HTMLElement).style.top).toBe(initialBlockTop)
    expect(wrapper!.get('[data-testid="timeline-4a"]').element.style.height).toBe(`${model.canvasHeightPx}px`)
    expect(wrapper!.get('[data-testid="now-line-4a"]').text()).toContain("10:45")
  })

  it("stacks a block below a capped leading stub at 2 px/min", () => {
    mountTimeline({ nowDate: null, nowMinutes: null })
    const item = wrapper!.get(".time-block-4a").element.parentElement as HTMLElement
    // 06:00–09:00 leading gap capped at 60 px, then the 60-minute block.
    expect(item.style.top).toBe(`${STUB_MINUTES * 2}px`)
    expect(item.style.height).toBe(`${60 * 2}px`)
  })

  it("sizes the canvas from the stacked items", () => {
    mountTimeline({ nowDate: null, nowMinutes: null })
    // 60 px leading stub + 120 px block + 60 px trailing stub.
    expect(wrapper!.get('[data-testid="timeline-4a"]').element.style.height).toBe("240px")
  })

  it("gives an out-of-window early block a non-negative top", () => {
    mountTimeline({ blocks: [{ ...BLOCK, start_time: "05:00", end_time: "06:00" }] })
    const item = wrapper!.get(".time-block-4a").element.parentElement as HTMLElement
    expect(Number.parseFloat(item.style.top)).toBeGreaterThanOrEqual(0)
  })

  it("does not render spacer slots", () => {
    mountTimeline()
    const items = wrapper!.findAll(".timeline-item")
    expect(items.length).toBeGreaterThan(0)
    for (const item of items) {
      const hasBlock = item.find(".time-block-4a").exists()
      const hasGap = item.find('[data-testid="gap-row-4a"]').exists()
      expect(hasBlock || hasGap).toBe(true)
    }
  })

  it("renders a 5-minute block 28px tall without overlapping its neighbours", () => {
    const blocks: TimeBlock[] = [
      { ...BLOCK, id: 1, start_time: "11:15", end_time: "11:40", sort_order: 0 },
      { ...BLOCK, id: 2, start_time: "11:40", end_time: "11:45", sort_order: 1 },
      { ...BLOCK, id: 3, start_time: "11:45", end_time: "12:10", sort_order: 2 },
    ]
    mountTimeline({ blocks, nowDate: null, nowMinutes: null })
    const boxes = wrapper!.findAll(".time-block-4a").map((b) => {
      const el = b.element.parentElement as HTMLElement
      return { top: Number.parseFloat(el.style.top), height: Number.parseFloat(el.style.height) }
    })
    expect(boxes.map((b) => b.height)).toEqual([50, 28, 50])
    expect(boxes[1].top).toBe(boxes[0].top + boxes[0].height)
    expect(boxes[2].top).toBe(boxes[1].top + boxes[1].height)
    expect(wrapper!.findAll(".time-block-4a")[1].classes()).toContain("is-compact")
  })
})

const AFTERNOON: TimeBlock = {
  ...BLOCK,
  start_time: "14:00",
  end_time: "15:00",
}

function gapItem(index: number): HTMLElement {
  const gaps = wrapper!.findAll('[data-testid="gap-row-4a"]')
  return gaps[index].element.parentElement as HTMLElement
}

describe("Timeline4a edge stubs (0017, stacked in 0106)", () => {
  const px = 2

  it("collapses the leading gap to a 30-minute stub above a late first block", () => {
    mountTimeline({ blocks: [AFTERNOON], nowDate: null, nowMinutes: null, pxPerMinute: px })
    const leading = gapItem(0)
    expect(Number.parseFloat(leading.style.top)).toBe(0)
    expect(leading.style.height).toBe(`${STUB_MINUTES * px}px`)
    expect(wrapper!.text()).toContain("earlier")
    expect(wrapper!.text()).toContain("06:00\u201314:00")
  })

  it("collapses the trailing gap to a 30-minute stub after an early last block", () => {
    mountTimeline({ blocks: [AFTERNOON], nowDate: null, nowMinutes: null, pxPerMinute: px })
    const trailing = gapItem(wrapper!.findAll('[data-testid="gap-row-4a"]').length - 1)
    expect(trailing.style.height).toBe(`${STUB_MINUTES * px}px`)
    expect(wrapper!.text()).toContain("later")
    expect(wrapper!.text()).toContain("15:00\u201323:00")
  })

  it("emits the full semantic leading range from a compressed stub", async () => {
    mountTimeline({ blocks: [AFTERNOON], nowDate: null, nowMinutes: null, pxPerMinute: px })
    await wrapper!.findAll('[data-testid="gap-row-4a"]')[0].trigger("click")
    expect(wrapper!.emitted("add-here-4a")).toEqual([
      [{ start_time: "06:00", end_time: "14:00" }],
    ])
  })

  it("places the now-line inside the leading stub when now is before the first block", () => {
    mountTimeline({ blocks: [AFTERNOON], nowMinutes: 10 * 60, nowDate: "2026-08-22", pxPerMinute: px })
    const nowLine = wrapper!.get('[data-testid="now-line-4a"]').element as HTMLElement
    // 10:00 sits halfway through the semantic 06:00–14:00 leading gap.
    expect(nowLine.style.top).toBe(`${0.5 * STUB_MINUTES * px}px`)
  })

  it("caps a mid-day gap at 60px", () => {
    const morning: TimeBlock = { ...BLOCK, id: 1, start_time: "09:00", end_time: "10:00" }
    const afternoon: TimeBlock = { ...BLOCK, id: 2, start_time: "12:00", end_time: "13:00", sort_order: 10 }
    mountTimeline({ blocks: [morning, afternoon], nowDate: null, nowMinutes: null, pxPerMinute: px })
    const mid = wrapper!.findAll(".timeline-item").find((item) =>
      item.find('[data-testid="gap-4a-range"]').exists() &&
      item.get('[data-testid="gap-4a-range"]').text() === "10:00\u201312:00")
    expect(mid).toBeTruthy()
    expect((mid!.element as HTMLElement).style.height).toBe("60px")
  })
})
