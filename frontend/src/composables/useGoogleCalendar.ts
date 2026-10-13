import { reactive } from "vue"
import type { GoogleAccountError, GoogleEventsResponse, NormalizedEvent } from "../types/calendar"
import { useDatedResource, type AccountState, type ResourceState } from "./useDatedResource"

interface GoogleCalendarState {
  events: NormalizedEvent[]
  accountErrors: GoogleAccountError[]
  loading: boolean
  error: string | null
  connected: boolean
  statusKnown: boolean
  accountState: AccountState
  resourceState: ResourceState
}

export function useGoogleCalendar(getContext: () => string = () => "") {
  const state = reactive<GoogleCalendarState>({
    events: [], accountErrors: [], loading: false, error: null,
    connected: false, statusKnown: false, accountState: "unknown", resourceState: "idle",
  })
  const controller = useDatedResource(state, getContext, {
    url: (date, refresh) => `/api/calendar/google/events/${date}/${refresh ? "?refresh=1" : ""}`,
    decode: (data) => Array.isArray(data?.events) ? data as unknown as GoogleEventsResponse : undefined,
    clear: () => { state.events = []; state.accountErrors = [] },
    commit: (body) => {
      state.events = body?.events ?? []
      state.accountErrors = body?.account_errors ?? []
    },
    onFailedSuccess: (body, meta) => {
      if (body.events.length > 0) return null
      if (meta?.resource_state === "provider_error") {
        state.accountErrors = body.account_errors ?? []
        return "Google Calendar service unavailable. Try again later."
      }
      if (meta?.resource_state === "credentials_error") {
        state.accountErrors = body.account_errors ?? []
        return "Google Calendar authorization expired. Reconnect in Settings."
      }
      return null
    },
    errorMessage: (status) => {
      if (status === 401) return "Google Calendar authorization expired. Reconnect in Settings."
      if (status === 502 || status === 504) return "Google Calendar service unavailable. Try again later."
      return null
    },
    fallbackError: "Google Calendar fetch failed",
    accountUrl: "/api/calendar/google/accounts/",
    decodeAccount: (data) => Array.isArray(data?.accounts) ? data.accounts.length > 0 : undefined,
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
