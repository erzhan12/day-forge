<script setup lang="ts">
import { computed } from "vue"
import type { TimeBlock, ScheduleWindow, UserCategory } from "../types"
import {
  minutesToTime,
  timeToMinutes,
  type ScheduleWindowBounds,
} from "../utils/scheduleTime"
import { createTimelinePresentation, type TimelinePresentation } from "../composables/useTimelinePresentation"
import TimeBlock4a from "./TimeBlock4a.vue"
import GapSlot4a from "./GapSlot4a.vue"
import NowLine4a from "./NowLine4a.vue"

const props = defineProps<{
  blocks: TimeBlock[]
  date: string
  scheduleWindow: ScheduleWindow
  nowMinutes: number | null
  nowDate: string | null
  currentHHMM?: string
  pxPerMinute: number
  timelineOriginMinutes?: number
  timelineEndMinutes?: number
  currentBlockId?: number | null
  currentBlockRemaining?: number | null
  presentation?: TimelinePresentation
  disabled: boolean
  categories: UserCategory[]
}>()

const windowBounds = computed((): ScheduleWindowBounds => ({
  start: props.scheduleWindow.start,
  end: props.scheduleWindow.end,
  startMinutes: timeToMinutes(props.scheduleWindow.start),
  endMinutes: timeToMinutes(props.scheduleWindow.end),
}))
const nowLabel = computed(() =>
  props.currentHHMM ?? (props.nowMinutes === null ? "" : minutesToTime(props.nowMinutes)),
)
// Standalone callers use the same model builder as Schedule.vue.
const model = computed(() => props.presentation ?? createTimelinePresentation({
  blocks: props.blocks,
  date: props.date,
  window: windowBounds.value,
  nowMinutes: props.nowMinutes,
  nowDate: props.nowDate,
  pxPerMinute: props.pxPerMinute,
  axisOriginMinutes: props.timelineOriginMinutes,
  axisEndMinutes: props.timelineEndMinutes,
}))
const axisOriginMinutes = computed(() => model.value.axisOriginMinutes)
const axisEndMinutes = computed(() => model.value.axisEndMinutes)
const canvasHeight = computed(() => model.value.canvasHeightPx)
const currentBlockId = computed(() =>
  props.currentBlockId === undefined ? model.value.currentBlock?.id ?? null : props.currentBlockId,
)
const currentBlockRemaining = computed(() =>
  props.currentBlockRemaining === undefined
    ? model.value.currentBlockRemaining
    : props.currentBlockRemaining,
)
const emit = defineEmits<{ "add-here": [payload: { start_time: string; end_time: string }] }>()

defineExpose({ timelineOriginMinutes: axisOriginMinutes, timelineEndMinutes: axisEndMinutes, canvasHeight })
</script>

<template>
  <section class="timeline-4a" :style="{ height: canvasHeight + 'px' }" data-testid="timeline-4a">
    <div v-for="tick in model.hourTicks" :key="tick.minute" class="hour-tick" :style="{ top: tick.topPx + 'px' }">
      <span>{{ minutesToTime(tick.minute) }}</span><i />
    </div>
    <div v-for="(positioned, index) in model.positionedItems" :key="`${positioned.item.type}:${positioned.item.start_time}:${index}`" class="timeline-item" :style="{ top: positioned.topPx + 'px', height: positioned.heightPx + 'px' }">
      <TimeBlock4a v-if="positioned.item.type === 'block' && positioned.item.block" :block="positioned.item.block" :date="date" :categories="categories" :is-current="positioned.item.block.id === currentBlockId" :remaining-minutes="positioned.item.block.id === currentBlockId ? currentBlockRemaining : null" />
      <GapSlot4a v-else-if="positioned.item.type === 'gap'" :start-time="positioned.item.start_time" :end-time="positioned.item.end_time" :duration-minutes="positioned.item.duration_minutes" :compact="positioned.item.compact" :window-start="model.window.start" :disabled="disabled" @add-here="emit('add-here', $event)" />
    </div>
    <NowLine4a v-if="model.nowVisible" class="timeline-now" :label="nowLabel" :style="{ top: model.nowLineTopPx + 'px' }" />
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
