import { describe, expect, it } from "vitest"
import type { TimeBlock } from "../src/types"
import {
  buildBaseDisplayItems,
  computeRenderBounds,
  timeToMinutes,
  type ScheduleDisplayItem,
  type ScheduleWindowBounds,
} from "../src/utils/scheduleTime"
import { createTimelinePresentation } from "../src/composables/useTimelinePresentation"
import {
  COMPACT_BELOW_PX,
  MIN_BLOCK_PX,
  buildTimelineStack,
  type TimelineStack,
} from "../src/utils/timelineStack"

const PPM = 2
const m = timeToMinutes

function windowOf(start: string, end: string): ScheduleWindowBounds {
  return { start, end, startMinutes: m(start), endMinutes: m(end) }
}

let nextId = 1
function block(start: string, end: string, sortOrder = 0): TimeBlock {
  const id = nextId++
  return {
    id, title: `Block ${id}`, start_time: start, end_time: end,
    category: "work", is_completed: false, sort_order: sortOrder,
  }
}

function stackFor(blocks: TimeBlock[], window: ScheduleWindowBounds, nowMinutes: number | null = null): TimelineStack {
  const bounds = computeRenderBounds(blocks, nowMinutes, window)
  const items = buildBaseDisplayItems(blocks, bounds.renderStart, bounds.renderEnd, nowMinutes, window)
  return buildTimelineStack(items, PPM, window)
}

function gap(start: string, end: string, extra: Partial<ScheduleDisplayItem> = {}): ScheduleDisplayItem {
  return { type: "gap", start_time: start, end_time: end, duration_minutes: m(end) - m(start), ...extra }
}

function blockItem(start: string, end: string): ScheduleDisplayItem {
  const b = block(start, end)
  return { type: "block", block: b, start_time: start, end_time: end, duration_minutes: m(end) - m(start) }
}

// 22 Nov 2026 fixture (schedule-today.png): window 05:00–22:00.
const FIXTURE_WINDOW = windowOf("05:00", "22:00")
function fixtureBlocks(): TimeBlock[] {
  return [
    block("09:40", "10:05", 0),
    block("11:15", "11:40", 1),
    block("11:40", "11:45", 2),
    block("11:45", "12:10", 3),
    block("15:00", "16:00", 4),
  ]
}

function heights(stack: TimelineStack): number[] {
  return stack.segments.map((s) => s.heightPx)
}

describe("buildTimelineStack (0106)", () => {
  describe("heights", () => {
    it("raises a 5-minute block to 28px", () => {
      const stack = buildTimelineStack([blockItem("11:40", "11:45")], PPM, FIXTURE_WINDOW)
      expect(stack.items[0].heightPx).toBe(MIN_BLOCK_PX)
      expect(MIN_BLOCK_PX).toBe(28)
    })

    it("keeps an 18-minute block on the scale", () => {
      const stack = buildTimelineStack([blockItem("11:40", "11:58")], PPM, FIXTURE_WINDOW)
      expect(stack.items[0].heightPx).toBe(36)
    })

    it("caps a 170-minute gap at 60px", () => {
      const stack = buildTimelineStack([gap("12:10", "15:00")], PPM, FIXTURE_WINDOW)
      expect(stack.items[0].heightPx).toBe(60)
      expect(stack.items[0].compressed).toBe(true)
    })

    it("keeps a 25-minute gap on the scale", () => {
      const stack = buildTimelineStack([gap("12:10", "12:35")], PPM, FIXTURE_WINDOW)
      expect(stack.items[0].heightPx).toBe(50)
      expect(stack.items[0].compressed).toBe(false)
    })

    it("does not shrink a 30-minute edge stub again", () => {
      const stack = buildTimelineStack([
        gap("05:00", "09:40", { render_minutes: 30, compact: true }),
        blockItem("09:40", "10:05"),
      ], PPM, FIXTURE_WINDOW)
      expect(stack.items[0].heightPx).toBe(60)
    })
  })

  describe("stacking", () => {
    it("stacks items with no overlap and no hole", () => {
      const stack = stackFor(fixtureBlocks(), FIXTURE_WINDOW)
      for (let i = 1; i < stack.segments.length; i++) {
        const prev = stack.segments[i - 1]
        expect(stack.segments[i].topPx).toBe(prev.topPx + prev.heightPx)
      }
      expect(stack.segments[0].topPx).toBe(0)
    })

    it("pushes everything below a stretched block down by the missing pixels", () => {
      const stack = buildTimelineStack([
        blockItem("11:40", "11:45"),
        blockItem("11:45", "12:10"),
      ], PPM, FIXTURE_WINDOW)
      expect(stack.items[1].topPx).toBe(28)
      expect(stack.segments[0].stretched).toBe(true)
    })

    it("does not let the next gap absorb a stretch", () => {
      const stack = buildTimelineStack([
        blockItem("11:40", "11:45"),
        gap("11:45", "12:05"),
        blockItem("12:05", "12:30"),
      ], PPM, FIXTURE_WINDOW)
      expect(stack.items[1].heightPx).toBe(40)
      expect(stack.items[2].topPx).toBe(68)
    })

    it("lays out time-overlapping blocks one under another", () => {
      const stack = stackFor([block("10:00", "11:00", 0), block("10:30", "11:30", 1)], windowOf("10:00", "11:30"))
      const blocks = stack.items.filter((i) => i.item.type === "block")
      expect(blocks.map((b) => [b.topPx, b.heightPx])).toEqual([[0, 120], [120, 120]])
    })
  })

  describe("monotonicity", () => {
    it("is monotonic by duration within blocks and within gaps", () => {
      let prevBlock = 0
      let prevGap = 0
      for (let minutes = 5; minutes <= 600; minutes += 5) {
        const end = 6 * 60 + minutes
        const endTime = `${String(Math.floor(end / 60)).padStart(2, "0")}:${String(end % 60).padStart(2, "0")}`
        const b = buildTimelineStack([blockItem("06:00", endTime)], PPM, windowOf("05:00", "23:00")).items[0].heightPx
        const g = buildTimelineStack([gap("06:00", endTime)], PPM, windowOf("05:00", "23:00")).items[0].heightPx
        expect(b).toBeGreaterThanOrEqual(prevBlock)
        expect(g).toBeGreaterThanOrEqual(prevGap)
        prevBlock = b
        prevGap = g
      }
    })

    it("never renders a 70-minute gap lower than a 25-minute block", () => {
      const stack = buildTimelineStack([
        blockItem("09:00", "09:25"),
        gap("09:25", "10:35"),
        blockItem("10:35", "11:00"),
      ], PPM, FIXTURE_WINDOW)
      expect(stack.items[1].heightPx).toBeGreaterThanOrEqual(stack.items[0].heightPx)
    })

    it("lets the cap win over a 40-minute block (documented limit)", () => {
      const stack = buildTimelineStack([
        blockItem("09:00", "09:40"),
        gap("09:40", "10:50"),
        blockItem("10:50", "11:00"),
      ], PPM, FIXTURE_WINDOW)
      expect(stack.items[1].heightPx).toBe(60)
      expect(stack.items[0].heightPx).toBe(80)
    })

    it("lets the floor win over a 10-minute gap (documented limit)", () => {
      const stack = buildTimelineStack([
        blockItem("09:00", "09:05"),
        gap("09:05", "09:15"),
        blockItem("09:15", "10:00"),
      ], PPM, FIXTURE_WINDOW)
      expect(stack.items[1].heightPx).toBe(20)
      expect(stack.items[0].heightPx).toBe(28)
    })
  })

  describe("gaps", () => {
    it("coalesces adjacent free items into one capped gap", () => {
      const stack = buildTimelineStack([
        blockItem("15:00", "16:00"),
        gap("16:00", "17:00"),
        gap("17:00", "22:00", { render_minutes: 30, compact: true }),
      ], PPM, FIXTURE_WINDOW)
      const gaps = stack.items.filter((i) => i.item.type === "gap")
      expect(gaps).toHaveLength(1)
      expect(gaps[0].item).toMatchObject({ start_time: "16:00", end_time: "22:00", duration_minutes: 360 })
      expect(gaps[0].heightPx).toBe(60)
    })

    it("drops a fully covered gap and keeps the free suffix of a partly covered one", () => {
      const window = windowOf("09:00", "17:00")
      const covered = stackFor([block("10:00", "14:00", 0), block("11:00", "12:00", 1), block("13:00", "15:00", 2)], window)
      expect(covered.items.some((i) => i.item.type === "gap" && i.item.start_time === "12:00")).toBe(false)

      const partial = stackFor([block("10:00", "14:00", 0), block("11:00", "12:00", 1), block("15:00", "16:00", 2)], window)
      const gaps = partial.items.filter((i) => i.item.type === "gap").map((i) => [i.item.start_time, i.item.end_time])
      expect(gaps).toContainEqual(["14:00", "15:00"])
      expect(gaps).not.toContainEqual(["12:00", "15:00"])
    })

    it("never merges a spacer into a clickable gap", () => {
      const stack = buildTimelineStack([
        { type: "spacer", start_time: "05:00", end_time: "06:00", duration_minutes: 60 },
        gap("06:00", "07:00"),
        blockItem("07:00", "08:00"),
      ], PPM, windowOf("06:00", "08:00"))
      expect(stack.segments.map((s) => s.kind)).toEqual(["spacer", "gap", "block"])
      expect(stack.items.map((i) => i.item.type)).toEqual(["gap", "block"])
      expect(stack.items[0].topPx).toBe(60)
    })

    it("keeps the later hint and the in-window range on a coalesced trailing gap", () => {
      const blocks = [block("15:00", "16:00")]
      const stack = stackFor(blocks, FIXTURE_WINDOW, m("17:00"))
      const trailing = stack.items.filter((i) => i.item.type === "gap").at(-1)!
      expect(trailing.item).toMatchObject({ start_time: "16:00", end_time: "22:00", duration_minutes: 360 })
      expect(trailing.edgeHint).toBe("later")
      expect(trailing.heightPx).toBe(60)
    })

    it("sizes a corrected tail after a nested overlap from its semantic interval", () => {
      const stack = buildTimelineStack([
        blockItem("10:00", "14:00"),
        blockItem("11:00", "12:00"),
        gap("12:00", "14:20", { render_minutes: 0, compact: true }),
      ], PPM, windowOf("10:00", "14:20"))
      const tail = stack.items.at(-1)!
      expect(tail.item).toMatchObject({ start_time: "14:00", end_time: "14:20", duration_minutes: 20 })
      expect(tail.heightPx).toBe(40)
    })
  })

  describe("linear equivalence and fixture", () => {
    it("equals the linear layout on an off-today, non-overlapping day with nothing clamped", () => {
      const window = windowOf("09:00", "12:00")
      const blocks = [block("09:20", "10:00", 0), block("10:20", "11:30", 1)]
      const linear = createTimelinePresentation({
        blocks, date: "2026-05-04", window, nowMinutes: null, nowDate: null, pxPerMinute: PPM,
      })
      const stack = stackFor(blocks, window)
      expect(stack.items.map((i) => [i.topPx, i.heightPx])).toEqual(
        linear.positionedItems.map((p) => [p.topPx, p.heightPx]),
      )
      expect(stack.canvasHeightPx).toBe(linear.canvasHeightPx)
    })

    it("lays out the 22 Nov 2026 fixture in 538px", () => {
      const stack = stackFor(fixtureBlocks(), FIXTURE_WINDOW)
      expect(heights(stack)).toEqual([60, 50, 60, 50, 28, 50, 60, 120, 60])
      expect(stack.canvasHeightPx).toBe(538)
    })

    it("keeps the fixture at 538px at any clock time", () => {
      for (const now of ["04:30", "11:42", "13:00", "15:30", "17:00", "21:59"]) {
        expect(stackFor(fixtureBlocks(), FIXTURE_WINDOW, m(now)).canvasHeightPx, now).toBe(538)
      }
    })

    it("flags a block compact below 36px rendered height, not by duration", () => {
      const table: Array<[number, boolean]> = [[5, true], [15, true], [17, true], [18, false], [20, false]]
      expect(COMPACT_BELOW_PX).toBe(36)
      for (const [minutes, compact] of table) {
        const end = m("10:00") + minutes
        const endTime = `10:${String(end - m("10:00")).padStart(2, "0")}`
        const stack = buildTimelineStack([blockItem("10:00", endTime)], PPM, FIXTURE_WINDOW)
        expect(stack.items[0].compact, `${minutes}m`).toBe(compact)
      }
    })
  })

  describe("axis map", () => {
    it("maps a time inside a capped gap proportionally", () => {
      const stack = stackFor(fixtureBlocks(), FIXTURE_WINDOW)
      const capped = stack.segments.find((s) => s.startMin === m("12:10"))!
      expect(stack.timeToPx(m("13:35"))).toBeCloseTo(capped.topPx + 30)
    })

    it("maps a time inside a stretched block proportionally", () => {
      const stack = stackFor(fixtureBlocks(), FIXTURE_WINDOW)
      const short = stack.segments.find((s) => s.startMin === m("11:40"))!
      expect(stack.timeToPx(m("11:42"))).toBeCloseTo(short.topPx + (2 / 5) * 28)
    })

    it("pxToTime inverts timeToPx on segment edges", () => {
      const stack = stackFor(fixtureBlocks(), FIXTURE_WINDOW)
      for (const segment of stack.segments) {
        expect(stack.timeToPx(segment.startMin)).toBe(segment.topPx)
        expect(stack.pxToTime(segment.topPx)).toBe(segment.startMin)
      }
      expect(stack.timeToPx(m("22:00"))).toBe(stack.canvasHeightPx)
      expect(stack.pxToTime(stack.canvasHeightPx)).toBe(m("22:00"))
    })

    it("keeps the now line inside an enclosing block that ends after the last stacked block", () => {
      const stack = stackFor([block("10:00", "14:00", 0), block("11:00", "12:00", 1)], windowOf("10:00", "14:00"))
      expect(stack.segmentAt(m("13:00"))?.kind).toBe("block")
      expect(stack.timeToPx(m("13:00"))).toBe(360)
    })
  })

  describe("hour ticks", () => {
    it("emits hour ticks inside blocks and uncapped gaps", () => {
      const stack = buildTimelineStack([
        blockItem("09:30", "10:50"),
        gap("10:50", "11:10"),
        blockItem("11:10", "11:40"),
      ], PPM, windowOf("09:30", "11:40"))
      expect(stack.hourTicks.map((t) => t.minute)).toEqual([m("10:00"), m("11:00")])
      expect(stack.hourTicks.map((t) => t.topPx)).toEqual([60, 180])
    })

    it("omits hour ticks strictly inside a capped gap", () => {
      const stack = stackFor(fixtureBlocks(), FIXTURE_WINDOW)
      const minutes = stack.hourTicks.map((t) => t.minute)
      expect(minutes).not.toContain(m("13:00"))
      expect(minutes).not.toContain(m("14:00"))
    })

    it("omits hour ticks inside compressed leading and trailing stubs", () => {
      const minutes = stackFor(fixtureBlocks(), FIXTURE_WINDOW).hourTicks.map((t) => t.minute)
      for (const hour of ["06:00", "07:00", "08:00", "09:00", "17:00", "21:00"]) {
        expect(minutes).not.toContain(m(hour))
      }
      expect(minutes).toEqual(["05:00", "10:00", "12:00", "15:00", "16:00"].map(m))
    })

    it("keeps a tick that falls on a segment start", () => {
      const minutes = stackFor(fixtureBlocks(), FIXTURE_WINDOW).hourTicks.map((t) => t.minute)
      expect(minutes).toContain(m("15:00"))
      expect(minutes).toContain(m("16:00"))
    })
  })
})
