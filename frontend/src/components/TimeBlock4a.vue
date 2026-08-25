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
  }>(),
  { isCurrent: false, remainingMinutes: null },
)
</script>

<template>
  <div
    class="time-block-4a"
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

.time-block-4a :deep(.time-block) {
  background: linear-gradient(
    90deg,
    color-mix(in oklab, var(--category-color) 12%, #1d1f22) 0%,
    #1d1f22 55%
  );
  border: 1px solid #2e3237;
  border-left: 0;
  border-radius: 0;
  box-shadow: none;
}

.time-block-4a :deep(.time-block.completed) {
  background: #1c1e21;
}

.time-block-4a :deep(.checkbox) {
  accent-color: var(--category-color);
  border-color: #43474d;
}
</style>
