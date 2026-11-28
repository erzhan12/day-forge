<script setup lang="ts">
// Dark 4a phone list (feature 0113, SPEC 11.3): blocks (52 px) and free rows
// (48 px) in time order with 8 px gaps. No hour axis, no now line, no time
// scale.
import { computed } from "vue"
import type { TimeBlock, UserCategory } from "../types"
import type { ScheduleWindowBounds } from "../utils/scheduleTime"
import { buildMobileRows } from "../utils/mobileRows"
import MobileBlockRow from "./MobileBlockRow.vue"
import MobileGapRow from "./MobileGapRow.vue"

const props = defineProps<{
  date: string
  blocks: TimeBlock[]
  window: ScheduleWindowBounds
  disabled: boolean
  categories: UserCategory[]
}>()

const emit = defineEmits<{ "add-here-4a": [payload: { start_time: string; end_time: string }] }>()

const rows = computed(() => buildMobileRows(props.blocks, props.window))
</script>

<template>
  <ul class="timeline-mobile" data-testid="timeline-mobile">
    <li v-for="row in rows" :key="row.key">
      <MobileBlockRow
        v-if="row.kind === 'block'"
        :block="row.block"
        :date="date"
        :categories="categories"
      />
      <MobileGapRow
        v-else
        :start-time="row.start_time"
        :end-time="row.end_time"
        :duration-minutes="row.duration_minutes"
        :disabled="disabled"
        @add-here-4a="emit('add-here-4a', $event)"
      />
    </li>
  </ul>
</template>

<style scoped>
@media (max-width: 640px) {
  html[data-theme="dark_4a"] .timeline-mobile {
    display: flex;
    flex-direction: column;
    gap: 8px;
    margin: 0;
    /* Bottom: the last row scrolls clear of the 56px FAB and its 16px offset. */
    padding: 12px 16px calc(56px + 16px + 8px);
    list-style: none;
  }
}
</style>
