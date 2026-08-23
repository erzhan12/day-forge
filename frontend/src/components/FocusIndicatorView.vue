<!-- Visual styles live in PIP_STYLES (useFocusIndicator). Document PiP is a
     foreign Document; Vue/Vite scoped CSS is injected only into the opener
     page and would never apply here. -->
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
