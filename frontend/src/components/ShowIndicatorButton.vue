<script setup lang="ts">
import { computed } from "vue"

// Persistent header control for the focus indicator. Takes only supported /
// isOpen — deliberately independent of active-block state so it stays available
// with no current block and off-today (0049 plan § Schedule-page control).
const props = defineProps<{
  supported: boolean
  isOpen: boolean
}>()

const emit = defineEmits<{ (e: "open"): void }>()

const disabled = computed(() => !props.supported || props.isOpen)

const label = computed(() => {
  if (!props.supported) return "Indicator not supported"
  return props.isOpen ? "Indicator open" : "Show indicator"
})

function handleClick() {
  if (disabled.value) return
  emit("open")
}
</script>

<template>
  <button
    type="button"
    class="show-indicator-btn"
    :disabled="disabled"
    :title="!supported ? 'Focus indicator is not supported in this browser.' : undefined"
    @click="handleClick"
  >
    {{ label }}
  </button>
</template>

<style scoped>
.show-indicator-btn {
  font-size: 12px;
  padding: 4px 12px;
  border: 1px solid var(--border-color, #ccc);
  border-radius: 12px;
  background: var(--surface, #fff);
  color: var(--text-color, #222);
  cursor: pointer;
  font-weight: 500;
}

.show-indicator-btn:hover:not(:disabled) {
  background: var(--surface-hover, #f2f2f2);
}

.show-indicator-btn:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}
</style>
