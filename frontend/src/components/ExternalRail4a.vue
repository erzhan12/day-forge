<script setup lang="ts">
import { computed, ref, watch } from "vue"
import type { HabiticaTask } from "../types/habitica"
import type { TodoistTask } from "../types/todoist"
import type { GoogleAccountError, NormalizedEvent, ProviderErrorBanner } from "../types/calendar"
import TodoistTasksPanel from "./TodoistTasksPanel.vue"
import HabiticaTasksSection from "./HabiticaTasksSection.vue"
import ExternalEventsPanel from "./ExternalEventsPanel.vue"
import RailSection from "./RailSection.vue"
import { civilDayDelta, formatShortCivilDate, todayString, zonedDateTime } from "../utils/date"
import { isExternalEventPast } from "../utils/externalEventPast"
import {
  readExternalRailCollapsed,
  writeExternalRailCollapsed,
  type ExternalRailCollapsed,
  type ExternalRailSection,
} from "../utils/externalRailSectionsStorage"

const props = withDefaults(defineProps<{
  activeDate: string
  timeZone?: string; todayDate?: string
  todoistTasks: TodoistTask[]; todoistLoading: boolean; todoistError: string | null; showTodoist?: boolean
  habiticaTasks: HabiticaTask[]; habiticaLoading: boolean; habiticaError: string | null; showHabitica?: boolean
  showCalendars?: boolean; events: NormalizedEvent[]; eventsLoading: boolean; eventErrors: ProviderErrorBanner[]; accountErrors: GoogleAccountError[]; externalConnected: boolean; nowMinutes: number | null
}>(), { showTodoist: false, showHabitica: false, showCalendars: false })

const emit = defineEmits<{
  todoistRetry: []; todoistComplete: [taskId: string]
  habiticaRetry: []; habiticaComplete: [taskId: string]
  refresh: []; retryExternal: [provider: "apple" | "google"]
  addToSchedule: [event: NormalizedEvent]
}>()
const open = defineModel<boolean>("open", { required: true })

// Remaining = last committed ids (not click-only); freeze that set while loading.
const todoistBaselineIds = ref<Set<string> | null>(null)
const habiticaBaselineIds = ref<Set<string> | null>(null)
const todoistRemainingIds = ref<Set<string>>(new Set())
const habiticaRemainingIds = ref<Set<string>>(new Set())
const todoistSawLoad = ref(false)
const habiticaSawLoad = ref(false)
const todoistAwaitingCommit = ref(false)
const habiticaAwaitingCommit = ref(false)
function resetProviderOnDateChange(
  loading: boolean,
  baselineIds: { value: Set<string> | null },
  remainingIds: { value: Set<string> },
  sawLoad: { value: boolean },
  awaitingCommit: { value: boolean },
) {
  baselineIds.value = null
  remainingIds.value = new Set()
  if (loading) {
    // In-flight: Vue won't re-fire loading:true, so accept that commit.
    sawLoad.value = true
    awaitingCommit.value = false
  } else {
    sawLoad.value = false
    awaitingCommit.value = true
  }
}
watch(() => [props.activeDate, props.timeZone, props.todayDate], () => {
  resetProviderOnDateChange(props.todoistLoading, todoistBaselineIds, todoistRemainingIds, todoistSawLoad, todoistAwaitingCommit)
  resetProviderOnDateChange(props.habiticaLoading, habiticaBaselineIds, habiticaRemainingIds, habiticaSawLoad, habiticaAwaitingCommit)
})
function captureBaseline(
  loading: boolean,
  tasks: { id: string }[],
  error: string | null,
  baselineIds: { value: Set<string> | null },
  remainingIds: { value: Set<string> },
  sawLoad: { value: boolean },
  awaitingCommit: { value: boolean },
) {
  if (loading) {
    sawLoad.value = true
    awaitingCommit.value = false
    return
  }
  if (error || awaitingCommit.value) return
  const ids = new Set(tasks.map((task) => task.id))
  remainingIds.value = ids
  const baseline = baselineIds.value
  if (baseline === null) {
    // Warm mount (`ids`) or empty-day commit after `sawLoad`.
    if (sawLoad.value || ids.size > 0) baselineIds.value = new Set(ids)
    return
  }
  // `∅` can grow; a non-empty baseline never shrinks, only unions new ids.
  if (baseline.size === 0) {
    if (ids.size > 0) baselineIds.value = new Set(ids)
    return
  }
  let grew = false
  const next = new Set(baseline)
  for (const id of ids) {
    if (!next.has(id)) {
      next.add(id)
      grew = true
    }
  }
  if (grew) baselineIds.value = next
}
watch(
  () => [props.todoistLoading, props.todoistError, props.todoistTasks.map((task) => task.id).join("\0")] as const,
  ([loading, error]) => {
    captureBaseline(loading, props.todoistTasks, error, todoistBaselineIds, todoistRemainingIds, todoistSawLoad, todoistAwaitingCommit)
  },
  { immediate: true },
)
watch(
  () => [props.habiticaLoading, props.habiticaError, props.habiticaTasks.map((task) => task.id).join("\0")] as const,
  ([loading, error]) => {
    captureBaseline(loading, props.habiticaTasks, error, habiticaBaselineIds, habiticaRemainingIds, habiticaSawLoad, habiticaAwaitingCommit)
  },
  { immediate: true },
)
// The rendered counter text lives here, so this is the symbol that enforces
// the label contract (feature 0105): `done / total`, or `–` before a baseline.
function progress(baselineIds: Set<string> | null, remainingIds: Set<string>) {
  if (baselineIds === null) return { label: "–", ariaLabel: "Not loaded yet", percent: 0, loaded: false }
  let done = 0
  for (const id of baselineIds) {
    if (!remainingIds.has(id)) done++
  }
  const total = baselineIds.size
  return {
    label: `${done} / ${total}`,
    ariaLabel: `${done} of ${total} completed this session`,
    percent: total === 0 ? 0 : (done / total) * 100,
    loaded: true,
  }
}
function liveRemaining(loading: boolean, tasks: { id: string }[], frozen: Set<string>) {
  return loading ? frozen : new Set(tasks.map((task) => task.id))
}
const todoistProgress = computed(() =>
  progress(todoistBaselineIds.value, liveRemaining(props.todoistLoading, props.todoistTasks, todoistRemainingIds.value)),
)
const habiticaProgress = computed(() =>
  progress(habiticaBaselineIds.value, liveRemaining(props.habiticaLoading, props.habiticaTasks, habiticaRemainingIds.value)),
)
function completeTodoist(id: string) { emit("todoistComplete", id) }
function completeHabitica(id: string) { emit("habiticaComplete", id) }
function toggle() { open.value = !open.value }

// Per-section collapse, remembered across reloads (feature 0105).
const collapsed = ref<ExternalRailCollapsed>(readExternalRailCollapsed())
function toggleSection(section: ExternalRailSection) {
  collapsed.value = { ...collapsed.value, [section]: !collapsed.value[section] }
  writeExternalRailCollapsed(collapsed.value)
}

const today = computed(() => props.todayDate ?? todayString(props.timeZone ?? "UTC"))
const railTitle = computed(() => (props.activeDate === today.value ? "Today" : formatShortCivilDate(props.activeDate)))
const railSubtitle = computed(() => formatShortCivilDate(props.activeDate))

type Peek = { text: string; tone: "plain" | "status" | "live" }

// A collapsed task section must still say what its hidden body says: the
// panel's own error (a failed completion also writes it, so never a fixed
// "couldn't load"), or a first load.
function taskPeek(error: string | null, loading: boolean, loaded: boolean): Peek | null {
  if (error) return { text: `${error} · Expand`, tone: "status" }
  if (loading && !loaded) return { text: "Loading…", tone: "live" }
  return null
}
const todoistPeek = computed(() => taskPeek(props.todoistError, props.todoistLoading, todoistProgress.value.loaded))
const habiticaPeek = computed(() => taskPeek(props.habiticaError, props.habiticaLoading, habiticaProgress.value.loaded))

function eventIsPast(ev: NormalizedEvent): boolean {
  return isExternalEventPast(ev, props.activeDate, today.value, props.nowMinutes, props.timeZone ?? "UTC")
}

// Started = zoned start folded relative to today (same folding as the end in
// isExternalEventPast), so an overnight event that began yesterday is `Now`.
function eventHasStarted(ev: NormalizedEvent): boolean {
  if (props.activeDate !== today.value || props.nowMinutes === null) return false
  const start = zonedDateTime(new Date(ev.start), props.timeZone ?? "UTC")
  return civilDayDelta(today.value, start.date) * 1440 + start.minutes <= props.nowMinutes
}

// Calendar counter and collapsed peek (feature 0105). Rules 1–3 are
// exclusive; rule 4 post-processes rule 3.
const calendarSummary = computed((): { counter: string; counterLabel: string; peek: Peek; hasError: boolean } => {
  const events = props.events
  if (events.length === 0 && props.eventsLoading) {
    return { counter: "–", counterLabel: "Loading", peek: { text: "Loading…", tone: "live" }, hasError: false }
  }
  if (events.length === 0 && (props.eventErrors.length > 0 || props.accountErrors.length > 0)) {
    return { counter: "–", counterLabel: "Unavailable", peek: { text: "Calendars unavailable · Expand", tone: "status" }, hasError: true }
  }
  const upcoming = events.filter((ev) => !eventIsPast(ev))
  const nextTimed = upcoming.find((ev) => !ev.all_day)
  const nextAllDay = upcoming.find((ev) => ev.all_day)
  let text = "Nothing upcoming"
  if (nextTimed) {
    text = eventHasStarted(nextTimed)
      ? `Now · ${nextTimed.title}`
      : `Next · ${zonedDateTime(new Date(nextTimed.start), props.timeZone ?? "UTC").hhmm} ${nextTimed.title}`
  } else if (nextAllDay) {
    text = `All day · ${nextAllDay.title}`
  }
  const counter = `${upcoming.length} upcoming`
  // Google's all-account failure yields a banner AND account errors for one
  // outage; count accounts only when there is no Google banner.
  const googleBanner = props.eventErrors.some((banner) => banner.provider === "google")
  const unavailable = props.eventErrors.length + (googleBanner ? 0 : props.accountErrors.length)
  if (unavailable > 0) {
    return { counter, counterLabel: counter, peek: { text: `${text} · ${unavailable} unavailable`, tone: "status" }, hasError: true }
  }
  if (props.eventsLoading) {
    return { counter, counterLabel: counter, peek: { text: `${text} · Loading…`, tone: "live" }, hasError: false }
  }
  return { counter, counterLabel: counter, peek: { text, tone: "plain" }, hasError: false }
})
</script>

<template>
  <aside class="external-rail-4a" :class="{ collapsed: !open }" data-testid="external-rail-4a" aria-label="External tasks and calendars">
    <header v-if="open" class="rail-header">
      <div class="rail-heading">
        <strong>{{ railTitle }}</strong>
        <small v-if="railTitle !== railSubtitle">{{ railSubtitle }}</small>
      </div>
      <span class="rail-actions">
        <button v-if="showTodoist || showHabitica" class="icon-btn" aria-label="Refresh external tasks" @click="emit('refresh')">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M13 8a5 5 0 1 1-1.46-3.54M13 3v3h-3" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /></svg>
        </button>
        <button class="icon-btn" aria-label="Collapse external sources" @click="toggle">
          <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M10 4 6 8l4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /></svg>
        </button>
      </span>
    </header>
    <button v-else class="icon-btn" aria-label="Expand external sources" @click="toggle">
      <svg viewBox="0 0 16 16" aria-hidden="true"><path d="M6 4l4 4-4 4" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round" /></svg>
    </button>
    <div v-if="open" class="rail-content">
      <RailSection
        v-if="showTodoist"
        class="task-section"
        section-id="todoist"
        title="Todoist"
        color="var(--provider-todoist)"
        :counter="todoistProgress.label"
        :counter-label="todoistProgress.ariaLabel"
        counter-test-id="todoist-session-progress"
        :percent="todoistProgress.percent"
        :has-error="Boolean(todoistError)"
        :collapsed="collapsed.todoist"
        @update:collapsed="toggleSection('todoist')"
      >
        <template v-if="todoistPeek" #peek>
          <span :role="todoistPeek.tone === 'status' ? 'status' : undefined" :aria-live="todoistPeek.tone === 'live' ? 'polite' : undefined">{{ todoistPeek.text }}</span>
        </template>
        <TodoistTasksPanel :tasks="todoistTasks" :loading="todoistLoading" :error="todoistError" @retry="emit('todoistRetry')" @complete="completeTodoist" />
      </RailSection>
      <RailSection
        v-if="showHabitica"
        class="task-section"
        section-id="habitica"
        title="Habitica"
        color="var(--provider-habitica)"
        :counter="habiticaProgress.label"
        :counter-label="habiticaProgress.ariaLabel"
        counter-test-id="habitica-session-progress"
        :percent="habiticaProgress.percent"
        :has-error="Boolean(habiticaError)"
        :collapsed="collapsed.habitica"
        @update:collapsed="toggleSection('habitica')"
      >
        <template v-if="habiticaPeek" #peek>
          <span :role="habiticaPeek.tone === 'status' ? 'status' : undefined" :aria-live="habiticaPeek.tone === 'live' ? 'polite' : undefined">{{ habiticaPeek.text }}</span>
        </template>
        <HabiticaTasksSection :tasks="habiticaTasks" :loading="habiticaLoading" :error="habiticaError" @retry="emit('habiticaRetry')" @complete="completeHabitica" />
      </RailSection>
      <RailSection
        v-if="showCalendars"
        class="calendar-section"
        section-id="calendars"
        title="Calendars"
        :counter="calendarSummary.counter"
        :counter-label="calendarSummary.counterLabel"
        counter-test-id="calendar-summary-counter"
        :has-error="calendarSummary.hasError"
        :collapsed="collapsed.calendars"
        @update:collapsed="toggleSection('calendars')"
      >
        <template #marker>
          <svg class="calendar-glyph" viewBox="0 0 16 16"><rect x="2.5" y="3.5" width="11" height="10" rx="2" fill="none" stroke="currentColor" stroke-width="1.3" /><path d="M2.5 6.5h11M5.5 2v3M10.5 2v3" stroke="currentColor" stroke-width="1.3" stroke-linecap="round" /></svg>
        </template>
        <template #peek>
          <span :role="calendarSummary.peek.tone === 'status' ? 'status' : undefined" :aria-live="calendarSummary.peek.tone === 'live' ? 'polite' : undefined">{{ calendarSummary.peek.text }}</span>
        </template>
        <ExternalEventsPanel embedded :time-zone="timeZone" :today-date="todayDate" variant="sidebar" :date="activeDate" :now-minutes="nowMinutes" :events="events" :loading="eventsLoading" :error-banners="eventErrors" :account-errors="accountErrors" :connected="externalConnected" @retry="emit('retryExternal', $event)" @add-to-schedule="emit('addToSchedule', $event)" />
      </RailSection>
    </div>
  </aside>
</template>

<style scoped>
.external-rail-4a { position:fixed; inset:0 auto 0 0; width:380px; display:flex; flex-direction:column; background:var(--bg-panel); border-right:1px solid var(--border); z-index:30; overflow:hidden; transition:width 180ms ease; }
.external-rail-4a.collapsed { width:32px; padding-top:8px; align-items:center; }
.rail-header { flex-shrink:0; display:flex; align-items:center; justify-content:space-between; gap:8px; padding:12px 14px; border-bottom:1px solid var(--border); color:var(--text-primary); }
.rail-heading { display:flex; flex-direction:column; min-width:0; }
.rail-heading strong { font-size:14px; font-weight:600; }
.rail-heading small { font-size:12px; color:var(--text-secondary); }
.rail-actions { display:flex; gap:2px; }
.icon-btn { display:inline-flex; align-items:center; justify-content:center; width:28px; height:28px; padding:0; border:0; border-radius:6px; background:transparent; color:var(--text-secondary); cursor:pointer; }
.icon-btn:hover { background:var(--bg-elevated); color:var(--text-primary); }
.icon-btn:focus { outline:none; }
.icon-btn:focus-visible { box-shadow:0 0 0 2px var(--focus-ring); }
@media (forced-colors: active) { .icon-btn:focus-visible { outline:2px solid CanvasText; outline-offset:-2px; } }
.icon-btn svg { width:16px; height:16px; }
/* Sections take their content height; the rail scrolls as a whole. */
.rail-content { flex:1 1 auto; min-height:0; display:flex; flex-direction:column; padding:6px 0 12px; overflow-y:auto; }
.calendar-glyph { width:14px; height:14px; }
/* The panels were built to fill a fixed-height sidebar; in the rail they
   take natural height (lists included) and lose their own padding/scroll. */
.rail-content :deep(.todoist-panel),
.rail-content :deep(.habitica-panel) { flex:0 0 auto; min-height:auto; overflow:visible; padding:0 6px 8px; }
.rail-content :deep(.todoist-list),
.rail-content :deep(.habitica-list),
.rail-content :deep(.todoist-skeleton),
.rail-content :deep(.habitica-skeleton) { flex:0 0 auto; min-height:auto; overflow:visible; }
.rail-content :deep(.todoist-item),
.rail-content :deep(.habitica-item) { padding:6px 8px; margin:0 -8px; border-radius:6px; }
.rail-content :deep(.todoist-item:hover),
.rail-content :deep(.habitica-item:hover) { background:var(--bg-elevated); }
.rail-content :deep(.todoist-task-title),
.rail-content :deep(.habitica-task-title) { font-weight:400; }
</style>
