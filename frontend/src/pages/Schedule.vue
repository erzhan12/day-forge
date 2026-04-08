<script setup lang="ts">
import { computed, ref, onMounted, onUnmounted } from "vue"
import type { TimeBlock as TimeBlockType, Schedule, RenderItem } from "../types"
import DateNavigator from "../components/DateNavigator.vue"
import TimeBlock from "../components/TimeBlock.vue"
import GapSlot from "../components/GapSlot.vue"
import AddBlockForm from "../components/AddBlockForm.vue"
import NowLine from "../components/NowLine.vue"
import { todayString } from "../utils/date"
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

const isToday = computed(() => props.date === todayString())

// Reactive current-minute counter so display list recomputes as time passes
const nowMinutes = ref(getCurrentMinutes())
let nowInterval: ReturnType<typeof setInterval> | null = null

function getCurrentMinutes(): number {
  const now = new Date()
  return now.getHours() * 60 + now.getMinutes()
}

onMounted(() => {
  nowInterval = setInterval(() => {
    nowMinutes.value = getCurrentMinutes()
  }, 60_000)
})

onUnmounted(() => {
  if (nowInterval) clearInterval(nowInterval)
})

function timeToMinutes(time: string): number {
  const [h, m] = time.split(":").map(Number)
  return h * 60 + m
}

function minutesToTime(mins: number): string {
  const h = String(Math.floor(mins / 60)).padStart(2, "0")
  const m = String(mins % 60).padStart(2, "0")
  return `${h}:${m}`
}

// Build the display list: blocks and gaps with the now marker spliced in.
// Gaps that contain the current time are split into two halves around it.
// Blocks that contain the current time get the marker placed before or after
// (whichever half of the block the current minute falls in).
const displayList = computed<DisplayItem[]>(() => {
  const blocks = props.blocks
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

const DAY_START = "06:00"
const DAY_END = "23:00"
const DAY_START_MINUTES = timeToMinutes(DAY_START)
const DAY_END_MINUTES = timeToMinutes(DAY_END)

// Pixels per minute — 2px/min gives 120px for 1h, 30px for 15min.
const PX_PER_MINUTE = 2

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
</script>

<template>
  <div class="schedule-page">
    <DateNavigator :date="date" />

    <AddBlockForm
      :date="date"
      :initial-start-time="prefillStart"
      :initial-end-time="prefillEnd"
    />

    <div class="schedule-body">
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
  padding: 8px 16px;
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
</style>
