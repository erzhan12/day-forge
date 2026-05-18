<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue"
import { Link } from "@inertiajs/vue3"
import type { DailyReview, Schedule, StreakInfo, TimeBlock } from "../types"
import CompletionBar from "../components/CompletionBar.vue"
import CategoryBreakdown from "../components/CategoryBreakdown.vue"
import StreakCounter from "../components/StreakCounter.vue"
import SkippedTasks from "../components/SkippedTasks.vue"
import { useAnalytics } from "../composables/useAnalytics"
import { parseLocalDate } from "../utils/date"
import { useThemeFromProps } from "../composables/useThemeFromProps"
import "../app.css"

useThemeFromProps()

const props = defineProps<{
  review: DailyReview
  streak: StreakInfo
  schedule: Schedule
  blocks: TimeBlock[]
  date: string
}>()

const { isMarkingReviewed, lastError, markReviewed, saveNotes } = useAnalytics()

const isReviewed = computed(() => props.schedule.status === "reviewed")

const formattedDate = computed(() => {
  const d = parseLocalDate(props.date)
  return d.toLocaleDateString("en-US", {
    weekday: "long",
    year: "numeric",
    month: "long",
    day: "numeric",
  })
})

// Notes state — debounced auto-save. The input is uncontrolled in the
// sense that user keystrokes update ``notesDraft`` immediately; the
// server PATCH fires only after 1 s of inactivity. When the panel
// re-renders with a new ``review`` (e.g. after mark-reviewed), we sync
// the draft with the persisted value.
const NOTES_DEBOUNCE_MS = 1000
const notesDraft = ref(props.review.notes)
let saveTimer: ReturnType<typeof setTimeout> | null = null

watch(
  () => props.review.id,
  () => {
    notesDraft.value = props.review.notes
  },
)

function onNotesInput() {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = setTimeout(() => {
    saveTimer = null
    saveNotes(props.review.id, notesDraft.value)
  }, NOTES_DEBOUNCE_MS)
}

// Flush a pending PATCH on unmount instead of dropping it — losing a
// half-typed note because the user navigated < 1s after typing is
// worse than the alternative. ``saveNotes`` is parameterised by
// ``review.id``, so the request lands on the correct review even if a
// new Analytics page mounts immediately afterwards. Inertia is an SPA
// (no real page unload), so the in-flight fetch completes normally.
// The ``!==`` guard avoids an idempotent no-op PATCH when the
// debounce timer was armed by a keystroke that didn't actually change
// the value.
onUnmounted(() => {
  if (saveTimer) {
    clearTimeout(saveTimer)
    saveTimer = null
    if (notesDraft.value !== props.review.notes) {
      saveNotes(props.review.id, notesDraft.value)
    }
  }
})

async function onMarkReviewed() {
  // Pass notes only if the user already typed something pre-review;
  // otherwise the empty body convention takes over and the backend
  // doesn't write a notes value.
  const notes = notesDraft.value.trim() ? notesDraft.value : undefined
  await markReviewed(props.date, notes)
}
</script>

<template>
  <div class="analytics-page">
    <header class="page-header">
      <Link :href="`/schedule/${date}/`" class="back-link">&larr; Back to schedule</Link>
      <div class="title-row">
        <h1>{{ formattedDate }}</h1>
        <span
          class="status-badge"
          :class="{ 'status-reviewed': isReviewed, 'status-active': !isReviewed }"
        >
          {{ isReviewed ? "Reviewed" : "Active" }}
        </span>
        <StreakCounter :streak="streak.current" :threshold="streak.threshold" />
        <button
          v-if="!isReviewed"
          class="mark-reviewed-btn"
          :disabled="isMarkingReviewed"
          @click="onMarkReviewed"
        >
          {{ isMarkingReviewed ? "Saving…" : "Mark reviewed" }}
        </button>
      </div>
      <p v-if="lastError" class="error">{{ lastError }}</p>
    </header>

    <div class="panels">
      <CompletionBar
        :completed="review.completed_count"
        :planned="review.planned_count"
      />
      <CategoryBreakdown
        :planned="review.planned_minutes_by_category"
        :completed="review.completed_minutes_by_category"
      />
      <SkippedTasks :blocks="blocks" :date="date" />
      <section class="notes-card">
        <h3>Notes</h3>
        <textarea
          v-model="notesDraft"
          class="notes-input"
          maxlength="2000"
          placeholder="What worked? What didn't?"
          @input="onNotesInput"
        />
      </section>
    </div>
  </div>
</template>

<style scoped>
.analytics-page {
  max-width: 640px;
  margin: 0 auto;
  padding: 16px;
  background: var(--bg-schedule-gap);
  min-height: 100vh;
}

.page-header {
  margin-bottom: 16px;
}

.back-link {
  font-size: 13px;
  color: var(--accent-hover);
  text-decoration: none;
}

.title-row {
  display: flex;
  align-items: center;
  gap: 12px;
  margin-top: 8px;
  flex-wrap: wrap;
}

.title-row h1 {
  margin: 0;
  font-size: 20px;
  font-weight: 600;
  color: var(--text-primary);
}

.status-badge {
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  padding: 2px 10px;
  border-radius: 999px;
  font-weight: 600;
}
.status-active {
  /* Info badge family: each theme defines --info-text and --info-surface
     as a contrast-verified pair (≥ 4.5:1 in every theme — see
     frontend/tests/semanticContrast.test.ts). Previously used a
     same-accent-token derivation that collapsed to ~2.8:1 on Classic. */
  background: var(--info-surface);
  color: var(--info-text);
  border: 1px solid var(--info-border);
}
.status-reviewed {
  background: var(--success-surface);
  color: var(--success-text);
  border: 1px solid var(--success-border);
}

.mark-reviewed-btn {
  margin-left: auto;
  padding: 6px 14px;
  border-radius: 6px;
  border: 1px solid var(--accent-hover);
  background: var(--accent-hover);
  color: var(--accent-contrast);
  font-size: 13px;
  cursor: pointer;
}
.mark-reviewed-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.error {
  margin: 8px 0 0;
  padding: 8px 12px;
  background: var(--danger-surface);
  color: var(--danger-text);
  border-radius: 6px;
  font-size: 13px;
}

.panels {
  display: grid;
  gap: 12px;
}
@media (min-width: 768px) {
  .panels {
    grid-template-columns: 1fr 1fr;
  }
  .notes-card {
    grid-column: span 2;
  }
}

.notes-card {
  background: var(--bg-panel);
  border-radius: 8px;
  padding: 16px;
  box-shadow: 0 1px 2px rgba(0, 0, 0, 0.05);
}
.notes-card h3 {
  margin: 0 0 8px;
  font-size: 14px;
  color: var(--text-primary);
}
.notes-input {
  width: 100%;
  min-height: 96px;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  padding: 8px 10px;
  font-size: 14px;
  font-family: inherit;
  resize: vertical;
  box-sizing: border-box;
}
</style>
