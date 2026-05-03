<script setup lang="ts">
import { computed } from "vue"

const props = withDefaults(
  defineProps<{
    startTime: string
    endTime: string
    durationMinutes: number
    disabled?: boolean
  }>(),
  { disabled: false },
)

const emit = defineEmits<{
  "add-here": [payload: { start_time: string; end_time: string }]
}>()

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
    :class="{ disabled }"
    @click="handleClick"
  >
    <span class="gap-label">Free — {{ durationLabel }}</span>
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
  color: #9ca3af;
  font-size: 13px;
  box-sizing: border-box;
  height: 100%;
}

.gap-slot:hover {
  background: #f9fafb;
  border-color: #9ca3af;
  color: #6b7280;
}

.gap-slot.disabled {
  cursor: not-allowed;
  opacity: 0.5;
}

.gap-slot.disabled:hover {
  background: transparent;
  border-color: #d1d5db;
  color: #9ca3af;
}

.gap-label {
  font-weight: 500;
}

.gap-time {
  font-size: 12px;
}
</style>
