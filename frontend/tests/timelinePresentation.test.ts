import { describe, expect, it, vi } from "vitest"
import { ref } from "vue"
import type { TimeBlock } from "../src/types"
import { useDrag } from "../src/composables/useDrag"
import { createTimelinePresentation, useTimelinePresentation } from "../src/composables/useTimelinePresentation"
import { timeToMinutes, type ScheduleWindowBounds } from "../src/utils/scheduleTime"

const block: TimeBlock = {
  id: 1, title: "Work", start_time: "09:00", end_time: "10:00",
  category: "work", is_completed: false, sort_order: 0,
}

function container() {
  const element = document.createElement("div")
  element.setPointerCapture = vi.fn()
  element.releasePointerCapture = vi.fn()
  element.getBoundingClientRect = () => ({
    top: 0, left: 0, right: 600, bottom: 800, width: 600, height: 800,
    x: 0, y: 0, toJSON: () => ({}),
  }) as DOMRect
  return element
}

function setup(scale: number) {
  const blocks = ref([block])
  const date = ref("2026-10-11")
  const nowDate = ref("2026-10-11")
  const nowMinutes = ref(10 * 60 + 30)
  const window = ref<ScheduleWindowBounds>({
    start: "06:00", end: "23:00", startMinutes: 360, endMinutes: 1380,
  })
  const pxPerMinute = ref(scale)
  const context = ref("classic|UTC")
  let presentation: ReturnType<typeof useTimelinePresentation>
  const drag = useDrag(
    () => date.value, () => blocks.value, vi.fn(async () => ({ ok: false })),
    vi.fn(), () => blocks.value.map((item) => ({ ...item })),
    undefined, () => presentation.renderBounds.value,
    () => nowMinutes.value, () => window.value, () => pxPerMinute.value,
    () => presentation.timelineOriginMinutes.value, () => context.value,
  )
  presentation = useTimelinePresentation({
    getBlocks: () => blocks.value,
    getDate: () => date.value,
    getWindow: () => window.value,
    getNowMinutes: () => nowMinutes.value,
    getNowDate: () => nowDate.value,
    getPxPerMinute: () => pxPerMinute.value,
    getDragState: () => ({
      isDragging: drag.isDragging.value,
      previewBlocks: drag.previewBlocks.value,
      dragBlockId: drag.dragBlockId.value,
      frozenRenderBounds: drag.frozenRenderBounds.value,
      frozenNowMinutes: drag.frozenNowMinutes.value,
      frozenPxPerMinute: drag.frozenPxPerMinute.value,
      frozenTimelineOriginMinutes: drag.frozenTimelineOriginMinutes.value,
      frozenWindow: drag.frozenWindow.value,
    }),
  })
  return { blocks, date, nowDate, nowMinutes, window, pxPerMinute, context, drag, presentation }
}

describe("timeline presentation during drag", () => {
  it.each([2, 1.6])("keeps both renderer geometries frozen at %s px/minute while the clock ticks", (scale) => {
    const state = setup(scale)
    const before = state.presentation.presentation.value
    state.drag.startDrag({ pointerId: 1, clientY: 0 } as PointerEvent, block, container())
    const frozen = state.presentation.presentation.value
    expect(frozen.axisOriginMinutes).toBe(before.axisOriginMinutes)
    expect(frozen.axisEndMinutes).toBe(before.axisEndMinutes)
    expect(frozen.pxPerMinute).toBe(scale)
    expect(state.drag.frozenWindow.value).toEqual(state.window.value)
    const geometry = frozen.positionedItems.map(({ item, topPx, heightPx }) =>
      [item.type, item.start_time, topPx, heightPx])

    state.nowMinutes.value += 60
    const afterTick = state.presentation.presentation.value
    expect(afterTick.axisOriginMinutes).toBe(frozen.axisOriginMinutes)
    expect(afterTick.axisEndMinutes).toBe(frozen.axisEndMinutes)
    expect(afterTick.canvasHeightPx).toBe(frozen.canvasHeightPx)
    expect(afterTick.baseItems).toEqual(frozen.baseItems)
    expect(afterTick.positionedItems.map(({ item, topPx, heightPx }) =>
      [item.type, item.start_time, topPx, heightPx])).toEqual(geometry)
    expect(state.presentation.ghostHeight.value).toBe(60 * scale)
    state.drag.cancelDrag()
    expect(state.presentation.presentation.value.axisEndMinutes).toBeGreaterThan(frozen.axisEndMinutes)
  })

  it("uses preview blocks in both flow and positioned items", () => {
    const state = setup(1.6)
    state.drag.startDrag({ pointerId: 1, clientY: 0 } as PointerEvent, block, container())
    state.drag.previewBlocks.value = [{ ...block, start_time: "11:00", end_time: "12:00" }]
    const model = state.presentation.presentation.value
    expect(model.displayList.find((item) => item.type.startsWith("block"))?.start_time).toBe("11:00")
    expect(model.positionedItems.find(({ item }) => item.type === "block")?.topPx).toBe(
      (timeToMinutes("11:00") - model.axisOriginMinutes) * 1.6,
    )
    state.drag.cancelDrag()
  })

  it("maps a 4a pointer move to the displayed ghost time after a clock tick", () => {
    vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
      callback(0)
      return 0
    })
    try {
      const state = setup(1.6)
      const element = container()
      state.drag.startDrag({ pointerId: 1, clientY: 0 } as PointerEvent, block, element)
      const frozenOrigin = state.presentation.presentation.value.axisOriginMinutes
      state.nowMinutes.value += 60
      const move = new Event("pointermove")
      Object.defineProperty(move, "clientY", { value: 48 })
      element.dispatchEvent(move)

      expect(state.drag.previewStartTime.value).toBe("09:30")
      expect(state.drag.ghostTop.value).toBe((570 - frozenOrigin) * 1.6)
      expect(state.presentation.presentation.value.positionedItems
        .find(({ item }) => item.type === "block")?.topPx).toBe(state.drag.ghostTop.value)
      state.drag.cancelDrag()
    } finally {
      vi.unstubAllGlobals()
    }
  })

  it.each(["window", "theme", "date", "scale", "viewport"])("cancels when %s changes", (change) => {
    const state = setup(2)
    state.drag.startDrag({ pointerId: 1, clientY: 0 } as PointerEvent, block, container())
    expect(state.drag.isDragging.value).toBe(true)
    if (change === "window") state.window.value = {
      start: "08:00", end: "20:00", startMinutes: 480, endMinutes: 1200,
    }
    if (change === "theme") state.context.value = "strategic|UTC"
    if (change === "date") state.date.value = "2026-10-12"
    if (change === "scale") state.pxPerMinute.value = 1.6
    if (change === "viewport") window.dispatchEvent(new Event("resize"))
    expect(state.drag.isDragging.value).toBe(false)
    expect(state.drag.frozenWindow.value).toBeNull()
  })
})

describe("timeline presentation in stack mode (0106)", () => {
  const WINDOW: ScheduleWindowBounds = { start: "05:00", end: "22:00", startMinutes: 300, endMinutes: 1320 }
  const m = timeToMinutes
  function b(id: number, start: string, end: string, extra: Partial<TimeBlock> = {}): TimeBlock {
    return { id, title: `B${id}`, start_time: start, end_time: end, category: "work", is_completed: false, sort_order: id, ...extra }
  }
  const FIXTURE = [
    b(1, "09:40", "10:05"), b(2, "11:15", "11:40"), b(3, "11:40", "11:45"),
    b(4, "11:45", "12:10"), b(5, "15:00", "16:00"),
  ]
  function present(overrides: Partial<Parameters<typeof createTimelinePresentation>[0]> = {}) {
    return createTimelinePresentation({
      blocks: FIXTURE, date: "2026-11-22", window: WINDOW,
      nowMinutes: null, nowDate: null, pxPerMinute: 2, layoutMode: "stack", ...overrides,
    })
  }

  it("stack mode positions items from the stack", () => {
    const model = present()
    expect(model.canvasHeightPx).toBe(538)
    expect(model.positionedItems.map((p) => p.heightPx)).toEqual([60, 50, 60, 50, 28, 50, 60, 120, 60])
    expect(model.positionedItems.find((p) => p.item.block?.id === 3)?.compact).toBe(true)
    expect(model.axisMap).not.toBeNull()
  })

  it("linear mode is unchanged", () => {
    const linear = createTimelinePresentation({
      blocks: FIXTURE, date: "2026-11-22", window: WINDOW, nowMinutes: null, nowDate: null, pxPerMinute: 2,
    })
    expect(linear.axisMap).toBeNull()
    expect(linear.positionedItems.find((p) => p.item.block?.id === 3)?.heightPx).toBe(10)
    expect(linear.canvasHeightPx).toBe((linear.axisEndMinutes - linear.axisOriginMinutes) * 2)
  })

  it("places the now line inside a capped gap proportionally", () => {
    const model = present({ nowMinutes: m("13:35"), nowDate: "2026-11-22" })
    const gap = model.positionedItems.find((p) => p.item.type === "gap" && p.item.start_time === "12:10")!
    expect(model.nowVisible).toBe(true)
    expect(model.nowLineTopPx).toBeCloseTo(gap.topPx + 30)
  })

  it("keeps the trailing row's height, range and later hint before, during and after the old split (13:00, 17:00, 21:30)", () => {
    for (const now of ["13:00", "17:00", "21:30"]) {
      const model = present({ nowMinutes: m(now), nowDate: "2026-11-22" })
      const trailing = model.positionedItems.at(-1)!
      expect(trailing.item, now).toMatchObject({ type: "gap", start_time: "16:00", end_time: "22:00" })
      expect(trailing.heightPx, now).toBe(60)
      expect(trailing.edgeHint, now).toBe("later")
      expect(model.canvasHeightPx, now).toBe(538)
    }
  })

  it("renders an empty templated day as one capped gap", () => {
    const model = present({ blocks: [], nowMinutes: m("13:00"), nowDate: "2026-11-22" })
    expect(model.positionedItems).toHaveLength(1)
    expect(model.positionedItems[0].item).toMatchObject({ type: "gap", start_time: "05:00", end_time: "22:00" })
    expect(model.positionedItems[0].heightPx).toBe(60)
    expect(model.positionedItems[0].edgeHint).toBeNull()
  })

  it("hides an hour label that intersects the now label at an exact hour and a nearby minute", () => {
    const exact = present({ nowMinutes: m("10:00"), nowDate: "2026-11-22" })
    expect(exact.hourTicks.map((t) => t.minute)).not.toContain(m("10:00"))
    const near = present({ nowMinutes: m("10:02"), nowDate: "2026-11-22" })
    expect(near.hourTicks.map((t) => t.minute)).not.toContain(m("10:00"))
    const far = present({ nowMinutes: m("15:30"), nowDate: "2026-11-22" })
    expect(far.hourTicks.map((t) => t.minute)).toContain(m("10:00"))
  })

  it("hides the now line before the window, after its end and off today", () => {
    expect(present({ nowMinutes: m("04:30"), nowDate: "2026-11-22" }).nowVisible).toBe(false)
    expect(present({ nowMinutes: m("22:30"), nowDate: "2026-11-22" }).nowVisible).toBe(false)
    expect(present({ nowMinutes: m("13:00"), nowDate: "2026-11-21" }).nowVisible).toBe(false)
    expect(present({ nowMinutes: m("13:00"), nowDate: "2026-11-22" }).nowVisible).toBe(true)
  })

  it("ghost height equals the stacked height (28px for a 5-minute block)", () => {
    const blocks = ref([...FIXTURE])
    const presentation = useTimelinePresentation({
      getBlocks: () => blocks.value, getDate: () => "2026-11-22", getWindow: () => WINDOW,
      getNowMinutes: () => null, getNowDate: () => null, getPxPerMinute: () => 2,
      getLayoutMode: () => "stack",
      getDragState: () => ({
        isDragging: true, previewBlocks: [], dragBlockId: 3,
        frozenRenderBounds: null, frozenNowMinutes: null, frozenPxPerMinute: 2,
        frozenTimelineOriginMinutes: null, frozenWindow: WINDOW,
      }),
    })
    expect(presentation.ghostHeight.value).toBe(28)
  })

  it("ghost readout uses the rounded duration of an off-grid import", () => {
    const blocks = ref([b(9, "14:07", "14:33")])
    const presentation = useTimelinePresentation({
      getBlocks: () => blocks.value, getDate: () => "2026-11-22", getWindow: () => WINDOW,
      getNowMinutes: () => null, getNowDate: () => null, getPxPerMinute: () => 2,
      getLayoutMode: () => "stack",
      getDragState: () => ({
        isDragging: true, previewBlocks: [], dragBlockId: 9,
        frozenRenderBounds: null, frozenNowMinutes: null, frozenPxPerMinute: 2,
        frozenTimelineOriginMinutes: null, frozenWindow: WINDOW,
      }),
    })
    expect(presentation.ghostDuration.value).toBe("30m")
  })

  it("freezes the axis map during drag and keeps untouched blocks in place", () => {
    const frozenBefore = present({ nowMinutes: m("13:00"), nowDate: "2026-11-22" })
    const dragging = present({
      nowMinutes: m("14:00"), nowDate: "2026-11-22",
      drag: {
        isDragging: true, dragBlockId: 3,
        previewBlocks: [b(1, "09:40", "10:05"), b(2, "11:15", "11:40"), b(4, "11:45", "12:10"), b(3, "13:00", "13:05"), b(5, "15:00", "16:00")],
        frozenRenderBounds: null, frozenNowMinutes: m("13:00"), frozenPxPerMinute: 2,
        frozenTimelineOriginMinutes: null, frozenWindow: WINDOW,
      },
    })
    expect(dragging.positionedItems.map((p) => [p.item.type, p.item.start_time, p.topPx, p.heightPx]))
      .toEqual(frozenBefore.positionedItems.map((p) => [p.item.type, p.item.start_time, p.topPx, p.heightPx]))
    expect(dragging.effectiveBlocks.find((x) => x.id === 3)?.start_time).toBe("13:00")
  })
})
