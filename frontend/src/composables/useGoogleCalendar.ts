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
import { extractErrorMessage } from "../utils/errorMessage"

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

  // Shared fetch body for both the initial load (`fetchEvents`) and the
  // manual/background refresh (`refreshEvents`).
  //   - `force`  → append `refresh=1` so the backend bypasses its read cache.
  //   - `silent` → skip the `loading=true` skeleton flip so existing rows
  //     stay visible during a background refresh (no skeleton flash). On a
  //     whole-request (non-503, non-ok) failure, a *steady-state* silent
  //     refresh also leaves last-good events/accountErrors on screen (only
  //     sets `error`). If silent supersedes an in-flight non-silent load
  //     (`state.loading` still true), blank on failure — otherwise a
  //     date-change fetch aborted by a poll could leave the prior day's
  //     events under the new date.
  async function _fetchEvents(
    date: string,
    {
      force = false,
      silent = false,
    }: { force?: boolean; silent?: boolean } = {},
  ): Promise<void> {
    eventsAbortController.value?.abort()
    const controller = new AbortController()
    eventsAbortController.value = controller

    latestRequestedEventDate.value = date
    const seq = ++eventsRequestSeq.value
    const expectedDate = date

    // Capture before flipping loading: steady-state silent polls preserve
    // last-good rows on error; silent that interrupts a loading fetch does not.
    const preserveOnError = silent && !state.loading

    if (!silent) {
      state.loading = true
    }
    state.error = null

    const eventsUrl = force
      ? `/api/calendar/google/events/${date}/?refresh=1`
      : `/api/calendar/google/events/${date}/`

    let result
    try {
      result = await requestJson(eventsUrl, "GET", undefined, {
        signal: controller.signal,
      })
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
    // Whole-request failure (no 200).
    if (!preserveOnError) {
      state.events = []
      state.accountErrors = []
    }
    const msg = statusToMessage(result.status)
    state.error =
      msg ?? extractErrorMessage(result.errors, "Google Calendar fetch failed")
  }

  // Initial / date-change load — shows the skeleton on first fetch.
  function fetchEvents(date: string): Promise<void> {
    return _fetchEvents(date, { force: false, silent: false })
  }

  // Background poll / forced re-fetch — cache bypass, silent so existing
  // events stay visible (no skeleton flash). Atomic commit on success.
  function refreshEvents(date: string): Promise<void> {
    return _fetchEvents(date, { force: true, silent: true })
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

  return { state, fetchEvents, refreshEvents, fetchAccountStatus }
}
