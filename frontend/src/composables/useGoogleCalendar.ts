// Schedule-page composable for read-only Google Calendar events
// (feature 0022). Mirrors `useCalendar` (CalDAV) but for the multi-account
// Google endpoint, which returns a composite
// `{events, account_errors}` payload: per-account failures come back as a
// 200 with `account_errors[]` (NOT an HTTP error), so a single revoked grant
// never blanks the panel. Only a *whole-request* HTTP failure (401/502/504)
// sets `state.error`.
//
// Same dual commit-token (date + sequence) stale-response guard as
// `useCalendar` — interleaved date navigations / retries can't clobber a
// newer fetch.

import { reactive, ref } from "vue"
import type {
  GoogleAccount,
  GoogleAccountError,
  GoogleEventsResponse,
  NormalizedEvent,
} from "../types/calendar"
import { requestJson } from "./useHttp"

interface GoogleCalendarState {
  events: NormalizedEvent[]
  loading: boolean
  error: string | null
  connected: boolean
  statusKnown: boolean
  accountErrors: GoogleAccountError[]
}

function defaultState(): GoogleCalendarState {
  return {
    events: [],
    loading: false,
    error: null,
    connected: false,
    statusKnown: false,
    accountErrors: [],
  }
}

export function useGoogleCalendar() {
  const state = reactive<GoogleCalendarState>(defaultState())

  const eventsAbortController = ref<AbortController | null>(null)
  const latestRequestedEventDate = ref<string | null>(null)
  const eventsRequestSeq = ref<number>(0)

  const accountStatusAbortController = ref<AbortController | null>(null)
  const accountStatusRequestSeq = ref<number>(0)

  function statusToMessage(status: number | undefined): string | null {
    switch (status) {
      case 401:
        return "Google Calendar authorization expired. Reconnect in Settings."
      case 502:
      case 504:
        return "Google Calendar service unavailable. Try again later."
      case 503:
        return null // surfaced via `connected = false`
      default:
        return null
    }
  }

  async function fetchEvents(date: string): Promise<void> {
    eventsAbortController.value?.abort()
    const controller = new AbortController()
    eventsAbortController.value = controller

    latestRequestedEventDate.value = date
    const seq = ++eventsRequestSeq.value
    const expectedDate = date

    state.loading = true
    state.error = null

    let result
    try {
      result = await requestJson(
        `/api/calendar/google/events/${date}/`,
        "GET",
        undefined,
        { signal: controller.signal },
      )
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return
      }
      throw err
    }

    // Commit guard: both tokens must match the request that resolved.
    if (
      expectedDate !== latestRequestedEventDate.value ||
      seq !== eventsRequestSeq.value
    ) {
      return
    }

    state.loading = false
    if (result.ok) {
      const body = result.data as unknown as GoogleEventsResponse | undefined
      state.events = body?.events ?? []
      state.accountErrors = body?.account_errors ?? []
      state.connected = true
      state.statusKnown = true
      return
    }
    if (result.status === 503) {
      state.events = []
      state.accountErrors = []
      state.connected = false
      state.statusKnown = true
      return
    }
    // Whole-request failure (no 200) → there are no valid Google events for
    // this date. Clear stale events/banners so only the error banner shows —
    // the panel is non-suppressing, so leaving them would render stale events
    // from a prior date/fetch alongside the new error.
    state.events = []
    state.accountErrors = []
    const msg = statusToMessage(result.status)
    state.error = msg ?? extractErrorMessage(result.errors)
  }

  async function fetchAccountStatus(): Promise<void> {
    accountStatusAbortController.value?.abort()
    const controller = new AbortController()
    accountStatusAbortController.value = controller

    const seq = ++accountStatusRequestSeq.value

    let result
    try {
      result = await requestJson(
        "/api/calendar/google/accounts/",
        "GET",
        undefined,
        { signal: controller.signal },
      )
    } catch (err) {
      if (err instanceof DOMException && err.name === "AbortError") {
        return
      }
      throw err
    }

    if (seq !== accountStatusRequestSeq.value) {
      return
    }

    if (result.ok) {
      const accounts = (result.data?.accounts as GoogleAccount[]) ?? []
      state.connected = accounts.length > 0
      state.statusKnown = true
    }
  }

  return { state, fetchEvents, fetchAccountStatus }
}

function extractErrorMessage(
  errors: Record<string, string | string[]> | undefined,
): string {
  if (!errors) return "Google Calendar fetch failed"
  if (typeof errors.detail === "string") return errors.detail
  const first = Object.values(errors).flat()[0]
  return typeof first === "string" && first
    ? first
    : "Google Calendar fetch failed"
}
