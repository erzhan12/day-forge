<script setup lang="ts">
import { computed, inject, toRef } from "vue"
import { ScheduleDisabledKey } from "../composables/scheduleContext"
import type {
  GoogleAccountError,
  NormalizedEvent,
  ProviderErrorBanner,
} from "../types/calendar"
import { todayString, zonedDateTime } from "../utils/date"
import { isExternalEventPast } from "../utils/externalEventPast"
import { calendarColorVar } from "../utils/calendarColor"
import { eventSourceLabel } from "../utils/eventSourceLabel"

const props = withDefaults(
  defineProps<{
    events: NormalizedEvent[]
    loading: boolean
    connected: boolean
    // Schedule date (YYYY-MM-DD) — drives past-event fading on today.
    date?: string
    timeZone?: string
    todayDate?: string
    // Minutes-since-midnight sampler from Schedule's useNowMinutes; null
    // off-today or before the first tick.
    nowMinutes?: number | null
    // `sidebar` — nested in the left Todoist sidebar (tighter margins).
    // `center` — legacy placement above the schedule body.
    variant?: "sidebar" | "center"
    // Provider failures, including Google's 200 all-account failure.
    // Rendered as NON-suppressing banners above the list — a single
    // provider's failure must not blank the other provider's healthy events.
    errorBanners?: ProviderErrorBanner[]
    // Per-account Google failures (200 + account_errors[]).
    accountErrors?: GoogleAccountError[]
    // Inside the 4a sources rail (feature 0105): the rail section owns the
    // heading, so the panel drops its own header, frame and chips and renders
    // time / calendar stripe / title rows.
    embedded?: boolean
    // Dark 4a (feature 0106): the centre variant uses the rail's row, copy
    // and Add to schedule button too. Other layouts keep today's copy.
    layout?: "4a" | "classic"
  }>(),
  {
    errorBanners: () => [],
    accountErrors: () => [],
    variant: "sidebar",
    date: () => todayString(),
    nowMinutes: null,
    timeZone: "UTC",
    embedded: false,
    layout: "classic",
  },
)

const railRows = computed(() => props.embedded || (props.variant === "center" && props.layout === "4a"))

const viewedDate = toRef(props, "date")
// todayDate is the saved-zone civil date from Schedule's useNowMinutes.
// todayString() has no Vue dependency, so a computed that only calls it
// freezes the first render's date until remount (issue #229). Re-read it
// when the page clock ticks so a missing todayDate still rolls over.
const today = computed(() => {
  if (props.todayDate) return props.todayDate
  void props.nowMinutes
  return todayString(props.timeZone)
})

function eventIsPast(ev: NormalizedEvent): boolean {
  return isExternalEventPast(
    ev,
    viewedDate.value,
    today.value,
    props.nowMinutes,
    props.timeZone,
  )
}

const emit = defineEmits<{
  (e: "retry", provider: "apple" | "google"): void
  (e: "add-to-schedule", ev: NormalizedEvent): void
}>()

// From-event add is a schedule mutation path — honor the same disable
// signal as AddBlockForm / drag / gap-click (draft generation, AI chat).
const scheduleDisabled = inject(ScheduleDisabledKey, null)
const addDisabled = computed(() => Boolean(scheduleDisabled?.value))

// Compose-time format: ISO8601 → HH:MM in viewer's local TZ. All-day
// events show a flat "All day" badge instead of a time range.
function formatTime(iso: string): string {
  return zonedDateTime(new Date(iso), props.timeZone).hhmm
}

// Two Google accounts can hold equally named calendars; the account email
// stays available on hover (0106 question 16).
function sourceTitle(ev: NormalizedEvent): string | undefined {
  return ev.account_label.trim() || undefined
}
</script>

<template>
  <!-- When not connected, render nothing (V1 simplification per the plan). -->
  <section
    v-if="connected"
    class="external-events"
    :class="{ 'external-events--center': variant === 'center', 'external-events--embedded': embedded }"
    aria-label="External calendar events"
  >
    <header v-if="!embedded" class="ee-header">
      <span class="ee-title">External Calendars</span>
      <span v-if="loading" class="ee-loading" aria-live="polite">Loading…</span>
    </header>
    <span v-else-if="loading && events.length > 0" class="ee-loading" aria-live="polite">Loading…</span>

    <!-- Whole-request provider failures. NON-suppressing: each renders as a
         banner above the list and carries its own per-provider Retry. -->
    <div
      v-for="banner in errorBanners"
      :key="`err-${banner.provider}`"
      class="ee-error"
      role="status"
      data-testid="provider-error"
    >
      <span>{{ banner.message }}</span>
      <button
        type="button"
        class="ee-retry"
        @click="emit('retry', banner.provider)"
      >
        Retry
      </button>
    </div>

    <!-- Per-account (Google) failures. Also non-suppressing — working
         accounts' events still render below. -->
    <div
      v-for="acctErr in accountErrors"
      :key="`acct-${acctErr.account_id}`"
      class="ee-account-error"
      role="status"
      data-testid="account-error"
    >
      <template v-if="acctErr.error === 'reconnect_required'">
        <span>{{ acctErr.email }} needs reconnecting.</span>
        <a class="ee-reconnect" href="/settings/#integrations">Reconnect</a>
      </template>
      <template v-else>
        <span>{{ acctErr.email }} is temporarily unavailable.</span>
      </template>
    </div>

    <!-- Event list renders whenever there are events, regardless of banners. -->
    <ul v-if="events.length > 0" class="ee-list">
      <li
        v-for="ev in events"
        :key="ev.external_uid"
        class="ee-item"
        :class="{ 'ee-item--past': eventIsPast(ev), 'ee-item--embedded': railRows }"
        :style="railRows ? { '--ee-stripe': calendarColorVar(ev.calendar_name) } : undefined"
        data-testid="external-event"
      >
        <!-- Rail row: start time | calendar-colour stripe | title + source. -->
        <template v-if="railRows">
          <span class="ee-time ee-time-col">{{ ev.all_day ? "All day" : formatTime(ev.start) }}</span>
          <span class="ee-stripe" aria-hidden="true"></span>
          <div class="ee-body">
            <span class="ee-event-title">{{ ev.title }}</span>
            <span class="ee-source" data-testid="external-event-source" :title="sourceTitle(ev)">{{ eventSourceLabel(ev) }}</span>
          </div>
        </template>
        <template v-else>
          <span class="ee-event-title">{{ ev.title }}</span>
          <div class="ee-meta">
            <span class="ee-time">
              <template v-if="ev.all_day">All day</template>
              <template v-else>{{ formatTime(ev.start) }} – {{ formatTime(ev.end) }}</template>
            </span>
            <span v-if="ev.account_label" class="ee-account-chip">{{ ev.account_label }}</span>
            <span v-else class="ee-calendar-chip">{{ ev.calendar_name }}</span>
          </div>
        </template>
        <!-- Hidden for all-day events (no timed window to map — locked). -->
        <button
          v-if="!ev.all_day"
          type="button"
          class="ee-add-btn"
          :class="{ 'df-btn df-btn--secondary': railRows }"
          :disabled="addDisabled"
          data-testid="add-to-schedule"
          @click="emit('add-to-schedule', ev)"
        >{{ railRows ? "Add to schedule" : "+ Add to schedule" }}</button>
      </li>
    </ul>

    <!-- Full-bleed empty / skeleton state ONLY when there are no events. -->
    <template v-else>
      <!-- Embedded, the panel has no header "Loading…" live text and the rail
           peek only exists while collapsed, so the skeleton announces itself. -->
      <p
        v-if="loading"
        class="ee-skeleton"
        :aria-hidden="embedded ? undefined : 'true'"
        :role="embedded ? 'status' : undefined"
        :aria-label="embedded ? 'Loading calendar events' : undefined"
      >
        <span class="ee-skel-row"></span>
        <span class="ee-skel-row"></span>
        <span class="ee-skel-row"></span>
        <span class="ee-skel-row"></span>
      </p>
      <p
        v-else-if="errorBanners.length === 0 && accountErrors.length === 0"
        class="ee-empty"
      >
        No external calendar events for this day.
      </p>
    </template>
  </section>
</template>

<style scoped>
.external-events {
  margin: 8px 12px;
  padding: 10px 12px;
  background: var(--bg-panel);
  border: 1px solid var(--border-strong);
  border-radius: 8px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  font-size: 13px;
  min-width: 0;
}

.external-events--center {
  margin: 12px 16px;
  padding: 12px 14px;
}

.ee-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  font-weight: 500;
  color: var(--text-secondary);
}

.ee-title {
  text-transform: uppercase;
  letter-spacing: 0.04em;
  font-size: 11px;
}

.ee-loading {
  font-size: 11px;
  color: var(--text-muted);
}

.ee-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  background: var(--danger-surface);
  color: var(--danger-text);
  border-radius: 6px;
}

.ee-retry {
  font-size: 11px;
  padding: 2px 8px;
  border: 1px solid var(--danger-border);
  border-radius: 4px;
  background: transparent;
  color: var(--danger-text);
  cursor: pointer;
}

.ee-add-btn {
  align-self: flex-start;
  font-size: 11px;
  padding: 2px 8px;
  border: 1px solid var(--accent);
  border-radius: 4px;
  background: transparent;
  color: var(--accent);
  cursor: pointer;
}

.ee-add-btn:hover:not(:disabled) {
  background: var(--accent);
  color: var(--accent-contrast);
}

.ee-add-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.ee-list {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.ee-item {
  display: flex;
  flex-direction: column;
  gap: 4px;
  padding: 4px 0;
  color: var(--text-primary);
  min-width: 0;
}

.ee-item--past {
  opacity: 0.55;
  color: var(--text-muted);
}

.ee-time {
  font-variant-numeric: tabular-nums;
  font-size: 12px;
  color: var(--text-secondary);
  flex-shrink: 0;
}

.ee-event-title {
  font-weight: 500;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  min-width: 0;
}

/* Title on its own row; time + account/calendar chip share the meta row so
   the title never gets squeezed out in the narrow left sidebar. */
.ee-meta {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  min-width: 0;
}

.ee-calendar-chip {
  font-size: 10px;
  text-transform: uppercase;
  letter-spacing: 0.03em;
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--bg-schedule-gap);
  color: var(--text-muted);
}

.ee-account-chip {
  font-size: 10px;
  letter-spacing: 0.02em;
  padding: 2px 6px;
  border-radius: 999px;
  background: var(--border-strong);
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
  max-width: 55%;
  flex-shrink: 1;
  min-width: 0;
}

.ee-account-error {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 8px;
  padding: 6px 8px;
  background: var(--danger-surface);
  color: var(--danger-text);
  border-radius: 6px;
  font-size: 12px;
}

.ee-reconnect {
  font-size: 11px;
  padding: 2px 8px;
  border: 1px solid var(--danger-border);
  border-radius: 4px;
  color: var(--danger-text);
  text-decoration: none;
  white-space: nowrap;
}

.ee-empty {
  margin: 0;
  font-size: 12px;
  color: var(--text-muted);
}

.ee-skeleton {
  margin: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}

/* -- Embedded in the 4a sources rail (feature 0105) -------------------- */
.external-events--embedded {
  margin: 0;
  padding: 0 6px 8px;
  background: transparent;
  border: 0;
  border-radius: 0;
}

.ee-item--embedded {
  display: grid;
  grid-template-columns: 44px 3px minmax(0, 1fr);
  column-gap: 10px;
  row-gap: 4px;
  align-items: center;
  padding: 4px 0;
}

.ee-time-col {
  align-self: start;
  padding-top: 1px;
  white-space: nowrap;
}

.ee-stripe {
  align-self: stretch;
  min-height: 28px;
  border-radius: 2px;
  background: var(--ee-stripe);
}

.ee-body {
  display: flex;
  flex-direction: column;
  gap: 2px;
  min-width: 0;
}

.ee-source {
  font-size: 12px;
  color: var(--text-muted);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.ee-item--embedded .ee-add-btn {
  grid-column: 3;
  justify-self: start;
}

/* Rail rows (embedded and the Dark 4a centre variant, feature 0106): 13 px
   meta text, and a past event dims only its stripe so the text stays
   readable. */
.ee-item--embedded .ee-time,
.ee-item--embedded .ee-source {
  font-size: 13px;
  color: var(--text-secondary);
}

.ee-item--embedded.ee-item--past {
  opacity: 1;
  color: var(--text-secondary);
}

.ee-item--embedded.ee-item--past .ee-stripe {
  opacity: 0.4;
}

.ee-skel-row {
  height: 16px;
  background: var(--bg-schedule-gap);
  border-radius: 4px;
  opacity: 0.6;
}

/* Dark 4a text floor (feature 0106): nothing below 13 px. */
html[data-theme="dark_4a"] .ee-title,
html[data-theme="dark_4a"] .ee-loading,
html[data-theme="dark_4a"] .ee-retry,
html[data-theme="dark_4a"] .ee-add-btn,
html[data-theme="dark_4a"] .ee-time,
html[data-theme="dark_4a"] .ee-calendar-chip,
html[data-theme="dark_4a"] .ee-account-chip,
html[data-theme="dark_4a"] .ee-account-error,
html[data-theme="dark_4a"] .ee-reconnect,
html[data-theme="dark_4a"] .ee-empty,
html[data-theme="dark_4a"] .ee-source {
  font-size: 13px;
}
</style>
