<script setup lang="ts">
import { computed } from "vue"
import type { TimeBlock, ScheduleWindow } from "../types"
import { buildBaseDisplayItems, minutesToTime, timeToMinutes } from "../utils/scheduleTime"
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

const start = computed(() => timeToMinutes(props.scheduleWindow.start))
const end = computed(() => timeToMinutes(props.scheduleWindow.end))
const axisOriginMinutes = computed(() => props.timelineOriginMinutes ?? Math.min(start.value, ...props.blocks.map((b) => timeToMinutes(b.start_time))))
const axisEndMinutes = computed(() => props.timelineEndMinutes ?? Math.max(end.value, ...props.blocks.map((b) => timeToMinutes(b.end_time))))
const canvasHeight = computed(() => (axisEndMinutes.value - axisOriginMinutes.value) * props.pxPerMinute)

// Build without compact stubs or per-slot now markers. The list is absolute,
// so its `duration_minutes` determines height and inert flow spacers vanish.
const items = computed(() => buildBaseDisplayItems(
  props.blocks,
  axisOriginMinutes.value,
  axisEndMinutes.value,
  null,
  { start: props.scheduleWindow.start, end: props.scheduleWindow.end, startMinutes: start.value, endMinutes: end.value },
).filter((item) => item.type !== "spacer"))

const hourTicks = computed(() => {
  const first = Math.ceil(axisOriginMinutes.value / 60) * 60
  const ticks: number[] = []
  for (let minute = first; minute < axisEndMinutes.value; minute += 60) ticks.push(minute)
  return ticks
})
const nowVisible = computed(() => props.nowDate !== null && props.nowMinutes !== null && props.nowMinutes >= axisOriginMinutes.value && props.nowMinutes < axisEndMinutes.value)
function topFor(time: string | number): string {
  const minutes = typeof time === "string" ? timeToMinutes(time) : time
  return `${(minutes - axisOriginMinutes.value) * props.pxPerMinute}px`
}
function heightFor(minutes: number): string { return `${minutes * props.pxPerMinute}px` }
const emit = defineEmits<{ "add-here": [payload: { start_time: string; end_time: string }] }>()

defineExpose({ timelineOriginMinutes: axisOriginMinutes, timelineEndMinutes: axisEndMinutes, canvasHeight })
</script>

<template>
  <section class="timeline-4a" :style="{ height: canvasHeight + 'px' }" data-testid="timeline-4a">
    <div v-for="tick in hourTicks" :key="tick" class="hour-tick" :style="{ top: topFor(tick) }">
      <span>{{ minutesToTime(tick) }}</span><i />
    </div>
    <div v-for="(item, index) in items" :key="`${item.type}:${item.start_time}:${index}`" class="timeline-item" :style="{ top: topFor(item.start_time), height: heightFor(item.duration_minutes) }">
      <TimeBlock4a v-if="item.type === 'block' && item.block" :block="item.block" :date="date" :is-current="item.block.id === currentBlockId" :remaining-minutes="item.block.id === currentBlockId ? currentBlockRemaining : null" />
      <GapSlot4a v-else-if="item.type === 'gap'" :start-time="item.start_time" :end-time="item.end_time" :duration-minutes="item.duration_minutes" :window-start="scheduleWindow.start" :disabled="disabled" @add-here="emit('add-here', $event)" />
    </div>
    <NowLine4a v-if="nowVisible" class="timeline-now" :style="{ top: topFor(nowMinutes!) }" />
  </section>
</template>

<style scoped>
.timeline-4a { position:relative; margin-left:42px; border-left:1px solid #26292d; }
.timeline-item { position:absolute; left:12px; right:0; }
.hour-tick { position:absolute; left:-43px; right:0; display:flex; align-items:center; gap:8px; transform:translateY(-50%); color:#6a6e75; font-size:11px; pointer-events:none; }
.hour-tick span { width:33px; text-align:right; }
.hour-tick i { height:1px; flex:1; background:#212428; }
.timeline-now { position:absolute; left:-43px; right:0; transform:translateY(-50%); z-index:4; }
</style>
