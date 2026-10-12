import { computed, ref, watch, type Ref } from "vue"
import type { NormalizedEvent, ProviderErrorBanner } from "../types/calendar"
import type { ExternalCalendarPlacement } from "../utils/externalCalendarPlacementStorage"
import { useCalendar } from "./useCalendar"
import { useExternalSourcePoll } from "./useExternalSourcePoll"
import { useGoogleCalendar } from "./useGoogleCalendar"
import { useHabitica } from "./useHabitica"
import { useTodoist } from "./useTodoist"
import { isCurrentIntegrationBootstrap, type IntegrationBootstrap } from "./useEventImport"

export interface ExternalSourcesOptions {
  date: Ref<string>
  timeZone: Ref<string>
  todayDate: Ref<string>
  userId: Ref<number | null | undefined>
  bootstrap: Ref<IntegrationBootstrap | undefined>
  isWide: Ref<boolean>
  sidebarOpen: Ref<boolean>
  placement: Ref<ExternalCalendarPlacement>
  pollIntervalSeconds: Ref<number>
}

export function useExternalSources(options: ExternalSourcesOptions) {
  const context = () => `${options.timeZone.value}:${options.todayDate.value}`
  const calendar = useCalendar(context)
  const googleCalendar = useGoogleCalendar(context)
  const todoist = useTodoist(context)
  const habitica = useHabitica(context)
  const bootstrapEpoch = ref(0)
  let initialized = false
  let initializedUser: number | null | undefined
  let lastAppliedBootstrapId: string | undefined

  // A full Inertia visit carries a fresh snapshot. A partial date reload can
  // retain the previous prop; its date/zone metadata prevents that old
  // snapshot from restoring a source disconnected by a resource response.
  watch(
    [options.bootstrap, options.date, options.timeZone, options.userId],
    () => {
      if (options.userId.value === null) {
        if (!initialized || initializedUser !== null) {
          initialized = true
          initializedUser = null
          lastAppliedBootstrapId = undefined
          calendar.invalidateAccount("disconnected")
          googleCalendar.invalidateAccount("disconnected")
          todoist.invalidateAccount("disconnected")
          habitica.invalidateAccount("disconnected")
        }
        return
      }
      const snapshot = options.bootstrap.value
      if (isCurrentIntegrationBootstrap(snapshot, options.date.value, options.timeZone.value, options.userId.value)) {
        if (snapshot.snapshot_id !== lastAppliedBootstrapId || initializedUser !== snapshot.user_id) {
          initialized = true
          initializedUser = snapshot.user_id
          lastAppliedBootstrapId = snapshot.snapshot_id
          calendar.invalidateAccount(snapshot.connected.apple ? "connected" : "disconnected")
          googleCalendar.invalidateAccount(snapshot.connected.google ? "connected" : "disconnected")
          todoist.invalidateAccount(snapshot.connected.todoist ? "connected" : "disconnected")
          habitica.invalidateAccount(snapshot.connected.habitica ? "connected" : "disconnected")
          bootstrapEpoch.value += 1
        }
      } else if (!initialized || initializedUser !== options.userId.value) {
        // Compatibility for a stale/absent bootstrap and account switches.
        // Only account endpoints run until a provider is confirmed connected.
        const mayFetch = !(options.userId.value === undefined && typeof initializedUser === "number")
        initialized = true
        initializedUser = options.userId.value
        lastAppliedBootstrapId = undefined
        calendar.invalidateAccount("disconnected")
        googleCalendar.invalidateAccount("disconnected")
        todoist.invalidateAccount("disconnected")
        habitica.invalidateAccount("disconnected")
        if (mayFetch) {
          void calendar.fetchAccountStatus()
          void googleCalendar.fetchAccountStatus()
          void todoist.fetchAccountStatus()
          void habitica.fetchAccountStatus()
        }
      }
    },
    { immediate: true, flush: "sync" },
  )

  // Each source owns its date load. A disconnect in one provider must not
  // refetch every other connected provider as a side effect.
  watch(
    [options.date, options.timeZone, options.todayDate, bootstrapEpoch, () => calendar.state.connected],
    () => {
      if (calendar.state.statusKnown && calendar.state.connected) void calendar.fetchEvents(options.date.value)
    }, { immediate: true },
  )
  watch(
    [options.date, options.timeZone, options.todayDate, bootstrapEpoch, () => googleCalendar.state.connected],
    () => {
      if (googleCalendar.state.statusKnown && googleCalendar.state.connected) void googleCalendar.fetchEvents(options.date.value)
    }, { immediate: true },
  )
  watch(
    [options.date, options.timeZone, options.todayDate, bootstrapEpoch, () => todoist.state.connected],
    () => {
      if (todoist.state.statusKnown && todoist.state.connected) void todoist.fetchTasks(options.date.value)
    }, { immediate: true },
  )
  watch(
    [options.date, options.timeZone, options.todayDate, bootstrapEpoch, () => habitica.state.connected],
    () => {
      if (habitica.state.statusKnown && habitica.state.connected) void habitica.fetchTasks(options.date.value)
    }, { immediate: true },
  )

  const mergedExternalEvents = computed<NormalizedEvent[]>(() =>
    [...calendar.state.events, ...googleCalendar.state.events].sort((a, b) => {
      if (a.start !== b.start) return a.start < b.start ? -1 : 1
      if (a.title !== b.title) return a.title < b.title ? -1 : 1
      if (a.external_uid === b.external_uid) return 0
      return a.external_uid < b.external_uid ? -1 : 1
    }),
  )
  const externalConnected = computed(() => calendar.state.connected || googleCalendar.state.connected)
  const externalLoading = computed(() => calendar.state.loading || googleCalendar.state.loading)
  const externalErrorBanners = computed<ProviderErrorBanner[]>(() => {
    const banners: ProviderErrorBanner[] = []
    if (calendar.state.error) banners.push({ provider: "apple", message: calendar.state.error })
    if (googleCalendar.state.error) banners.push({ provider: "google", message: googleCalendar.state.error })
    return banners
  })

  function retryExternalFetch(provider: "apple" | "google") {
    if (provider === "apple" && calendar.state.connected) void calendar.fetchEvents(options.date.value)
    if (provider === "google" && googleCalendar.state.connected) void googleCalendar.fetchEvents(options.date.value)
  }
  function retryTodoistTasks() {
    if (todoist.state.connected) void todoist.fetchTasks(options.date.value)
  }
  function completeTodoistTask(taskId: string) {
    if (todoist.state.connected) void todoist.completeTask(taskId)
  }
  function retryHabiticaTasks() {
    if (habitica.state.connected) void habitica.fetchTasks(options.date.value)
  }
  function completeHabiticaTask(taskId: string) {
    if (habitica.state.connected) void habitica.completeTask(taskId)
  }
  function refreshExternalTasks(date = options.date.value) {
    if (todoist.state.statusKnown && todoist.state.connected) void todoist.refreshTasks(date)
    if (habitica.state.statusKnown && habitica.state.connected) void habitica.refreshTasks(date)
  }
  function refreshExternalCalendars(date = options.date.value) {
    if (calendar.state.statusKnown && calendar.state.connected) void calendar.refreshEvents(date)
    if (googleCalendar.state.statusKnown && googleCalendar.state.connected) void googleCalendar.refreshEvents(date)
  }

  const externalCalendarInSidebar = computed(() => options.placement.value === "sidebar")
  const externalCalendarInCenter = computed(() => options.placement.value === "center")
  const externalCalendarVisible = computed(() => externalCalendarInCenter.value ||
    (externalCalendarInSidebar.value && options.isWide.value && options.sidebarOpen.value))
  const tasksBranch = computed(() => options.isWide.value && options.sidebarOpen.value &&
    ((todoist.state.statusKnown && todoist.state.connected) ||
      (habitica.state.statusKnown && habitica.state.connected)))
  const calendarsBranch = computed(() =>
    ((calendar.state.statusKnown && calendar.state.connected) ||
      (googleCalendar.state.statusKnown && googleCalendar.state.connected)) &&
    externalCalendarVisible.value)
  const externalPollActive = computed(() => tasksBranch.value || calendarsBranch.value)
  const leftSidebarVisible = computed(() =>
    (todoist.state.statusKnown && todoist.state.connected) ||
    (habitica.state.statusKnown && habitica.state.connected) ||
    (externalConnected.value && externalCalendarInSidebar.value))

  useExternalSourcePoll({
    intervalSeconds: options.pollIntervalSeconds,
    date: options.date,
    active: externalPollActive,
    refresh: (date) => {
      if (tasksBranch.value) refreshExternalTasks(date)
      if (calendarsBranch.value) refreshExternalCalendars(date)
    },
  })

  return {
    calendar, googleCalendar, todoist, habitica,
    mergedExternalEvents, externalConnected, externalLoading, externalErrorBanners,
    retryExternalFetch, retryTodoistTasks, completeTodoistTask,
    retryHabiticaTasks, completeHabiticaTask, refreshExternalTasks, refreshExternalCalendars,
    externalCalendarInSidebar, externalCalendarInCenter, externalCalendarVisible,
    tasksBranch, calendarsBranch, externalPollActive, leftSidebarVisible,
  }
}
