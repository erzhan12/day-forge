<script setup lang="ts">
import { computed, ref, provide, onMounted, onUnmounted } from "vue"
import { router } from "@inertiajs/vue3"
import type { TimeBlock as TimeBlockType, Schedule, RenderItem } from "../types"
import DateNavigator from "../components/DateNavigator.vue"
import TimeBlock from "../components/TimeBlock.vue"
import GapSlot from "../components/GapSlot.vue"
import AddBlockForm from "../components/AddBlockForm.vue"
import NowLine from "../components/NowLine.vue"
import UndoToast from "../components/UndoToast.vue"
import CommandBar from "../components/CommandBar.vue"
import { todayString } from "../utils/date"
import {
  DAY_START, DAY_END, DAY_START_MINUTES, DAY_END_MINUTES,
  PX_PER_MINUTE, timeToMinutes, minutesToTime,
} from "../utils/scheduleTime"
import { useSchedule } from "../composables/useSchedule"
import { useUndo } from "../composables/useUndo"
import { useDrag } from "../composables/useDrag"
import "../app.css"

// Extend RenderItem with overlay variants for items containing the current time
interface DisplayItem {
  type: "block" | "gap" | "block-with-now" | "gap-with-now"
  block?: TimeBlockType
  start_time: string
  end_time: string
  duration_minutes: number
}

const props = defineProps<{
  schedule: Schedule
  blocks: TimeBlockType[]
  date: string
}>()

const prefillStart = ref<string | undefined>()
const prefillEnd = ref<string | undefined>()
const scheduleBodyRef = ref<HTMLElement | null>(null)

// Initialize composables
const { reorderBlocks } = useSchedule(props.date)
const getBlocks = () => props.blocks
const {
  currentToast, pushUndo, performUndo, snapshotBlocks, dismissToast,
} = useUndo(props.date, getBlocks)
const {
  isDragging, dragBlockId, ghostTop, previewStartTime, previewEndTime,
  previewBlocks, shiftedBlockIds, startDrag, endDrag, cancelDrag,
} = useDrag(props.date, getBlocks, reorderBlocks, pushUndo, snapshotBlocks)

// Provide to child components
provide("undo", { pushUndo, snapshotBlocks })
provide("drag", { startDrag, isDragging, dragBlockId, shiftedBlockIds })
provide("scheduleContainer", scheduleBodyRef)

const isToday = computed(() => props.date === todayString())

// Reactive current-minute counter so display list recomputes as time passes
const NOW_UPDATE_INTERVAL_MS = 60_000
const nowMinutes = ref(getCurrentMinutes())
let nowInterval: ReturnType<typeof setInterval> | null = null

function getCurrentMinutes(): number {
  const now = new Date()
  return now.getHours() * 60 + now.getMinutes()
}

onMounted(() => {
  if (!isToday.value) return
  nowInterval = setInterval(() => {
    nowMinutes.value = getCurrentMinutes()
  }, NOW_UPDATE_INTERVAL_MS)
})

onUnmounted(() => {
  if (nowInterval) clearInterval(nowInterval)
})

// During drag, use preview blocks for real-time visual feedback
const effectiveBlocks = computed(() =>
  isDragging.value && previewBlocks.value.length > 0
    ? previewBlocks.value
    : props.blocks,
)

// Ghost element computed properties
const draggedBlock = computed(() =>
  dragBlockId.value !== null
    ? props.blocks.find((b) => b.id === dragBlockId.value)
    : null,
)
const ghostHeight = computed(() => {
  if (!draggedBlock.value) return 0
  const dur = timeToMinutes(draggedBlock.value.end_time) - timeToMinutes(draggedBlock.value.start_time)
  return dur * PX_PER_MINUTE
})
const ghostIsCompact = computed(() => {
  if (!draggedBlock.value) return false
  const dur = timeToMinutes(draggedBlock.value.end_time) - timeToMinutes(draggedBlock.value.start_time)
  return dur <= 30
})

// Build the display list: blocks and gaps with the now marker spliced in.
const displayList = computed<DisplayItem[]>(() => {
  const blocks = effectiveBlocks.value
  const baseItems: RenderItem[] = []

  // Filter blocks to those overlapping the visible day window
  const visibleBlocks = blocks.filter(
    (b) => timeToMinutes(b.end_time) > DAY_START_MINUTES && timeToMinutes(b.start_time) < DAY_END_MINUTES
  )

  if (visibleBlocks.length === 0) {
    baseItems.push({
      type: "gap",
      start_time: DAY_START,
      end_time: DAY_END,
      duration_minutes: DAY_END_MINUTES - DAY_START_MINUTES,
    })
  } else {
    // Gap before first block
    const firstStart = Math.max(timeToMinutes(visibleBlocks[0].start_time), DAY_START_MINUTES)
    if (firstStart > DAY_START_MINUTES) {
      baseItems.push({
        type: "gap",
        start_time: DAY_START,
        end_time: minutesToTime(firstStart),
        duration_minutes: firstStart - DAY_START_MINUTES,
      })
    }

    for (let i = 0; i < visibleBlocks.length; i++) {
      const block = visibleBlocks[i]
      const clampedStart = Math.max(timeToMinutes(block.start_time), DAY_START_MINUTES)
      const clampedEnd = Math.min(timeToMinutes(block.end_time), DAY_END_MINUTES)
      baseItems.push({
        type: "block",
        block,
        start_time: minutesToTime(clampedStart),
        end_time: minutesToTime(clampedEnd),
        duration_minutes: clampedEnd - clampedStart,
      })

      if (i < visibleBlocks.length - 1) {
        const gapStart = clampedEnd
        const nextStart = Math.max(timeToMinutes(visibleBlocks[i + 1].start_time), DAY_START_MINUTES)
        const gapMinutes = nextStart - gapStart
        if (gapMinutes > 0) {
          baseItems.push({
            type: "gap",
            start_time: minutesToTime(gapStart),
            end_time: minutesToTime(nextStart),
            duration_minutes: gapMinutes,
          })
        }
      }
    }

    // Gap after last block
    const lastEnd = Math.min(timeToMinutes(visibleBlocks[visibleBlocks.length - 1].end_time), DAY_END_MINUTES)
    if (lastEnd < DAY_END_MINUTES) {
      baseItems.push({
        type: "gap",
        start_time: minutesToTime(lastEnd),
        end_time: DAY_END,
        duration_minutes: DAY_END_MINUTES - lastEnd,
      })
    }
  }

  // If not today, return as-is (no now marker)
  if (!isToday.value) {
    return baseItems as DisplayItem[]
  }

  // Splice the now marker into the list
  const now = nowMinutes.value
  const result: DisplayItem[] = []
  let inserted = false

  for (const item of baseItems) {
    const start = timeToMinutes(item.start_time)
    const end = timeToMinutes(item.end_time)

    if (inserted || now < start || now >= end) {
      // Current time is not in this item — pass through
      result.push(item as DisplayItem)
      continue
    }

    inserted = true

    if (item.type === "gap") {
      // Gap with now overlay — keeps the full gap height intact
      result.push({
        ...item,
        type: "gap-with-now",
      } as DisplayItem)
    } else {
      // Block with now overlay
      result.push({
        ...item,
        type: "block-with-now",
      } as DisplayItem)
    }
  }

  return result
})

function itemHeight(item: DisplayItem): string {
  return `${item.duration_minutes * PX_PER_MINUTE}px`
}

function nowOffsetPercent(item: DisplayItem): string {
  const start = timeToMinutes(item.start_time)
  const end = timeToMinutes(item.end_time)
  const span = end - start
  if (span <= 0) return "0%"
  return ((nowMinutes.value - start) / span) * 100 + "%"
}

function handleAddHere(payload: { start_time: string; end_time: string }) {
  prefillStart.value = payload.start_time
  prefillEnd.value = payload.end_time
}

function logout() {
  router.post("/accounts/logout/")
}
</script>

<template>
  <div class="schedule-page">
    <DateNavigator :date="date" />

    <AddBlockForm
      :date="date"
      :initial-start-time="prefillStart"
      :initial-end-time="prefillEnd"
    />

    <div ref="scheduleBodyRef" class="schedule-body">
      <!-- Drag ghost element -->
      <div
        v-if="isDragging && draggedBlock"
        class="drag-ghost"
        :class="{ compact: ghostIsCompact }"
        :style="{ top: ghostTop + 'px', height: ghostHeight + 'px' }"
      >
        <span class="ghost-handle">&#x2807;</span>
        <template v-if="ghostIsCompact">
          <input type="checkbox" class="ghost-checkbox" disabled />
          <span class="ghost-time">{{ previewStartTime }}–{{ previewEndTime }}</span>
          <span class="ghost-title">{{ draggedBlock.title }}</span>
        </template>
        <template v-else>
          <div class="ghost-header">
            <span class="ghost-time">{{ previewStartTime }} – {{ previewEndTime }}</span>
          </div>
          <div class="ghost-body">
            <input type="checkbox" class="ghost-checkbox" disabled />
            <span class="ghost-title">{{ draggedBlock.title }}</span>
          </div>
        </template>
      </div>

      <template v-for="(item, idx) in displayList" :key="idx">
        <div
          v-if="item.type === 'block-with-now' && item.block"
          class="schedule-slot"
          :style="{ height: itemHeight(item) }"
        >
          <TimeBlock :block="item.block" :date="date" />
          <NowLine
            class="now-overlay"
            :style="{ top: nowOffsetPercent(item) }"
          />
        </div>

        <div
          v-else-if="item.type === 'gap-with-now'"
          class="schedule-slot"
          :style="{ height: itemHeight(item) }"
        >
          <GapSlot
            :start-time="item.start_time"
            :end-time="item.end_time"
            :duration-minutes="item.duration_minutes"
            @add-here="handleAddHere"
          />
          <NowLine
            class="now-overlay"
            :style="{ top: nowOffsetPercent(item) }"
          />
        </div>

        <div
          v-else-if="(item.type === 'block') && item.block"
          class="schedule-slot"
          :style="{ height: itemHeight(item) }"
        >
          <TimeBlock :block="item.block" :date="date" />
        </div>

        <div
          v-else-if="item.type === 'gap'"
          class="schedule-slot"
          :style="{ height: itemHeight(item) }"
        >
          <GapSlot
            :start-time="item.start_time"
            :end-time="item.end_time"
            :duration-minutes="item.duration_minutes"
            @add-here="handleAddHere"
          />
        </div>
      </template>
    </div>

    <div class="logout-footer">
      <button class="logout-btn" @click="logout">Logout</button>
    </div>

    <UndoToast
      v-if="currentToast"
      :message="currentToast.description"
      :actionable="currentToast.actionable"
      @undo="performUndo"
      @dismiss="dismissToast"
    />

    <CommandBar
      :date="date"
      :snapshot-blocks="snapshotBlocks"
      :push-undo="pushUndo"
    />
  </div>
</template>

<style scoped>
.schedule-page {
  max-width: 640px;
  margin: 0 auto;
  min-height: 100vh;
  background: #f9fafb;
}

.schedule-body {
  position: relative;
  padding: 8px 16px;
  /* Bottom padding so the fixed command bar doesn't occlude the last block. */
  padding-bottom: 88px;
}

.drag-ghost {
  position: absolute;
  left: 16px;
  right: 16px;
  background: rgba(59, 130, 246, 0.12);
  border: 2px dashed #3b82f6;
  border-radius: 8px;
  padding: 12px 16px 12px 34px;
  pointer-events: none;
  z-index: 20;
  box-shadow: 0 4px 12px rgba(0, 0, 0, 0.1);
  display: flex;
  flex-direction: column;
  justify-content: center;
  gap: 6px;
  box-sizing: border-box;
  overflow: hidden;
}

.drag-ghost.compact {
  flex-direction: row;
  align-items: center;
  justify-content: flex-start;
  padding: 4px 8px 4px 30px;
  gap: 8px;
}

.ghost-handle {
  position: absolute;
  left: 4px;
  top: 0;
  bottom: 0;
  width: 24px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: #93c5fd;
  font-size: 16px;
}

.ghost-header {
  display: flex;
  align-items: center;
  gap: 8px;
  /* Match block-header height (driven by its 24px delete-btn) so the
     body (checkbox + title) lands at the same y as in the real block. */
  height: 24px;
}

.ghost-body {
  display: flex;
  align-items: center;
  gap: 8px;
  min-width: 0;
}

.ghost-checkbox {
  width: 18px;
  height: 18px;
  flex-shrink: 0;
  pointer-events: none;
}

.drag-ghost.compact .ghost-checkbox {
  width: 14px;
  height: 14px;
}

.ghost-time {
  font-size: 12px;
  color: #3b82f6;
  font-weight: 500;
  flex-shrink: 0;
}

.drag-ghost.compact .ghost-time {
  font-size: 12px;
}

.ghost-title {
  font-size: 15px;
  color: #1f2937;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}

.drag-ghost.compact .ghost-title {
  font-size: 13px;
}

.schedule-slot {
  position: relative;
  overflow: visible;
}

.now-overlay {
  position: absolute;
  left: 0;
  right: 0;
  z-index: 10;
  transform: translateY(-50%);
}

.logout-footer {
  padding: 24px 16px;
  text-align: right;
}

.logout-btn {
  font-size: 12px;
  padding: 4px 12px;
  border: 1px solid #d1d5db;
  border-radius: 6px;
  background: white;
  color: #6b7280;
  cursor: pointer;
}

.logout-btn:hover {
  background: #fee2e2;
  color: #dc2626;
  border-color: #fca5a5;
}
</style>
