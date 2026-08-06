// Schedule-page composable for read-only CalDAV events.
//
// Per the 0011 plan (stale-response guard section): two commit tokens
// for fetchEvents (date + sequence) because two requests for the same
// date can interleave via retry, onMounted+watch double-trigger, or
// refetch after a status change. Date alone is insufficient.
//
// `fetchEvents` and `fetchAccountStatus` own independent
// AbortControllers and seqs — they write disjoint state slices, so
// neither can supersede the other.

import { reactive, ref } from "vue"
import type { CalDAVAccountStatus, NormalizedEvent } from "../types/calendar"
import { requestJson } from "./useHttp"
import { extractErrorMessage } from "../utils/errorMessage"

interface CalendarState {
  events: NormalizedEvent[]
  loading: boolean
  error: string | null
  connected: boolean
  // Mirrors `connected` but distinguishes "not yet checked" from a
  // resolved disconnected status — the UI hides the panel for both,
  // but tests assert on the resolved state.
  statusKnown: boolean
}

function defaultState(): CalendarState {
  return {
    events: [],
    loading: false,
    error: null,
    connected: false,
    statusKnown: false,
  }
}

export function useCalendar() {
  const state = reactive<CalendarState>(defaultState())

  const eventsAbortController = ref<AbortController | null>(null)
  const latestRequestedEventDate = ref<string | null>(null)
  const eventsRequestSeq = ref<number>(0)

  const accountStatusAbortController = ref<AbortController | null>(null)
  const accountStatusRequestSeq = ref<number>(0)

  function statusToMessage(status: number | undefined): string | null {
    switch (status) {
      case 401:
        return "Apple Calendar credentials invalid. Reconnect in Settings."
      case 502:
      case 504:
        return "Apple Calendar service unavailable. Try again later."
      case 503:
        return null // surfaced via `connected = false` rather than an error message
      default:
        return null
    }
  }

  // Shared fetch body for both the initial load (`fetchEvents`) and the
  // manual/background refresh (`refreshEvents`).
  //   - `force`  → append `refresh=1` so the backend bypasses its read cache.
  //   - `silent` → skip the `loading=true` skeleton flip so existing rows
  //     stay visible during a background refresh (no skeleton flash). The
  //     commit is still atomic and the error clear / commit-guard / abort
  //     logic is unchanged.
  //   Non-503 errors: CalDAV normally leaves last-good events (unlike
  //   Google's non-silent blank). Exception: a silent refresh that
  //   supersedes an in-flight load (`state.loading` still true) blanks —
  //   otherwise a date-change fetch aborted by a poll can leave the prior
  //   day's events under the new date.
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

    // Steady-state silent poll preserves last-good rows on error; a silent
    // refresh interrupting a loading fetch does not (see header). Polarity
    // matches `useGoogleCalendar.ts`.
    const preserveOnError = silent && !state.loading

    if (!silent) {
      state.loading = true
    }
    state.error = null

    const eventsUrl = force
      ? `/api/calendar/events/${date}/?refresh=1`
      : `/api/calendar/events/${date}/`

    let result
    try {
      result = await requestJson(eventsUrl, "GET", undefined, {
        signal: controller.signal,
      })
    } catch (err) {
      // AbortError — swallow silently, do NOT touch state. The
      // superseding op owns `loading` / `error`.
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
      const events = (result.data?.events as NormalizedEvent[]) ?? []
      state.events = events
      state.connected = true
      state.statusKnown = true
      return
    }
    if (result.status === 503) {
      state.events = []
      state.connected = false
      state.statusKnown = true
      return
    }
    if (!preserveOnError) {
      state.events = []
    }
    const msg = statusToMessage(result.status)
    state.error =
      msg ?? extractErrorMessage(result.errors, "Calendar fetch failed")
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
      result = await requestJson("/api/calendar/account/", "GET", undefined, {
        signal: controller.signal,
      })
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
      const body = result.data as CalDAVAccountStatus | undefined
      state.connected = Boolean(body?.connected)
      state.statusKnown = true
    }
  }

  return { state, fetchEvents, refreshEvents, fetchAccountStatus }
}
