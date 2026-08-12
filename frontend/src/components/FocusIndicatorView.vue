<script setup lang="ts">
import { computed } from "vue"

// Props carry ONLY non-sensitive derived state — no block title, category,
// date, or times (privacy invariant, 0049 plan § Privacy).
const props = defineProps<{
  active: boolean
  progressPercent: number
  completing: boolean
  errorState: boolean
  disabled: boolean
}>()

const emit = defineEmits<{ (e: "complete"): void }>()

// Non-color state cue (state must not be conveyed by color alone).
const stateName = computed(() =>
  props.errorState ? "error" : props.active ? "active" : "neutral",
)

const completeDisabled = computed(() => props.disabled || props.completing)

function onComplete() {
  if (completeDisabled.value) return
  emit("complete")
}
</script>

<template>
  <div class="focus-indicator" :data-state="stateName">
    <template v-if="active">
      <div
        class="fi-bar"
        role="progressbar"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-valuenow="progressPercent"
      >
        <div class="fi-fill" :style="{ width: progressPercent + '%' }" />
      </div>
      <span v-if="errorState" class="fi-retry" role="alert">Retry</span>
      <button
        type="button"
        class="fi-complete"
        :disabled="completeDisabled"
        aria-label="Complete current block"
        @click="onComplete"
      >
        <span aria-hidden="true">✓</span>
      </button>
    </template>
    <template v-else>
      <span class="fi-neutral" aria-hidden="true">—</span>
      <span class="fi-sr-only">No active block</span>
    </template>
  </div>
</template>

<style scoped>
.focus-indicator {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  box-sizing: border-box;
  padding: 0 12px;
  font-family: system-ui, sans-serif;
}
.fi-bar {
  flex: 1;
  height: 12px;
  border-radius: 6px;
  background: rgba(128, 128, 128, 0.3);
  overflow: hidden;
}
.fi-fill {
  height: 100%;
  background: currentColor;
  transition: width 0.25s ease;
}
/* Generic (non-category) styling; state cue is the border, not color alone. */
.focus-indicator[data-state="error"] {
  outline: 2px solid currentColor;
  outline-offset: 2px;
}
.fi-complete {
  flex: none;
  min-width: 28px;
  min-height: 24px;
  border: 1px solid currentColor;
  border-radius: 4px;
  background: transparent;
  cursor: pointer;
  font-size: 14px;
  line-height: 1;
}
.fi-complete:disabled {
  opacity: 0.5;
  cursor: default;
}
.fi-complete:focus-visible {
  outline: 2px solid currentColor;
  outline-offset: 2px;
}
.fi-retry {
  flex: none;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
}
.fi-neutral {
  flex: 1;
  text-align: center;
  opacity: 0.6;
}
.fi-sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}
@media (prefers-reduced-motion: reduce) {
  .fi-fill {
    transition: none;
  }
}
</style>
