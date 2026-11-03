import { getCurrentScope, onScopeDispose, reactive } from "vue"
import type { ApiResult } from "./useHttp"
import { requestJson } from "./useHttp"
import { extractErrorMessage } from "../utils/errorMessage"

const URL = "/api/user/export-token/"

export interface ExportTokenState {
  // `null` means "not yet loaded"; `false` means "loaded, no token".
  hasToken: boolean | null
  createdAt: string | null
  // Only ever populated immediately after a successful create — never
  // restored from a GET. Cleared on dismissal, revocation, or disposal.
  rawToken: string | null
  loading: boolean
  error: string | null
}

interface WriteOutcome {
  ok: boolean
}

/** A lost response (network failure, or a body lost after the headers
 * committed) does not prove the write failed server-side. */
function isUncertainOutcome(result: ApiResult): boolean {
  if (result.status === undefined) return true
  const detail = result.errors?.detail
  return typeof detail === "string" && detail.includes("interrupted")
}

/**
 * Coordinates reads/writes for one mounted `DailyExportTokenPanel` instance.
 *
 * Generation-gated like `useIntegrationAccount`: a response from a request
 * superseded by a later one, or arriving after `dispose()`, is dropped
 * rather than applied. The panel is mounted only while the Integrations
 * topic is active and keyed to the current account, so a topic exit,
 * unmount, or identity change already tears this composable down —
 * `dispose()` additionally clears `rawToken` from memory as that happens.
 */
export function useDailyExportToken() {
  const state = reactive<ExportTokenState>({
    hasToken: null,
    createdAt: null,
    rawToken: null,
    loading: false,
    error: null,
  })
  let disposed = false
  let seq = 0
  // Serializes create/revoke against each other only — a concurrent read
  // (status refresh) never blocks a write, matching `useIntegrationAccount`.
  let writeInFlight = false

  function dismissRawToken(): void {
    state.rawToken = null
  }

  async function fetchStatus(): Promise<void> {
    if (disposed) return
    const mySeq = ++seq
    state.loading = true
    try {
      const result = await requestJson(URL, "GET")
      if (disposed || mySeq !== seq) return
      if (result.ok && result.data) {
        state.hasToken = Boolean(result.data.has_token)
        state.createdAt = (result.data.created_at as string | null | undefined) ?? null
        state.error = null
      } else {
        state.error = extractErrorMessage(result.errors, "Could not load export token status.")
      }
    } finally {
      if (mySeq === seq) state.loading = false
    }
  }

  async function createToken(expectedUserId?: number): Promise<WriteOutcome> {
    if (disposed || writeInFlight) return { ok: false }
    writeInFlight = true
    const mySeq = ++seq
    state.loading = true
    state.error = null
    try {
      const result = await requestJson(URL, "POST", undefined, { expectedUserId })
      if (disposed || mySeq !== seq) return { ok: false }

      if (result.ok && result.data) {
        state.hasToken = true
        state.rawToken = (result.data.token as string | undefined) ?? null
        state.createdAt = (result.data.created_at as string | null | undefined) ?? null
        return { ok: true }
      }
      if (result.code === "token_exists") {
        state.error = "A token already exists. Revoke it, then create a new one."
        await fetchStatus()
        return { ok: false }
      }
      if (isUncertainOutcome(result)) {
        // The create may have actually committed server-side even though
        // this response was lost. Never guess — reload the real status. If
        // a token now exists but its raw value was never captured here,
        // the panel's normal Revoke-then-Create flow is the recovery path.
        state.error = "Could not confirm the request. Refreshing status…"
        await fetchStatus()
        return { ok: false }
      }
      state.error = extractErrorMessage(result.errors, "Could not create the export token.")
      return { ok: false }
    } finally {
      writeInFlight = false
      if (mySeq === seq) state.loading = false
    }
  }

  async function revokeToken(expectedUserId?: number): Promise<WriteOutcome> {
    if (disposed || writeInFlight) return { ok: false }
    writeInFlight = true
    const mySeq = ++seq
    state.loading = true
    state.error = null
    try {
      const result = await requestJson(URL, "DELETE", undefined, { expectedUserId })
      if (disposed || mySeq !== seq) return { ok: false }

      if (result.ok) {
        state.hasToken = false
        state.createdAt = null
        state.rawToken = null
        return { ok: true }
      }
      state.error = extractErrorMessage(result.errors, "Could not revoke the export token.")
      return { ok: false }
    } finally {
      writeInFlight = false
      if (mySeq === seq) state.loading = false
    }
  }

  function dispose(): void {
    if (disposed) return
    disposed = true
    seq++
    state.rawToken = null
    state.loading = false
  }

  if (getCurrentScope()) onScopeDispose(dispose)

  return { state, fetchStatus, createToken, revokeToken, dismissRawToken, dispose }
}
