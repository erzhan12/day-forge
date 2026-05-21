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
        `/api/calendar/events/${date}/`,
        "GET",
        undefined,
        { signal: controller.signal },
      )
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
        "/api/calendar/account/",
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
      const body = result.data as CalDAVAccountStatus | undefined
      state.connected = Boolean(body?.connected)
      state.statusKnown = true
    }
  }

  return { state, fetchEvents, fetchAccountStatus }
}

function extractErrorMessage(
  errors: Record<string, string | string[]> | undefined,
): string {
  if (!errors) return "Calendar fetch failed"
  if (typeof errors.detail === "string") return errors.detail
  const first = Object.values(errors).flat()[0]
  return typeof first === "string" && first ? first : "Calendar fetch failed"
}
