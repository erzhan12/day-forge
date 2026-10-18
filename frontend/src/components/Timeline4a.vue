<script setup lang="ts">
import { computed } from "vue"
import type { UserCategory } from "../types"
import { minutesToTime } from "../utils/scheduleTime"
import type { TimelinePresentation } from "../composables/useTimelinePresentation"
import TimeBlock4a from "./TimeBlock4a.vue"
import GapSlot4a from "./GapSlot4a.vue"
import NowLine4a from "./NowLine4a.vue"

const props = defineProps<{
  date: string
  currentHHMM: string
  presentation: TimelinePresentation
  disabled: boolean
  categories: UserCategory[]
}>()

const currentBlockId = computed(() => props.presentation.currentBlock?.id ?? null)
const emit = defineEmits<{ "add-here": [payload: { start_time: string; end_time: string }] }>()
</script>

<template>
  <section class="timeline-4a" :style="{ height: presentation.canvasHeightPx + 'px' }" data-testid="timeline-4a">
    <div v-for="tick in presentation.hourTicks" :key="tick.minute" class="hour-tick" :style="{ top: tick.topPx + 'px' }">
      <span>{{ minutesToTime(tick.minute) }}</span><i />
    </div>
    <div v-for="(positioned, index) in presentation.positionedItems" :key="`${positioned.item.type}:${positioned.item.start_time}:${index}`" class="timeline-item" :style="{ top: positioned.topPx + 'px', height: positioned.heightPx + 'px' }">
      <TimeBlock4a v-if="positioned.item.type === 'block' && positioned.item.block" :block="positioned.item.block" :date="date" :categories="categories" :is-current="positioned.item.block.id === currentBlockId" :remaining-minutes="positioned.item.block.id === currentBlockId ? presentation.currentBlockRemaining : null" />
      <GapSlot4a v-else-if="positioned.item.type === 'gap'" :start-time="positioned.item.start_time" :end-time="positioned.item.end_time" :duration-minutes="positioned.item.duration_minutes" :compact="positioned.item.compact" :window-start="presentation.window.start" :disabled="disabled" @add-here="emit('add-here', $event)" />
    </div>
    <NowLine4a v-if="presentation.nowVisible" class="timeline-now" :label="currentHHMM" :style="{ top: presentation.nowLineTopPx + 'px' }" />
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
