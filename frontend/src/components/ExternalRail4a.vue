<script setup lang="ts">
import { computed, ref, watch } from "vue"
import type { HabiticaTask } from "../types/habitica"
import type { TodoistTask } from "../types/todoist"
import type { GoogleAccountError, NormalizedEvent, ProviderErrorBanner } from "../types/calendar"
import TodoistTasksPanel from "./TodoistTasksPanel.vue"
import HabiticaTasksSection from "./HabiticaTasksSection.vue"
import ExternalEventsPanel from "./ExternalEventsPanel.vue"

const props = withDefaults(defineProps<{
  activeDate: string
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

// Provider arrays hold remaining rows only. Capture the denominator IDs on
// the date's first *committed* load — not the idle `loading: false` default
// (`useTodoist` / `useHabitica` start that way) and not the stale list
// still showing after an `activeDate` change. Session completions are the
// baseline IDs missing from the last successful remaining list, so a close
// in Todoist/Habitica (picked up on poll) counts the same as a Day Forge
// click. Freeze remaining while a fetch is in flight so a refresh cannot
// look like "everything completed".
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
    // Already in-flight: Vue will not re-fire the loading:true watcher, so
    // accept that request's commit instead of latching awaitingCommit.
    sawLoad.value = true
    awaitingCommit.value = false
  } else {
    sawLoad.value = false
    awaitingCommit.value = true
  }
}
watch(() => props.activeDate, () => {
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
    // `ids.size > 0` covers a warm mount (theme switch after tasks already
    // fetched). `sawLoad` covers the empty-day commit (`ids.size === 0`).
    if (sawLoad.value || ids.size > 0) baselineIds.value = new Set(ids)
    return
  }
  // Empty-day `∅` must not freeze the denominator at 0 if the next list
  // has rows. A non-empty baseline never shrinks (so 1/1 stays after the
  // last row vanishes) but *does* union newly seen ids — otherwise a
  // task added in Todoist after a 1/1 session keeps showing 1/1.
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
function progress(baselineIds: Set<string> | null, remainingIds: Set<string>) {
  if (baselineIds === null) return { label: "0 left", percent: 0 }
  let done = 0
  for (const id of baselineIds) {
    if (!remainingIds.has(id)) done++
  }
  const baseline = baselineIds.size
  return { label: `${done} completed this session / ${baseline}`, percent: baseline === 0 ? 0 : (done / baseline) * 100 }
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
</script>

<template>
  <aside class="external-rail-4a" :class="{ collapsed: !open }" data-testid="external-rail-4a" aria-label="External tasks and calendars">
    <header v-if="open"><strong>Today’s sources</strong><span><button v-if="showTodoist || showHabitica" aria-label="Refresh external tasks" @click="emit('refresh')">⟳</button><button aria-label="Collapse external sources" @click="toggle">‹</button></span></header>
    <button v-else aria-label="Expand external sources" @click="toggle">›</button>
    <div v-if="open" class="rail-content">
      <section v-if="showTodoist" class="task-section"><div class="source-heading"><span>Todoist</span><small data-testid="todoist-session-progress">{{ todoistProgress.label }}</small></div><div class="progress"><i :style="{ width: todoistProgress.percent + '%' }" /></div><TodoistTasksPanel :tasks="todoistTasks" :loading="todoistLoading" :error="todoistError" @retry="emit('todoistRetry')" @complete="completeTodoist" /></section>
      <section v-if="showHabitica" class="task-section"><div class="source-heading"><span>Habitica</span><small data-testid="habitica-session-progress">{{ habiticaProgress.label }}</small></div><div class="progress"><i :style="{ width: habiticaProgress.percent + '%' }" /></div><HabiticaTasksSection :tasks="habiticaTasks" :loading="habiticaLoading" :error="habiticaError" @retry="emit('habiticaRetry')" @complete="completeHabitica" /></section>
      <section v-if="showCalendars" class="calendar-section"><div class="source-heading"><span>Внешние календари</span><small>{{ events.length }} left</small></div><ExternalEventsPanel variant="sidebar" :date="activeDate" :now-minutes="nowMinutes" :events="events" :loading="eventsLoading" :error-banners="eventErrors" :account-errors="accountErrors" :connected="externalConnected" @retry="emit('retryExternal', $event)" @add-to-schedule="emit('addToSchedule', $event)" /></section>
    </div>
  </aside>
</template>

<style scoped>
.external-rail-4a { position:fixed; inset:0 auto 0 0; width:380px; display:flex; flex-direction:column; background:#1b1d20; border-right:1px solid #26292d; z-index:30; overflow:hidden; transition:width 180ms ease; }
.external-rail-4a.collapsed { width:32px; padding-top:8px; align-items:center; }
header { flex-shrink:0; display:flex; justify-content:space-between; padding:12px; border-bottom:1px solid #26292d; color:#eceae6; font-size:13px; }
button { background:transparent; color:#8e9299; border:1px solid #2f3237; border-radius:4px; min-width:28px; height:28px; }
.rail-content { flex:1 1 auto; min-height:0; display:flex; flex-direction:column; overflow:hidden; }
.task-section { flex:1 1 auto; min-height:0; display:flex; flex-direction:column; overflow:hidden; border-bottom:1px solid #26292d; }
.calendar-section { flex:0 0 auto; max-height:50%; min-height:0; display:flex; flex-direction:column; overflow:auto; }
.source-heading { flex-shrink:0; display:flex; justify-content:space-between; gap:8px; padding:12px 12px 6px; color:#eceae6; font-size:13px; }
.source-heading small { color:#8e9299; font-size:11px; }
.progress { flex-shrink:0; height:3px; margin:0 12px; background:#2a2d31; border-radius:2px; overflow:hidden; }
.progress i { display:block; height:100%; background:oklch(0.72 0.17 30); }
.calendar-section :deep(.external-events-panel) { border:0; box-shadow:none; }
</style>
