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

// Provider arrays hold remaining rows only. Capture the denominator on the
// date's first *committed* load — not the idle `loading: false` default
// (`useTodoist` / `useHabitica` start that way) and not the stale list
// still showing after an `activeDate` change. Completions are click-only
// so polling / optimistic rollback cannot fake work.
const todoistBaseline = ref<number | null>(null)
const habiticaBaseline = ref<number | null>(null)
const todoistCompleted = ref(new Set<string>())
const habiticaCompleted = ref(new Set<string>())
const todoistSawLoad = ref(false)
const habiticaSawLoad = ref(false)
const todoistAwaitingCommit = ref(false)
const habiticaAwaitingCommit = ref(false)
function resetProviderOnDateChange(
  loading: boolean,
  baseline: { value: number | null },
  completed: { value: Set<string> },
  sawLoad: { value: boolean },
  awaitingCommit: { value: boolean },
) {
  baseline.value = null
  completed.value = new Set()
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
  resetProviderOnDateChange(props.todoistLoading, todoistBaseline, todoistCompleted, todoistSawLoad, todoistAwaitingCommit)
  resetProviderOnDateChange(props.habiticaLoading, habiticaBaseline, habiticaCompleted, habiticaSawLoad, habiticaAwaitingCommit)
})
function captureBaseline(
  loading: boolean,
  count: number,
  error: string | null,
  baseline: { value: number | null },
  sawLoad: { value: boolean },
  awaitingCommit: { value: boolean },
) {
  if (loading) {
    sawLoad.value = true
    awaitingCommit.value = false
    return
  }
  if (baseline.value !== null || error || awaitingCommit.value) return
  // `count > 0` covers a warm mount (theme switch after tasks already
  // fetched). `sawLoad` covers the empty-day commit (`count === 0`).
  if (sawLoad.value || count > 0) baseline.value = count
}
watch(() => [props.todoistLoading, props.todoistTasks.length, props.todoistError] as const, ([loading, count, error]) => {
  captureBaseline(loading, count, error, todoistBaseline, todoistSawLoad, todoistAwaitingCommit)
}, { immediate: true })
watch(() => [props.habiticaLoading, props.habiticaTasks.length, props.habiticaError] as const, ([loading, count, error]) => {
  captureBaseline(loading, count, error, habiticaBaseline, habiticaSawLoad, habiticaAwaitingCommit)
}, { immediate: true })
function progress(baseline: number | null, completed: Set<string>) {
  if (baseline === null) return { label: "0 left", percent: 0 }
  const done = Math.min(completed.size, baseline)
  return { label: `${done} completed this session / ${baseline}`, percent: baseline === 0 ? 0 : (done / baseline) * 100 }
}
const todoistProgress = computed(() => progress(todoistBaseline.value, todoistCompleted.value))
const habiticaProgress = computed(() => progress(habiticaBaseline.value, habiticaCompleted.value))
function completeTodoist(id: string) { todoistCompleted.value = new Set(todoistCompleted.value).add(id); emit("todoistComplete", id) }
function completeHabitica(id: string) { habiticaCompleted.value = new Set(habiticaCompleted.value).add(id); emit("habiticaComplete", id) }
function toggle() { open.value = !open.value }
</script>

<template>
  <aside class="external-rail-4a" :class="{ collapsed: !open }" data-testid="external-rail-4a" aria-label="External tasks and calendars">
    <header v-if="open"><strong>Today’s sources</strong><span><button v-if="showTodoist || showHabitica" aria-label="Refresh external tasks" @click="emit('refresh')">⟳</button><button aria-label="Collapse external sources" @click="toggle">‹</button></span></header>
    <button v-else aria-label="Expand external sources" @click="toggle">›</button>
    <div v-if="open" class="rail-content">
      <section v-if="showTodoist"><div class="source-heading"><span>Todoist</span><small data-testid="todoist-session-progress">{{ todoistProgress.label }}</small></div><div class="progress"><i :style="{ width: todoistProgress.percent + '%' }" /></div><TodoistTasksPanel :tasks="todoistTasks" :loading="todoistLoading" :error="todoistError" @retry="emit('todoistRetry')" @complete="completeTodoist" /></section>
      <section v-if="showHabitica"><div class="source-heading"><span>Habitica</span><small data-testid="habitica-session-progress">{{ habiticaProgress.label }}</small></div><div class="progress"><i :style="{ width: habiticaProgress.percent + '%' }" /></div><HabiticaTasksSection :tasks="habiticaTasks" :loading="habiticaLoading" :error="habiticaError" @retry="emit('habiticaRetry')" @complete="completeHabitica" /></section>
      <section v-if="showCalendars" class="calendar-section"><div class="source-heading"><span>Внешние календари</span><small>{{ events.length }} left</small></div><ExternalEventsPanel variant="sidebar" :date="activeDate" :now-minutes="nowMinutes" :events="events" :loading="eventsLoading" :error-banners="eventErrors" :account-errors="accountErrors" :connected="externalConnected" @retry="emit('retryExternal', $event)" @add-to-schedule="emit('addToSchedule', $event)" /></section>
    </div>
  </aside>
</template>

<style scoped>
.external-rail-4a { position:fixed; inset:0 auto 0 0; width:380px; display:flex; flex-direction:column; background:#1b1d20; border-right:1px solid #26292d; z-index:30; overflow:hidden; transition:width 180ms ease; }
.external-rail-4a.collapsed { width:32px; padding-top:8px; align-items:center; }
header { display:flex; justify-content:space-between; padding:12px; border-bottom:1px solid #26292d; color:#eceae6; font-size:13px; }
button { background:transparent; color:#8e9299; border:1px solid #2f3237; border-radius:4px; min-width:28px; height:28px; }
.rail-content { overflow:auto; }
section { border-bottom:1px solid #26292d; }
.source-heading { display:flex; justify-content:space-between; gap:8px; padding:12px 12px 6px; color:#eceae6; font-size:13px; }
.source-heading small { color:#8e9299; font-size:11px; }
.progress { height:3px; margin:0 12px; background:#2a2d31; border-radius:2px; overflow:hidden; }
.progress i { display:block; height:100%; background:oklch(0.72 0.17 30); }
.calendar-section :deep(.external-events-panel) { border:0; box-shadow:none; }
</style>
