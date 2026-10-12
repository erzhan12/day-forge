<script setup lang="ts">
import { computed, onUnmounted, ref, watch } from "vue"
import { Link } from "@inertiajs/vue3"
import type { DailyReview, Schedule, ScheduleSettingsWire, StreakInfo, TimeBlock, UserCategory } from "../types"
import TimeZoneMismatchPrompt from "../components/TimeZoneMismatchPrompt.vue"
import CompletionBar from "../components/CompletionBar.vue"
import CategoryBreakdown from "../components/CategoryBreakdown.vue"
import StreakCounter from "../components/StreakCounter.vue"
import SkippedTasks from "../components/SkippedTasks.vue"
import DailyExportDialog from "../components/DailyExportDialog.vue"
import { useAnalytics } from "../composables/useAnalytics"
import { provideScheduleRevision } from "../composables/useScheduleRevision"
import { formatCivilDate } from "../utils/date"
import { useThemeFromProps } from "../composables/useThemeFromProps"
import { hasValidCategoryCatalog } from "../utils/categories"
import "../app.css"

useThemeFromProps()

const props = withDefaults(defineProps<{
  review: DailyReview
  streak: StreakInfo
  schedule: Schedule
  blocks: TimeBlock[]
  date: string
  schedule_window?: ScheduleSettingsWire
  categories: UserCategory[]
  auth_user_id?: number | null
}>(), {
  schedule_window: () => ({ start: "06:00", end: "23:00", time_zone: "UTC" }),
})
const categoryCatalogValid = computed(() => hasValidCategoryCatalog(props.categories))

const scheduleRevision = provideScheduleRevision(() => props.date, () => props.schedule, { getBlocks: () => props.blocks, getUserId: () => props.auth_user_id })
const { isMarkingReviewed, lastError, markReviewed, saveNotes } = useAnalytics(scheduleRevision)

const isReviewed = computed(() => scheduleRevision.schedule.value?.status === "reviewed")
const hasCurrentReview = computed(() => isReviewed.value
  && props.review.snapshot_kind === "frozen"
  && props.review.schedule_id === scheduleRevision.schedule.value?.id
  && props.review.reviewed_revision === scheduleRevision.revision.value)
const summaryLabel = computed(() => hasCurrentReview.value ? "Reviewed summary"
  : props.review.snapshot_kind === "frozen" ? "Summary needs update" : "Current progress")
const statusLabel = computed(() => {
  const status = scheduleRevision.schedule.value?.status
  return status === "reviewed" ? "Reviewed" : status === "draft" ? "Draft" : status === "active" ? "Active" : ""
})
const isDailyExportOpen = ref(false)

const formattedDate = computed(() => formatCivilDate(props.date))

const NOTES_DEBOUNCE_MS = 1000
const notesDraft = ref(props.review.notes)
const notesEdited = ref(false)
let saveTimer: ReturnType<typeof setTimeout> | null = null
let pendingNotes: { date: string; userId?: number; notes: string } | null = null

function cancelPendingNotes() {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = null
  pendingNotes = null
}

function flushPendingNotes() {
  if (saveTimer) clearTimeout(saveTimer)
  saveTimer = null
  const pending = pendingNotes
  pendingNotes = null
  if (pending) void saveNotes(pending.date, pending.notes, pending.userId)
}

watch(
  () => [props.date, props.auth_user_id] as const,
  ([, userId], [, previousUserId]) => {
    if (userId !== previousUserId) cancelPendingNotes()
    else flushPendingNotes()
    notesDraft.value = userId === null ? "" : props.review.notes
    notesEdited.value = false
  },
)

watch(() => props.review.notes, (notes) => {
  if (!notesEdited.value) notesDraft.value = notes
  else if (notes === notesDraft.value) {
    notesEdited.value = false
    cancelPendingNotes()
  }
})

scheduleRevision.subscribeScopeReset((reason) => {
  if (reason !== "user" && reason !== "session") return
  cancelPendingNotes()
  notesDraft.value = reason === "session" || props.auth_user_id === null ? "" : props.review.notes
  notesEdited.value = false
})

function onNotesInput() {
  if (saveTimer) clearTimeout(saveTimer)
  notesEdited.value = true
  pendingNotes = { date: props.date, userId: props.auth_user_id ?? undefined, notes: notesDraft.value }
  saveTimer = setTimeout(flushPendingNotes, NOTES_DEBOUNCE_MS)
}

onUnmounted(flushPendingNotes)

async function onMarkReviewed() {
  const notes = notesEdited.value ? notesDraft.value : undefined
  flushPendingNotes()
  await markReviewed(props.date, notes)
}
</script>

<template>
  <div v-if="categoryCatalogValid" class="analytics-page">
    <TimeZoneMismatchPrompt :time-zone="schedule_window.time_zone" />
    <header class="page-header">
      <Link :href="`/schedule/${date}/`" class="back-link">&larr; Back to schedule</Link>
      <div class="title-row">
        <h1>{{ formattedDate }}</h1>
        <span
          v-if="scheduleRevision.schedule.value"
          class="status-badge"
          :class="{ 'status-reviewed': isReviewed, 'status-active': !isReviewed }"
        >
          {{ statusLabel }}
        </span>
        <StreakCounter :streak="streak.current" :threshold="streak.threshold" />
        <button
          v-if="!hasCurrentReview"
          class="mark-reviewed-btn"
          :disabled="isMarkingReviewed || scheduleRevision.busy.value"
          @click="onMarkReviewed"
        >
          {{ isMarkingReviewed || scheduleRevision.busy.value ? "Saving…" : isReviewed ? "Update reviewed summary" : "Mark reviewed" }}
        </button>
        <button type="button" class="daily-export-btn" @click="isDailyExportOpen = true">
          Daily export
        </button>
      </div>
      <p v-if="lastError" class="error">{{ lastError }}</p>
    </header>

    <DailyExportDialog
      v-if="isDailyExportOpen"
      :date="props.date"
      :blocks="scheduleRevision.blocks.value"
      @close="isDailyExportOpen = false"
    />

    <p class="summary-label">{{ summaryLabel }}</p>
    <div class="panels">
      <CompletionBar
        :completed="review.completed_count"
        :planned="review.planned_count"
      />
      <CategoryBreakdown
        :planned="review.planned_minutes_by_category"
        :completed="review.completed_minutes_by_category"
        :window-start="schedule_window.start"
        :window-end="schedule_window.end"
        :categories="categories"
      />
      <SkippedTasks :blocks="scheduleRevision.blocks.value" :date="date" :categories="categories" :time-zone="schedule_window.time_zone" />
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
  <div v-else class="analytics-page" role="alert">
    Category data could not be loaded. <a href="">Reload the page</a> to try again.
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

.daily-export-btn {
  padding: 6px 14px;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  background: var(--bg-panel);
  color: var(--text-primary);
  font-size: 13px;
  cursor: pointer;
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
.summary-label {
  margin: 0 0 8px;
  color: var(--text-secondary);
  font-size: 13px;
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
