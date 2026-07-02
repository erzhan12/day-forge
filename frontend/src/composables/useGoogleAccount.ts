// Settings-page composable for Google Calendar accounts (feature 0022).
// Mirrors `useCalendarAccount` but for the **multi-row** Google model: a
// user can connect several Google accounts, so state holds a list.
//
// `connect()` is a full-page redirect to the server-side OAuth start
// (`/api/calendar/google/connect/`) — no fetch, no commit-token machinery,
// because the browser leaves the page. `fetchAccounts()` / `disconnect(id)`
// keep the serialisation-lock + AbortController pattern from
// `useCalendarAccount` so a disconnect and a list-read can't race.

import { reactive, ref } from "vue"
import type { GoogleAccount } from "../types/calendar"
import type { ApiResult } from "./useHttp"
import { requestJson } from "./useHttp"

interface GoogleAccountState {
  accounts: GoogleAccount[]
  loading: boolean
  error: string | null
}

function defaultState(): GoogleAccountState {
  return { accounts: [], loading: false, error: null }
}

export function useGoogleAccount() {
  const state = reactive<GoogleAccountState>(defaultState())

  // Serialisation lock: a disconnect in flight blocks another disconnect and
  // a list-read (a mid-mutation read has nothing useful to read; the
  // mutation's response carries the authoritative next list).
  const operationInFlight = ref<boolean>(false)

  const listAbortController = ref<AbortController | null>(null)
  const disconnectAbortController = ref<AbortController | null>(null)

  const listReadSeq = ref<number>(0)
  const writeCompletionTick = ref<number>(0)

  function connect(): void {
    // Full-page redirect — the browser leaves the SPA, so there is no
    // response to commit-guard.
    window.location.href = "/api/calendar/google/connect/"
  }

  async function fetchAccounts(): Promise<void> {
    if (operationInFlight.value) return

    listAbortController.value?.abort()
    const controller = new AbortController()
    listAbortController.value = controller

    const seq = ++listReadSeq.value
    const tickAtEntry = writeCompletionTick.value

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

    // Drop the read if a newer read started or a write committed mid-flight.
    if (
      seq !== listReadSeq.value ||
      tickAtEntry !== writeCompletionTick.value
    ) {
      return
    }

    if (result.ok) {
      state.accounts = (result.data?.accounts as GoogleAccount[]) ?? []
    }
  }

  async function disconnect(id: number): Promise<ApiResult> {
    if (operationInFlight.value) {
      return {
        ok: false,
        errors: { detail: "Another account operation is in progress." },
      }
    }
    operationInFlight.value = true

    disconnectAbortController.value?.abort()
    const controller = new AbortController()
    disconnectAbortController.value = controller

    state.loading = true
    state.error = null

    try {
      let result
      try {
        result = await requestJson(
          `/api/calendar/google/accounts/${id}/`,
          "DELETE",
          undefined,
          { signal: controller.signal },
        )
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          // Reset loading so a cancelled disconnect doesn't leave the UI
          // stuck in a busy state. (`operationInFlight` is cleared in the
          // finally below.)
          state.loading = false
          return { ok: false, errors: { detail: "Cancelled" } }
        }
        throw err
      }

      // Bump the tick BEFORE writing state so any concurrent read sees it.
      writeCompletionTick.value++

      state.loading = false
      if (result.ok) {
        // The DELETE endpoint returns the refreshed list in the same shape
        // as GET /accounts/ — adopt it directly (no second round-trip).
        state.accounts = (result.data?.accounts as GoogleAccount[]) ?? []
        state.error = null
      } else {
        state.error = extractErrorMessage(result.errors)
      }
      return result
    } finally {
      operationInFlight.value = false
    }
  }

  return {
    state,
    connect,
    fetchAccounts,
    disconnect,
    _internals: { operationInFlight, writeCompletionTick },
  }
}

function extractErrorMessage(
  errors: Record<string, string | string[]> | undefined,
): string {
  if (!errors) return "Account operation failed"
  if (typeof errors.detail === "string") return errors.detail
  const first = Object.values(errors).flat()[0]
  return typeof first === "string" && first ? first : "Account operation failed"
}
