import { describe, expect, it, vi } from "vitest"
import { ref } from "vue"
import type { TimeBlock } from "../src/types"
import { useDrag } from "../src/composables/useDrag"
import { useTimelinePresentation } from "../src/composables/useTimelinePresentation"
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
