<script setup lang="ts">
import GapSlot from "./GapSlot.vue"

defineProps<{
  startTime: string
  endTime: string
  durationMinutes: number
  compact?: boolean
  disabled?: boolean
  windowStart: string
}>()

const emit = defineEmits<{
  "add-here": [payload: { start_time: string; end_time: string }]
}>()
</script>

<template>
  <div class="gap-slot-4a">
    <GapSlot
      :start-time="startTime"
      :end-time="endTime"
      :duration-minutes="durationMinutes"
      :compact="compact"
      :disabled="disabled"
      :window-start="windowStart"
      @add-here="emit('add-here', $event)"
    />
  </div>
</template>

<style scoped>
.gap-slot-4a { height: 100%; }
.gap-slot-4a :deep(.gap-slot) {
  border-color: #33373c;
  color: var(--text-faint);
  background: transparent;
}
</style>
