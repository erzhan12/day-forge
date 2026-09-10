<!-- Styles come from PIP_STYLES in useFocusIndicator.ts — scoped CSS never reaches the PiP Document. -->
<script setup lang="ts">
import { computed } from "vue"
import { formatRemainingMinutes } from "../utils/scheduleTime"

// Feature 0079 reverses the 0066 active-state privacy rule: the block title and
// its category colour are now shown, so "in a block" and "in a pause" are
// distinguishable without reading the text. Wall-clock times and the date stay
// out, and `document.title` remains generic (see useFocusIndicator).
//
// The window carries NO control of its own: the PiP chrome's close button and
// the schedule header's Hide are the two ways out (0079).
const props = withDefaults(
  defineProps<{
    active: boolean
    progressPercent: number
    errorState: boolean
    blockTitle?: string | null
    categoryColor?: string | null
    remainingMinutes?: number | null
    nextBlockTitle?: string | null
    nextBlockRemainingMinutes?: number | null
    /** Elapsed pause percent, or `null` when the pause has no measurable origin. */
    pausePercent?: number | null
    dayFinished?: boolean
  }>(),
  {
    blockTitle: null,
    categoryColor: null,
    remainingMinutes: null,
    nextBlockTitle: null,
    nextBlockRemainingMinutes: null,
    pausePercent: null,
    dayFinished: false,
  },
)

// Non-color state cue (state must not be conveyed by color alone).
const stateName = computed(() =>
  props.errorState ? "error" : props.active ? "active" : "neutral",
)

/** The pause palette; also the active fallback when a category has no colour. */
const NEUTRAL_INK = "#8E9299"

const accentColor = computed(() => props.categoryColor ?? NEUTRAL_INK)

function titleOrUntitled(title: string | null): string {
  return title === null ? "Untitled" : title.trim() || "Untitled"
}

/** Same "18m left" / "1h 30m left" copy as the timeline badge. */
function remainingLabelFor(minutes: number | null | undefined): string | null {
  if (minutes == null || !Number.isFinite(minutes) || minutes <= 0) return null
  return formatRemainingMinutes(minutes)
}

const blockLabel = computed(() => titleOrUntitled(props.blockTitle))
const remainingLabel = computed(() =>
  props.active ? remainingLabelFor(props.remainingMinutes) : null,
)

const nextBlockLabel = computed(() => {
  if (props.active || props.dayFinished) return null
  if (props.nextBlockTitle === null) return null
  if (remainingLabelFor(props.nextBlockRemainingMinutes) === null) return null
  return titleOrUntitled(props.nextBlockTitle)
})

const nextBlockRemainingLabel = computed(() =>
  nextBlockLabel.value === null
    ? null
    : remainingLabelFor(props.nextBlockRemainingMinutes),
)

/** Pause or day-finished: the row-1 pause glyph is shown for both. */
const inPause = computed(
  () => !props.active && (props.dayFinished || nextBlockLabel.value !== null),
)

// A dashed track only claims progressbar semantics when it has a real fraction
// to report; before the day's first block there is nothing to measure.
const pauseMeasurable = computed(
  () => inPause.value && !props.dayFinished && props.pausePercent !== null,
)
</script>

<template>
  <div class="focus-indicator" :data-state="stateName">
    <div class="fi-row fi-row--head">
      <template v-if="active">
        <span
          class="fi-rail"
          aria-hidden="true"
          :style="{ background: accentColor, boxShadow: `0 0 10px ${accentColor}` }"
        />
        <span class="fi-title">{{ blockLabel }}</span>
        <span class="fi-spacer" />
        <span v-if="remainingLabel" class="fi-remaining">{{ remainingLabel }}</span>
        <span v-if="errorState" class="fi-retry" role="alert">Retry</span>
      </template>
      <template v-else-if="inPause">
        <!-- Two bars drawn in CSS: a literal "||" reads as two pipes in a mono
             face and is nonsense to a screen reader. The glyph mirrors the
             active state's single `.fi-rail`, in grey. -->
        <span class="fi-pause-glyph" aria-hidden="true"><span /><span /></span>
        <span class="fi-sr-only">Pause</span>
        <template v-if="dayFinished">
          <span class="fi-pause-done">· day finished</span>
          <span class="fi-spacer" />
        </template>
        <template v-else>
          <span class="fi-arrow" aria-hidden="true">→</span>
          <span class="fi-next-title">{{ nextBlockLabel }}</span>
          <span class="fi-spacer" />
          <span class="fi-next-remaining">{{ nextBlockRemainingLabel }}</span>
        </template>
      </template>
      <template v-else>
        <span class="fi-neutral" aria-hidden="true">—</span>
        <span class="fi-sr-only">No active block</span>
        <span class="fi-spacer" />
      </template>
    </div>

    <div class="fi-row fi-row--track">
      <div
        v-if="active"
        class="fi-track"
        role="progressbar"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-valuenow="progressPercent"
        :aria-valuetext="remainingLabel ?? undefined"
      >
        <div class="fi-fill" :style="{ width: progressPercent + '%', background: accentColor }" />
      </div>
      <div
        v-else-if="pauseMeasurable"
        class="fi-track fi-track--dashed"
        role="progressbar"
        aria-valuemin="0"
        aria-valuemax="100"
        :aria-valuenow="pausePercent ?? 0"
        :aria-valuetext="nextBlockRemainingLabel ?? undefined"
      >
        <div class="fi-fill fi-fill--pause" :style="{ width: (pausePercent ?? 0) + '%' }" />
      </div>
      <div v-else class="fi-track fi-track--dashed" aria-hidden="true" />
    </div>
  </div>
</template>
