<script setup lang="ts">
// Dark 4a free-gap row (feature 0106). The whole row is one native button
// that offers the gap's 5-minute-grid range to the Add Block form; the `+` is
// a visible part of it, not a nested control. The classic GapSlot.vue is
// unchanged.
import { computed } from "vue"
import { SNAP_MINUTES, minutesToTime, timeToMinutes } from "../utils/scheduleTime"
import { formatGapLabel, formatGapRange } from "../utils/gapLabel"
import { MIN_BLOCK_PX } from "../utils/timelineStack"

const props = withDefaults(
  defineProps<{
    startTime: string
    endTime: string
    durationMinutes: number
    heightPx: number
    edgeHint?: "earlier" | "later" | null
    disabled?: boolean
  }>(),
  { edgeHint: null, disabled: false },
)

const emit = defineEmits<{
  "add-here-4a": [payload: { start_time: string; end_time: string }]
}>()

// Manual creates need grid-aligned edges inside the gap: ceil the start,
// floor the end.
const snapped = computed(() => {
  const start = Math.ceil(timeToMinutes(props.startTime) / SNAP_MINUTES) * SNAP_MINUTES
  const end = Math.floor(timeToMinutes(props.endTime) / SNAP_MINUTES) * SNAP_MINUTES
  return end - start >= SNAP_MINUTES ? { start, end } : null
})
const inert = computed(() => props.disabled || snapped.value === null)
const showText = computed(() => snapped.value !== null && props.heightPx >= MIN_BLOCK_PX)
const label = computed(() => formatGapLabel(props.durationMinutes))
const range = computed(() => formatGapRange(props.startTime, props.endTime))

function activate() {
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
    class="gap-row-4a"
    :class="{ 'is-inert': inert }"
    :disabled="inert"
    :aria-label="`Add a block between ${startTime} and ${endTime}`"
    data-testid="gap-row-4a"
    @click="activate"
  >
    <template v-if="showText">
      <span class="gap-text">
        <span class="gap-label" data-testid="gap-4a-label">{{ label }}</span>
        <span v-if="edgeHint" class="gap-hint">{{ edgeHint }}</span>
      </span>
      <span class="gap-range" data-testid="gap-4a-range">{{ range }}</span>
      <span class="gap-plus" aria-hidden="true" data-testid="gap-4a-plus">+</span>
    </template>
  </button>
</template>

<style scoped>
.gap-row-4a {
  box-sizing: border-box;
  display: flex;
  align-items: center;
  gap: 10px;
  width: 100%;
  height: 100%;
  margin: 0;
  padding: 0 8px 0 14px;
  overflow: hidden;
  background: transparent;
  border: 1px dashed var(--border-strong);
  border-radius: 8px;
  color: var(--text-secondary);
  font-family: var(--font-family-body);
  font-size: 13px;
  line-height: 16px;
  text-align: left;
  cursor: pointer;
}

.gap-row-4a:hover:not(:disabled) {
  background: var(--bg-panel);
  border-color: var(--border-control);
  color: var(--text-primary);
}

.gap-row-4a:focus {
  outline: none;
}

.gap-row-4a:focus-visible {
  box-shadow: 0 0 0 3px var(--focus-ring);
}

.gap-row-4a.is-inert {
  cursor: default;
}

.gap-text {
  flex: 1 1 auto;
  min-width: 0;
  overflow: hidden;
  white-space: nowrap;
  text-overflow: ellipsis;
}

.gap-label {
  font-weight: 500;
}

.gap-hint {
  margin-left: 6px;
  font-style: italic;
}

.gap-range {
  flex-shrink: 0;
  font-variant-numeric: tabular-nums;
}

.gap-plus {
  flex-shrink: 0;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  width: 24px;
  height: 24px;
  border: 1px solid var(--border-control);
  border-radius: 6px;
  color: var(--text-secondary);
  font-size: 16px;
  line-height: 1;
}

.gap-row-4a:hover:not(:disabled) .gap-plus {
  color: var(--text-primary);
}

@media (forced-colors: active) {
  .gap-row-4a:focus-visible {
    outline: 2px solid CanvasText;
    outline-offset: 2px;
  }
}
</style>
