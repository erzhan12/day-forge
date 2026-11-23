<script setup lang="ts">
import type { TimeBlock, UserCategory } from "../types"
import TimeBlockClassic from "./TimeBlock.vue"
import { getCategoryColor } from "../utils/categoryColors"

const props = withDefaults(
  defineProps<{
    block: TimeBlock
    date: string
    isCurrent?: boolean
    remainingMinutes?: number | null
    categories?: UserCategory[]
    /** Rendered below the stack's compact threshold (feature 0106). */
    compact?: boolean
  }>(),
  { isCurrent: false, remainingMinutes: null, compact: false },
)
</script>

<template>
  <div
    class="time-block-4a"
    :class="{ 'is-compact': props.compact }"
    :style="{ '--category-color': getCategoryColor(block.category, undefined, props.categories) }"
  >
    <!-- The functional block is deliberately reused: its completion retry,
         edit/delete, identity-reset and drag behavior stay identical. -->
    <TimeBlockClassic
      :block="props.block"
      :date="props.date"
      :is-current="props.isCurrent"
      :remaining-minutes="props.remainingMinutes"
      :categories="props.categories"
      :density="props.compact ? 'compact' : 'full'"
      tooltip
      shift-preview
    />
  </div>
</template>

<style scoped>
.time-block-4a {
  height: 100%;
  border-left: 3px solid var(--category-color);
  border-radius: 8px;
  overflow: hidden;
  box-shadow: -5px 0 14px color-mix(in oklab, var(--category-color) 22%, transparent);
}

/* Compact rows sit flush against their neighbours; a glow would bleed into
   them, so it is reduced to the stripe (feature 0106). */
.time-block-4a.is-compact {
  box-shadow: none;
}

.time-block-4a :deep(.time-block) {
  background: linear-gradient(
    90deg,
    color-mix(in oklab, var(--category-color) 12%, var(--bg-schedule-block)) 0%,
    var(--bg-schedule-block) 55%
  );
  border: 1px solid var(--border-strong);
  border-left: 0;
  border-radius: 0;
  box-shadow: none;
}

.time-block-4a :deep(.time-badge),
.time-block-4a :deep(.duration),
.time-block-4a :deep(.remaining-badge),
.time-block-4a :deep(.block-error) {
  font-size: 13px;
}

.time-block-4a :deep(.time-badge),
.time-block-4a :deep(.duration),
.time-block-4a :deep(.delete-btn),
.time-block-4a :deep(.drag-handle) {
  color: var(--text-secondary);
}

.time-block-4a :deep(.delete-btn:hover:not(:disabled)) {
  background: var(--danger-surface);
  color: var(--danger-text);
}

.time-block-4a :deep(.title-input) {
  background: var(--bg-input);
  border: 1px solid var(--border-control);
  color: var(--text-primary);
}

/* Completed: keep the text readable (no whole-card dimming); the filled
   checkbox and the strike-through carry the state. */
.time-block-4a :deep(.time-block.completed) {
  opacity: 1;
  background: var(--bg-elevated);
}

.time-block-4a :deep(.title-completed) {
  color: var(--text-secondary);
}

/* A neighbour the drop would cascade: dashed outline plus its new start. */
.time-block-4a :deep(.time-block.shifting) {
  outline: 1px dashed var(--border-control);
  outline-offset: -2px;
}

/* In 4a the duration stays visible on narrow full rows; the end time goes
   instead. */
@container (max-width: 300px) {
  .time-block-4a :deep(.duration) {
    display: inline;
  }

  .time-block-4a :deep(.time-end) {
    display: none;
  }
}
</style>
