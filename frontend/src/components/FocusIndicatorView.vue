<!-- Styles come from PIP_STYLES in useFocusIndicator.ts — scoped CSS never reaches the PiP Document. -->
<script setup lang="ts">
import { computed } from "vue"
import { formatRemainingMinutes } from "../utils/scheduleTime"

// Active state carries ONLY non-sensitive derived state — no current title,
// category, date, or clock times. The idle-gap body alone may display the
// supplied next title; document.title remains generic (0066 privacy exception).
const props = withDefaults(
  defineProps<{
    active: boolean
    progressPercent: number
    errorState: boolean
    remainingMinutes?: number | null
    nextBlockTitle?: string | null
    nextBlockRemainingMinutes?: number | null
  }>(),
  { remainingMinutes: null, nextBlockTitle: null, nextBlockRemainingMinutes: null },
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

const nextBlockLabel = computed(() => {
  if (
    props.active ||
    props.nextBlockTitle === null ||
    props.nextBlockRemainingMinutes === null ||
    !Number.isFinite(props.nextBlockRemainingMinutes) ||
    props.nextBlockRemainingMinutes <= 0
  ) {
    return null
  }
  return props.nextBlockTitle.trim() || "Untitled"
})

const nextBlockRemainingLabel = computed(() =>
  nextBlockLabel.value === null || props.nextBlockRemainingMinutes === null
    ? null
    : formatRemainingMinutes(props.nextBlockRemainingMinutes),
)
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
    <template v-else-if="nextBlockLabel !== null && nextBlockRemainingLabel !== null">
      <span class="fi-next-title">{{ nextBlockLabel }}</span>
      <span class="fi-next-remaining">{{ nextBlockRemainingLabel }}</span>
    </template>
    <template v-else>
      <span class="fi-neutral" aria-hidden="true">—</span>
      <span class="fi-sr-only">No active block</span>
    </template>
  </div>
</template>
