import { computed } from "vue"
import type { TimeBlock } from "../types"
import {
  buildBaseDisplayItems,
  computeRenderBounds,
  findCurrentBlock,
  formatDurationMinutes,
  nowOffsetPercent as computeNowOffsetPercent,
  remainingMinutesForBlock,
  spliceNowMarker,
  timeToMinutes,
  type RenderBounds,
  type ScheduleDisplayItem,
  type ScheduleWindowBounds,
} from "../utils/scheduleTime"
import { clampedDragDuration } from "./useDrag"
import { buildTimelineStack, type AxisMap } from "../utils/timelineStack"

export type TimelineLayoutMode = "linear" | "stack"

// The now label and an hour label share the axis gutter; an hour label
// closer than this to the now line is hidden so the now label wins (0106).
export const NOW_LABEL_CLEARANCE_PX = 18

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
  /** "stack" is the Dark 4a layout (feature 0106); "linear" is the default. */
  layoutMode?: TimelineLayoutMode
}

export interface PositionedTimelineItem {
  item: ScheduleDisplayItem
  topPx: number
  heightPx: number
  /** Stack mode: a block rendered below the compact threshold. */
  compact?: boolean
  /** Stack mode: rendered shorter than its true scale. */
  compressed?: boolean
  /** Stack mode: "earlier" / "later" on a compressed edge gap. */
  edgeHint?: "earlier" | "later" | null
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
  layoutMode: TimelineLayoutMode
  /** Piecewise minute↔pixel map; null in linear mode. */
  axisMap: AxisMap | null
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
  const currentBlock = input.nowMinutes === null
    ? null
    : findCurrentBlock(effectiveBlocks, input.nowMinutes, input.nowDate)
  const currentBlockRemaining = currentBlock && input.nowMinutes !== null
    ? remainingMinutesForBlock(currentBlock, input.nowMinutes)
    : null

  if (input.layoutMode === "stack") {
    // The stacked column stays frozen for the whole gesture: it is built from
    // the canonical blocks with the drag-start clock, and the ghost floats
    // over it (feature 0106). Preview blocks only feed effectiveBlocks.
    const stackBlocks = input.blocks
    const stackBounds = drag?.frozenRenderBounds ??
      computeRenderBounds(stackBlocks, geometryNow, window)
    const baseItems = buildBaseDisplayItems(
      stackBlocks, stackBounds.renderStart, stackBounds.renderEnd, geometryNow, window,
    )
    const stack = buildTimelineStack(baseItems, pxPerMinute, window)
    const positionedItems = stack.items.map((entry) => ({
      item: entry.item,
      topPx: entry.topPx,
      heightPx: entry.heightPx,
      compact: entry.compact,
      compressed: entry.compressed,
      edgeHint: entry.edgeHint,
    }))
    const nowSegment = todayNow === null ? null : stack.segmentAt(todayNow)
    const nowVisible = nowSegment !== null && nowSegment.kind !== "spacer"
    const nowLineTopPx = todayNow === null ? 0 : stack.timeToPx(todayNow)
    const hourTicks = nowVisible
      ? stack.hourTicks.filter((tick) => Math.abs(tick.topPx - nowLineTopPx) >= NOW_LABEL_CLEARANCE_PX)
      : stack.hourTicks
    return {
      bounds: stackBounds, window,
      axisOriginMinutes: stack.segments[0]?.startMin ?? window.startMinutes,
      axisEndMinutes: stack.segments.at(-1)?.endMin ?? window.endMinutes,
      pxPerMinute,
      canvasHeightPx: stack.canvasHeightPx,
      effectiveBlocks, baseItems,
      displayList: spliceNowMarker(baseItems, input.nowMinutes, input.nowDate),
      positionedItems, hourTicks, currentBlock, currentBlockRemaining,
      nowVisible, nowLineTopPx,
      layoutMode: "stack",
      axisMap: { segments: stack.segments, timeToPx: stack.timeToPx, pxToTime: stack.pxToTime },
    }
  }

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
    layoutMode: "linear", axisMap: null,
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
  getLayoutMode?: () => TimelineLayoutMode
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
    layoutMode: options.getLayoutMode?.() ?? "linear",
  }))
  const timelineOriginMinutes = computed(() => presentation.value.axisOriginMinutes)
  const effectiveBlocks = computed(() => presentation.value.effectiveBlocks)
  const currentBlock = computed(() => presentation.value.currentBlock)
  const currentBlockRemaining = computed(() => presentation.value.currentBlockRemaining)
  const displayList = computed(() => presentation.value.displayList)
  const draggedBlock = computed(() => {
    const drag = options.getDragState()
    return drag?.dragBlockId === null || drag?.dragBlockId === undefined
      ? null : options.getBlocks().find((item) => item.id === drag.dragBlockId) ?? null
  })
  // Stack mode keeps the dragged item's rendered height at drag start (a
  // 5-minute block is 28 px, not 10); linear mode draws duration × scale.
  const ghostHeight = computed(() => {
    const block = draggedBlock.value
    if (!block) return 0
    if (presentation.value.layoutMode === "stack") {
      const stacked = presentation.value.positionedItems.find((entry) => entry.item.block?.id === block.id)
      if (stacked) return stacked.heightPx
    }
    return clampedDragDuration(block) * presentation.value.pxPerMinute
  })
  // The ghost readout shows the snapped, rounded duration a drop submits.
  const ghostDuration = computed(() =>
    draggedBlock.value ? formatDurationMinutes(clampedDragDuration(draggedBlock.value)) : "")
  const axisMap = computed(() => presentation.value.axisMap)
  const itemHeight = (item: ScheduleDisplayItem): string =>
    `${renderedMinutes(item) * presentation.value.pxPerMinute}px`
  const nowOffsetPercent = (item: ScheduleDisplayItem): string =>
    computeNowOffsetPercent(item.start_time, item.end_time, options.getNowMinutes())

  return {
    renderBounds, timelineOriginMinutes,
    effectiveBlocks, currentBlock, currentBlockRemaining, displayList,
    ghostHeight, ghostDuration, axisMap, itemHeight, nowOffsetPercent, presentation,
  }
}
