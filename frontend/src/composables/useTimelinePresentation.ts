import { computed } from "vue"
import type { TimeBlock } from "../types"
import {
  buildBaseDisplayItems,
  computeRenderBounds,
  findCurrentBlock,
  nowOffsetPercent as computeNowOffsetPercent,
  remainingMinutesForBlock,
  spliceNowMarker,
  timeToMinutes,
  type RenderBounds,
  type ScheduleDisplayItem,
  type ScheduleWindowBounds,
} from "../utils/scheduleTime"
import { clampedDragDuration } from "./useDrag"

export interface TimelineDragState {
  isDragging: boolean
  previewBlocks: TimeBlock[]
  dragBlockId: number | null
  frozenRenderBounds: RenderBounds | null
  frozenNowMinutes: number | null
  frozenPxPerMinute: number
  frozenTimelineOriginMinutes: number | null
  frozenWindow: ScheduleWindowBounds | null
}

export interface TimelinePresentationInput {
  blocks: TimeBlock[]
  date: string
  window: ScheduleWindowBounds
  nowMinutes: number | null
  nowDate: string | null
  pxPerMinute: number
  drag?: TimelineDragState | null
  liveRenderBounds?: RenderBounds
  axisOriginMinutes?: number
  axisEndMinutes?: number
}

export interface PositionedTimelineItem {
  item: ScheduleDisplayItem
  topPx: number
  heightPx: number
}

export interface TimelinePresentation {
  bounds: RenderBounds
  window: ScheduleWindowBounds
  axisOriginMinutes: number
  axisEndMinutes: number
  pxPerMinute: number
  canvasHeightPx: number
  effectiveBlocks: TimeBlock[]
  baseItems: ScheduleDisplayItem[]
  displayList: ScheduleDisplayItem[]
  positionedItems: PositionedTimelineItem[]
  hourTicks: Array<{ minute: number; topPx: number }>
  currentBlock: TimeBlock | null
  currentBlockRemaining: number | null
  nowVisible: boolean
  nowLineTopPx: number
}

function renderedMinutes(item: ScheduleDisplayItem): number {
  return item.render_minutes ?? item.duration_minutes
}

function visualStartMinutes(item: ScheduleDisplayItem, origin: number): number {
  const start = timeToMinutes(item.start_time)
  return item.compact && start < origin ? origin : start
}

/** The geometry shared by the flow and absolute-positioned timeline renderers. */
export function createTimelinePresentation(input: TimelinePresentationInput): TimelinePresentation {
  const drag = input.drag?.isDragging ? input.drag : null
  const window = drag?.frozenWindow ?? input.window
  const effectiveBlocks = drag && drag.previewBlocks.length > 0
    ? drag.previewBlocks
    : input.blocks
  const todayNow = input.nowDate === input.date ? input.nowMinutes : null
  const geometryNow = drag ? drag.frozenNowMinutes : todayNow
  const bounds = drag?.frozenRenderBounds ?? input.liveRenderBounds ??
    computeRenderBounds(input.blocks, todayNow, input.window)
  const axisOriginMinutes = drag?.frozenTimelineOriginMinutes ??
    (drag?.frozenRenderBounds ? drag.frozenRenderBounds.renderStart : input.axisOriginMinutes ?? bounds.renderStart)
  const axisEndMinutes = drag?.frozenRenderBounds?.renderEnd ?? input.axisEndMinutes ?? bounds.renderEnd
  const pxPerMinute = drag ? drag.frozenPxPerMinute : input.pxPerMinute

  const baseItems = buildBaseDisplayItems(
    effectiveBlocks, axisOriginMinutes, axisEndMinutes, geometryNow, window,
  )
  const displayList = spliceNowMarker(baseItems, input.nowMinutes, input.nowDate)
  const positionedItems = baseItems
    .filter((item) => item.type !== "spacer")
    .map((item) => ({
      item,
      topPx: (visualStartMinutes(item, axisOriginMinutes) - axisOriginMinutes) * pxPerMinute,
      heightPx: renderedMinutes(item) * pxPerMinute,
    }))
  const hourTicks: Array<{ minute: number; topPx: number }> = []
  for (let minute = Math.ceil(axisOriginMinutes / 60) * 60; minute < axisEndMinutes; minute += 60) {
    hourTicks.push({ minute, topPx: (minute - axisOriginMinutes) * pxPerMinute })
  }

  const currentBlock = input.nowMinutes === null
    ? null
    : findCurrentBlock(effectiveBlocks, input.nowMinutes, input.nowDate)
  const currentBlockRemaining = currentBlock && input.nowMinutes !== null
    ? remainingMinutesForBlock(currentBlock, input.nowMinutes)
    : null

  const leadingStub = baseItems.find((item) =>
    item.type === "gap" && item.compact && item.start_time === window.start,
  )
  const nowInLeadingStub = input.nowMinutes !== null && leadingStub !== undefined &&
    input.nowMinutes >= timeToMinutes(leadingStub.start_time) &&
    input.nowMinutes < timeToMinutes(leadingStub.end_time)
  const nowVisible = todayNow !== null && (
    (todayNow >= axisOriginMinutes && todayNow < axisEndMinutes) || nowInLeadingStub
  )
  let nowLineTopPx = todayNow === null ? 0 : (todayNow - axisOriginMinutes) * pxPerMinute
  if (nowInLeadingStub && leadingStub && todayNow !== null &&
      (todayNow < axisOriginMinutes || todayNow >= axisEndMinutes)) {
    const percent = Number.parseFloat(computeNowOffsetPercent(
      leadingStub.start_time, leadingStub.end_time, todayNow,
    )) / 100
    nowLineTopPx = (visualStartMinutes(leadingStub, axisOriginMinutes) - axisOriginMinutes) * pxPerMinute +
      percent * renderedMinutes(leadingStub) * pxPerMinute
  }

  return {
    bounds, window, axisOriginMinutes, axisEndMinutes, pxPerMinute,
    canvasHeightPx: (axisEndMinutes - axisOriginMinutes) * pxPerMinute,
    effectiveBlocks, baseItems, displayList, positionedItems, hourTicks,
    currentBlock, currentBlockRemaining, nowVisible, nowLineTopPx,
  }
}

export interface UseTimelinePresentationOptions {
  getBlocks: () => TimeBlock[]
  getDate: () => string
  getWindow: () => ScheduleWindowBounds
  getNowMinutes: () => number | null
  getNowDate: () => string | null
  getPxPerMinute: () => number
  getDragState: () => TimelineDragState | null
}

export function useTimelinePresentation(options: UseTimelinePresentationOptions) {
  const renderBounds = computed(() => computeRenderBounds(
    options.getBlocks(),
    options.getNowDate() === options.getDate() ? options.getNowMinutes() : null,
    options.getWindow(),
  ))
  const presentation = computed(() => createTimelinePresentation({
    blocks: options.getBlocks(),
    date: options.getDate(),
    window: options.getWindow(),
    nowMinutes: options.getNowMinutes(),
    nowDate: options.getNowDate(),
    pxPerMinute: options.getPxPerMinute(),
    drag: options.getDragState(),
    liveRenderBounds: renderBounds.value,
  }))
  const timelineOriginMinutes = computed(() => presentation.value.axisOriginMinutes)
  const timelineEndMinutes = computed(() => presentation.value.axisEndMinutes)
  const effectiveBlocks = computed(() => presentation.value.effectiveBlocks)
  const currentBlock = computed(() => presentation.value.currentBlock)
  const currentBlockRemaining = computed(() => presentation.value.currentBlockRemaining)
  const displayList = computed(() => presentation.value.displayList)
  const ghostHeight = computed(() => {
    const drag = options.getDragState()
    const block = drag?.dragBlockId === null || drag?.dragBlockId === undefined
      ? null : options.getBlocks().find((item) => item.id === drag.dragBlockId)
    return block ? clampedDragDuration(block) * presentation.value.pxPerMinute : 0
  })
  const ghostIsCompact = computed(() => {
    const drag = options.getDragState()
    const block = drag?.dragBlockId === null || drag?.dragBlockId === undefined
      ? null : options.getBlocks().find((item) => item.id === drag.dragBlockId)
    return block ? clampedDragDuration(block) <= 30 : false
  })
  const itemHeight = (item: ScheduleDisplayItem): string =>
    `${renderedMinutes(item) * presentation.value.pxPerMinute}px`
  const nowOffsetPercent = (item: ScheduleDisplayItem): string =>
    computeNowOffsetPercent(item.start_time, item.end_time, options.getNowMinutes())

  return {
    renderBounds, timelineOriginMinutes, timelineEndMinutes,
    effectiveBlocks, currentBlock, currentBlockRemaining, displayList,
    ghostHeight, ghostIsCompact, itemHeight, nowOffsetPercent, presentation,
  }
}
