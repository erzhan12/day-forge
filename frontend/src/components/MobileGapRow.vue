<script setup lang="ts">
// Free-gap row of the Dark 4a phone list (feature 0113, SPEC 11.3): 48 px,
// dashed, `Free · 1h 45m`, range and a visible +. The whole row is one native
// button that offers the gap's 5-minute-grid range to the Add Block form.
import { computed } from "vue"
import { SNAP_MINUTES, minutesToTime, timeToMinutes } from "../utils/scheduleTime"
import { formatGapLabel, formatGapRange } from "../utils/gapLabel"

const props = defineProps<{
  startTime: string
  endTime: string
  durationMinutes: number
  disabled?: boolean
}>()

const emit = defineEmits<{
  "add-here-4a": [payload: { start_time: string; end_time: string }]
}>()

// Ceil the start and floor the end to the grid, like GapSlot4a.
const snapped = computed(() => {
  const start = Math.ceil(timeToMinutes(props.startTime) / SNAP_MINUTES) * SNAP_MINUTES
  const end = Math.floor(timeToMinutes(props.endTime) / SNAP_MINUTES) * SNAP_MINUTES
  return end - start >= SNAP_MINUTES ? { start, end } : null
})
const inert = computed(() => Boolean(props.disabled) || snapped.value === null)

function activate(): void {
  if (inert.value || !snapped.value) return
  emit("add-here-4a", {
    start_time: minutesToTime(snapped.value.start),
    end_time: minutesToTime(snapped.value.end),
  })
}
</script>

<template>
  <button
    type="button"
    class="mobile-gap-row"
    :aria-disabled="inert || undefined"
    :aria-label="`Add a block, ${formatGapLabel(durationMinutes)}, ${formatGapRange(startTime, endTime)}`"
    data-testid="mobile-gap-row"
    @click="activate"
  >
    <span class="gap-label">{{ formatGapLabel(durationMinutes) }}</span>
    <span class="gap-range">{{ formatGapRange(startTime, endTime) }}</span>
    <span class="gap-plus" aria-hidden="true">+</span>
  </button>
</template>

<style scoped>
@media (max-width: 640px) {
  html[data-theme="dark_4a"] .mobile-gap-row {
    box-sizing: border-box;
    display: flex;
    align-items: center;
    gap: 10px;
    width: 100%;
    height: 48px;
    padding: 0 0 0 14px;
    border: 1px dashed #6a6e75;
    border-radius: 8px;
    background: transparent;
    color: #e5e7eb;
    font: inherit;
    text-align: left;
  }

  html[data-theme="dark_4a"] .mobile-gap-row[aria-disabled="true"] {
    cursor: default;
  }

  html[data-theme="dark_4a"] .mobile-gap-row:focus-visible {
    outline: 2px solid #fd7562;
    outline-offset: 2px;
  }

  html[data-theme="dark_4a"] .gap-label {
    font-size: 14px;
    font-weight: 500;
    color: #e5e7eb;
    white-space: nowrap;
  }

  html[data-theme="dark_4a"] .gap-range {
    flex: 1;
    min-width: 0;
    font-size: 13px;
    font-weight: 400;
    color: #9ca3af;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }

  html[data-theme="dark_4a"] .gap-plus {
    display: flex;
    align-items: center;
    justify-content: center;
    flex-shrink: 0;
    width: 44px;
    height: 44px;
    font-size: 22px;
    line-height: 1;
    color: #9ca3af;
  }
}
</style>
