<script setup lang="ts">
import { computed } from "vue"
import { DAY_START } from "../utils/scheduleTime"

const props = withDefaults(
  defineProps<{
    startTime: string
    endTime: string
    durationMinutes: number
    compact?: boolean
    disabled?: boolean
  }>(),
  { compact: false, disabled: false },
)

const emit = defineEmits<{
  "add-here": [payload: { start_time: string; end_time: string }]
}>()

const edgeHint = computed(() =>
  props.startTime === DAY_START ? "earlier" : "later",
)

const durationLabel = computed(() => {
  if (props.durationMinutes >= 60) {
    const h = Math.floor(props.durationMinutes / 60)
    const m = props.durationMinutes % 60
    return m > 0 ? `${h}h ${m}m` : `${h}h`
  }
  return `${props.durationMinutes}m`
})

function handleClick() {
  if (props.disabled) return
  emit("add-here", { start_time: props.startTime, end_time: props.endTime })
}

</script>

<template>
  <div
    class="gap-slot"
    :class="{ disabled, compact }"
    @click="handleClick"
  >
    <span class="gap-label">
      Free — {{ durationLabel }}
      <span v-if="compact" class="gap-hint">{{ edgeHint }}</span>
    </span>
    <span class="gap-time">{{ startTime }} – {{ endTime }}</span>
  </div>
</template>

<style scoped>
.gap-slot {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 8px 16px;
  border: 1px dashed #d1d5db;
  border-radius: 8px;
  cursor: pointer;
  color: var(--text-faint);
  font-size: 13px;
  box-sizing: border-box;
  height: 100%;
}

.gap-slot:hover {
  background: var(--bg-schedule-gap);
  border-color: var(--text-faint);
  color: var(--text-muted);
}

.gap-slot.disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.gap-slot.disabled:hover {
  background: transparent;
  border-color: var(--border-strong);
  color: var(--text-faint);
}

.gap-label {
  font-weight: 500;
}

.gap-time {
  font-size: 12px;
}

.gap-slot.compact {
  padding: 4px 12px;
  font-size: 12px;
}

.gap-hint {
  margin-left: 6px;
  font-weight: 400;
  font-style: italic;
  opacity: 0.85;
}
</style>
