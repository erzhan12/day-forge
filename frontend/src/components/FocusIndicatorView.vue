<!-- Styles come from PIP_STYLES in useFocusIndicator.ts — scoped CSS never reaches the PiP Document. -->
<script setup lang="ts">
import { computed } from "vue"
import { formatRemainingMinutes } from "../utils/scheduleTime"

// Props carry ONLY non-sensitive derived state — no block title, category,
// date, or clock times (privacy invariant, 0049 plan § Privacy). Remaining
// minutes is a derived countdown, same copy as the timeline badge.
const props = withDefaults(
  defineProps<{
    active: boolean
    progressPercent: number
    errorState: boolean
    remainingMinutes?: number | null
  }>(),
  { remainingMinutes: null },
)

// Non-color state cue (state must not be conveyed by color alone).
const stateName = computed(() =>
  props.errorState ? "error" : props.active ? "active" : "neutral",
)

const remainingLabel = computed(() => {
  if (!props.active || props.remainingMinutes == null || props.remainingMinutes <= 0) {
    return null
  }
  return formatRemainingMinutes(props.remainingMinutes)
})
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
        :aria-valuetext="remainingLabel ?? undefined"
      >
        <div class="fi-fill" :style="{ width: progressPercent + '%' }" />
      </div>
      <span v-if="remainingLabel" class="fi-remaining">{{ remainingLabel }}</span>
      <span v-if="errorState" class="fi-retry" role="alert">Retry</span>
    </template>
    <template v-else>
      <span class="fi-neutral" aria-hidden="true">—</span>
      <span class="fi-sr-only">No active block</span>
    </template>
  </div>
</template>
