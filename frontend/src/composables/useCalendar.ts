import { reactive } from "vue"
import type { NormalizedEvent } from "../types/calendar"
import { useDatedResource, type AccountState, type ResourceState } from "./useDatedResource"

interface CalendarState {
  events: NormalizedEvent[]
  loading: boolean
  error: string | null
  connected: boolean
  statusKnown: boolean
  accountState: AccountState
  resourceState: ResourceState
}

export function useCalendar(getContext: () => string = () => "") {
  const state = reactive<CalendarState>({
    events: [], loading: false, error: null, connected: false, statusKnown: false,
    accountState: "unknown", resourceState: "idle",
  })
  const controller = useDatedResource(state, getContext, {
    url: (date, refresh) => `/api/calendar/events/${date}/${refresh ? "?refresh=1" : ""}`,
    decode: (data) => Array.isArray(data?.events) ? data.events as NormalizedEvent[] : undefined,
    clear: () => { state.events = [] },
    commit: (events) => { state.events = events },
    errorMessage: (status) => {
      if (status === 401) return "Apple Calendar credentials invalid. Reconnect in Settings."
      if (status === 502 || status === 504) return "Apple Calendar service unavailable. Try again later."
      return null
    },
    fallbackError: "Calendar fetch failed",
    accountUrl: "/api/calendar/account/",
    decodeAccount: (data) => typeof data?.connected === "boolean" ? data.connected : undefined,
  })
  return {
    state,
    fetchEvents: (date: string) => controller.load(date),
    refreshEvents: (date: string) => controller.load(date, true),
    fetchAccountStatus: controller.fetchAccountStatus,
    invalidateAccount: controller.invalidateAccount,
    dispose: controller.dispose,
  }
}
