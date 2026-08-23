<script setup lang="ts">
import { computed } from "vue"
import type { TimeBlock, ScheduleWindow } from "../types"
import {
  buildBaseDisplayItems,
  computeRenderBounds,
  minutesToTime,
  nowOffsetPercent,
  timeToMinutes,
  type ScheduleDisplayItem,
  type ScheduleWindowBounds,
} from "../utils/scheduleTime"
import TimeBlock4a from "./TimeBlock4a.vue"
import GapSlot4a from "./GapSlot4a.vue"
import NowLine4a from "./NowLine4a.vue"

const props = defineProps<{
  blocks: TimeBlock[]
  date: string
  scheduleWindow: ScheduleWindow
  nowMinutes: number | null
  nowDate: string | null
  pxPerMinute: number
  timelineOriginMinutes?: number
  timelineEndMinutes?: number
  currentBlockId?: number | null
  currentBlockRemaining?: number | null
  disabled: boolean
}>()

const windowBounds = computed((): ScheduleWindowBounds => ({
  start: props.scheduleWindow.start,
  end: props.scheduleWindow.end,
  startMinutes: timeToMinutes(props.scheduleWindow.start),
  endMinutes: timeToMinutes(props.scheduleWindow.end),
}))
// Same contract as classic: nowMinutes is non-null only on the viewed today.
const todayNowMinutes = computed(() =>
  props.nowDate !== null && props.nowDate === props.date ? props.nowMinutes : null,
)
const compactBounds = computed(() =>
  computeRenderBounds(props.blocks, todayNowMinutes.value, windowBounds.value),
)
// Origin defaults to 0017 renderStart so omitted props still compress edges.
const axisOriginMinutes = computed(() => props.timelineOriginMinutes ?? compactBounds.value.renderStart)
const axisEndMinutes = computed(() => props.timelineEndMinutes ?? compactBounds.value.renderEnd)
const canvasHeight = computed(() => (axisEndMinutes.value - axisOriginMinutes.value) * props.pxPerMinute)

const items = computed(() => buildBaseDisplayItems(
  props.blocks,
  axisOriginMinutes.value,
  axisEndMinutes.value,
  todayNowMinutes.value,
  windowBounds.value,
).filter((item) => item.type !== "spacer"))

const hourTicks = computed(() => {
  const first = Math.ceil(axisOriginMinutes.value / 60) * 60
  const ticks: number[] = []
  for (let minute = first; minute < axisEndMinutes.value; minute += 60) ticks.push(minute)
  return ticks
})

function visualStartMinutes(item: ScheduleDisplayItem): number {
  const start = timeToMinutes(item.start_time)
  // Pin compact leading stub to origin so top stays non-negative.
  if (item.compact && start < axisOriginMinutes.value) return axisOriginMinutes.value
  return start
}
function visualMinutes(item: ScheduleDisplayItem): number {
  return item.render_minutes ?? item.duration_minutes
}
function topFor(time: string | number): string {
  const minutes = typeof time === "string" ? timeToMinutes(time) : time
  return `${(minutes - axisOriginMinutes.value) * props.pxPerMinute}px`
}
function itemTop(item: ScheduleDisplayItem): string {
  return topFor(visualStartMinutes(item))
}
function itemHeight(item: ScheduleDisplayItem): string {
  return `${visualMinutes(item) * props.pxPerMinute}px`
}

const leadingCompactGap = computed(() =>
  items.value.find(
    (item) =>
      item.compact === true &&
      item.type === "gap" &&
      item.start_time === props.scheduleWindow.start,
  ),
)
function nowInLeadingStub(now: number): boolean {
  const stub = leadingCompactGap.value
  if (!stub) return false
  return now >= timeToMinutes(stub.start_time) && now < timeToMinutes(stub.end_time)
}
const nowVisible = computed(() => {
  if (props.nowDate === null || props.nowMinutes === null || props.nowDate !== props.date) {
    return false
  }
  const now = props.nowMinutes
  if (now >= axisOriginMinutes.value && now < axisEndMinutes.value) return true
  return nowInLeadingStub(now)
})
const nowLineTop = computed(() => {
  const now = props.nowMinutes
  if (now === null) return "0px"
  if (now >= axisOriginMinutes.value && now < axisEndMinutes.value) return topFor(now)
  const stub = leadingCompactGap.value
  if (stub && nowInLeadingStub(now)) {
    const pct = Number.parseFloat(nowOffsetPercent(stub.start_time, stub.end_time, now)) / 100
    const top =
      (visualStartMinutes(stub) - axisOriginMinutes.value) * props.pxPerMinute +
      pct * visualMinutes(stub) * props.pxPerMinute
    return `${top}px`
  }
  return topFor(now)
})
const emit = defineEmits<{ "add-here": [payload: { start_time: string; end_time: string }] }>()

defineExpose({ timelineOriginMinutes: axisOriginMinutes, timelineEndMinutes: axisEndMinutes, canvasHeight })
</script>

<template>
  <section class="timeline-4a" :style="{ height: canvasHeight + 'px' }" data-testid="timeline-4a">
    <div v-for="tick in hourTicks" :key="tick" class="hour-tick" :style="{ top: topFor(tick) }">
      <span>{{ minutesToTime(tick) }}</span><i />
    </div>
    <div v-for="(item, index) in items" :key="`${item.type}:${item.start_time}:${index}`" class="timeline-item" :style="{ top: itemTop(item), height: itemHeight(item) }">
      <TimeBlock4a v-if="item.type === 'block' && item.block" :block="item.block" :date="date" :is-current="item.block.id === currentBlockId" :remaining-minutes="item.block.id === currentBlockId ? currentBlockRemaining : null" />
      <GapSlot4a v-else-if="item.type === 'gap'" :start-time="item.start_time" :end-time="item.end_time" :duration-minutes="item.duration_minutes" :compact="item.compact" :window-start="scheduleWindow.start" :disabled="disabled" @add-here="emit('add-here', $event)" />
    </div>
    <NowLine4a v-if="nowVisible" class="timeline-now" :style="{ top: nowLineTop }" />
  </section>
</template>

<style scoped>
.timeline-4a { position:relative; margin-left:var(--timeline-4a-axis-gutter, 42px); border-left:1px solid #26292d; }
.timeline-item { position:absolute; left:var(--timeline-4a-item-inset, 12px); right:0; }
.hour-tick { position:absolute; left:calc(-1 * var(--timeline-4a-axis-gutter, 42px) - 1px); right:0; display:flex; align-items:center; gap:8px; transform:translateY(-50%); color:#6a6e75; font-size:11px; pointer-events:none; }
.hour-tick span { width:33px; text-align:right; }
.hour-tick i { height:1px; flex:1; background:#212428; }
.timeline-now { position:absolute; left:calc(-1 * var(--timeline-4a-axis-gutter, 42px) - 1px); right:0; transform:translateY(-50%); z-index:4; }
</style>
