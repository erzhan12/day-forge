import { getCurrentScope, onScopeDispose, ref, watch, type Ref } from "vue"
import type { TravelRule } from "../types"
import type { NormalizedEvent } from "../types/calendar"
import { matchTravelRule } from "../utils/travelRules"
import { useTravelRules } from "./useTravelRules"

export interface IntegrationBootstrap {
  snapshot_id: string
  user_id: number
  date: string
  time_zone: string
  connected: {
    apple: boolean
    google: boolean
    todoist: boolean
    habitica: boolean
  }
  travel_rules: TravelRule[]
}

export interface EventImportOptions {
  date: Ref<string>
  timeZone: Ref<string>
  userId: Ref<number | null | undefined>
  bootstrap: Ref<IntegrationBootstrap | undefined>
}

export function isCurrentIntegrationBootstrap(
  snapshot: IntegrationBootstrap | undefined,
  date: string,
  timeZone: string,
  userId: number | null | undefined,
): snapshot is IntegrationBootstrap {
  return !!snapshot && typeof userId === "number" && snapshot.user_id === userId &&
    snapshot.date === date && snapshot.time_zone === timeZone
}

export function useEventImport(options: EventImportOptions) {
  const api = useTravelRules()
  const travelRules = ref<TravelRule[]>([])
  const travelRulesReady = ref(false)
  const travelRulesError = ref(false)
  const addDialogEvent = ref<NormalizedEvent | null>(null)
  const addDialogRule = ref<TravelRule | null>(null)
  let fetchInFlight: ReturnType<typeof api.listRules> | null = null
  let fetchController: AbortController | null = null
  let generation = 0
  let initialized = false
  let initializedUser: number | null | undefined
  let lastAppliedBootstrapId: string | undefined
  let disposed = false

  function closeAddDialog() {
    addDialogEvent.value = null
    addDialogRule.value = null
  }

  watch([options.date, options.timeZone, options.userId], closeAddDialog, { immediate: true })

  function fetchTravelRules() {
    if (options.userId.value === null) return Promise.resolve({ ok: false })
    if (!fetchInFlight) {
      const controller = new AbortController()
      fetchController = controller
      const expectedGeneration = generation
      const expectedUser = options.userId.value
      const promise = api.listRules({ signal: controller.signal }).then((result) => {
        if (!disposed && expectedGeneration === generation && expectedUser === options.userId.value) {
          if (result.ok && result.rules) {
            travelRules.value = result.rules
            travelRulesReady.value = true
            travelRulesError.value = false
          } else {
            travelRulesError.value = true
          }
        }
        return result
      }).catch((error: unknown) => {
        if (error instanceof DOMException && error.name === "AbortError") return { ok: false }
        throw error
      }).finally(() => {
        if (fetchInFlight === promise) {
          fetchInFlight = null
          fetchController = null
        }
      })
      fetchInFlight = promise
    }
    return fetchInFlight
  }

  function abortRulesFetch() {
    fetchController?.abort()
    fetchController = null
    fetchInFlight = null
    generation += 1
  }

  watch([options.date, options.timeZone], () => {
    if (fetchController) {
      abortRulesFetch()
      if (!travelRulesReady.value && options.userId.value !== null) void fetchTravelRules()
    }
  }, { flush: "sync" })

  watch(
    [options.bootstrap, options.date, options.timeZone, options.userId],
    () => {
      if (options.userId.value === null) {
        if (!initialized || initializedUser !== null) {
          abortRulesFetch()
          initialized = true
          initializedUser = null
          lastAppliedBootstrapId = undefined
          travelRules.value = []
          travelRulesReady.value = false
          travelRulesError.value = false
          closeAddDialog()
        }
        return
      }
      const snapshot = options.bootstrap.value
      if (isCurrentIntegrationBootstrap(snapshot, options.date.value, options.timeZone.value, options.userId.value)) {
        if (initializedUser !== snapshot.user_id || !travelRulesReady.value || snapshot.snapshot_id !== lastAppliedBootstrapId) {
          abortRulesFetch()
          initialized = true
          initializedUser = snapshot.user_id
          lastAppliedBootstrapId = snapshot.snapshot_id
          travelRules.value = snapshot.travel_rules.map((rule) => ({ ...rule }))
          travelRulesReady.value = true
          travelRulesError.value = false
        }
      } else if (!initialized || initializedUser !== options.userId.value) {
        const mayFetch = !(options.userId.value === undefined && typeof initializedUser === "number")
        abortRulesFetch()
        initialized = true
        initializedUser = options.userId.value
        lastAppliedBootstrapId = undefined
        travelRules.value = []
        travelRulesReady.value = false
        if (mayFetch) void fetchTravelRules()
      }
    },
    { immediate: true, flush: "sync" },
  )

  async function handleAddToSchedule(event: NormalizedEvent) {
    if (options.userId.value === null) return
    if (!travelRulesReady.value) {
      const date = options.date.value
      const timeZone = options.timeZone.value
      const userId = options.userId.value
      const expectedGeneration = generation
      await fetchTravelRules()
      if (disposed || generation !== expectedGeneration || options.date.value !== date ||
        options.timeZone.value !== timeZone || options.userId.value !== userId) return
    }
    if (disposed) return
    addDialogRule.value = matchTravelRule(travelRules.value, event.title, event.calendar_name)
    addDialogEvent.value = event
  }

  if (getCurrentScope()) onScopeDispose(() => {
    disposed = true
    abortRulesFetch()
    closeAddDialog()
  })

  return {
    addDialogEvent, addDialogRule, travelRulesError,
    handleAddToSchedule, closeAddDialog,
  }
}
