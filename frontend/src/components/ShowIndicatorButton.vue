<script setup lang="ts">
import { computed } from "vue"

// Persistent header control for the focus indicator. Its state is deliberately
// independent of active-block data so it stays available with no current block
// and off-today (0049 plan § Schedule-page control).
const props = defineProps<{
  supported: boolean
  isOpen: boolean
  shouldRestore?: boolean
  error: string | null
}>()

const emit = defineEmits<{ (e: "open"): void; (e: "close"): void }>()

const disabled = computed(() => !props.supported)

const label = computed(() => {
  if (!props.supported) return "Indicator not supported"
  return props.isOpen ? "Hide indicator" : "Show indicator"
})

function handleClick() {
  if (disabled.value) return
  if (props.isOpen) emit("close")
  else emit("open")
}
</script>

<template>
  <div class="show-indicator-control">
    <button
      type="button"
      class="show-indicator-btn"
      :disabled="disabled"
      :aria-description="shouldRestore && !isOpen ? 'Reopen focus indicator' : undefined"
      :title="!supported ? 'Focus indicator is not supported in this browser.' : undefined"
      @click="handleClick"
    >
      {{ label }}
    </button>
    <span v-if="error" class="show-indicator-error" role="alert">
      {{ error }}
    </span>
  </div>
</template>

<style scoped>
.show-indicator-control {
  position: relative;
  display: inline-flex;
}

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

.show-indicator-error {
  position: absolute;
  z-index: 25;
  top: calc(100% + 6px);
  right: 0;
  width: max-content;
  max-width: min(260px, 80vw);
  padding: 6px 9px;
  border: 1px solid var(--danger-border);
  border-radius: 6px;
  background: var(--danger-surface);
  color: var(--danger-text);
  font-size: 12px;
  line-height: 1.3;
  white-space: normal;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.12);
}
</style>
