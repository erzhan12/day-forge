import { getCurrentScope, onScopeDispose, watch } from "vue"
import type { ApiResult } from "./useHttp"
import { requestJson } from "./useHttp"
import { extractErrorMessage } from "../utils/errorMessage"

export type AccountState = "unknown" | "connected" | "disconnected" | "configuration_error"
export type ResourceState = "idle" | "ready" | "credentials_error" | "provider_error" | "unavailable" | "network_error"

export interface ResourceStatus {
  loading: boolean
  error: string | null
  connected: boolean
  statusKnown: boolean
  accountState: AccountState
  resourceState: ResourceState
}

interface ResourceMeta {
  account_state: Exclude<AccountState, "unknown">
  resource_state: Exclude<ResourceState, "idle" | "network_error">
}

function parseMeta(value: unknown): ResourceMeta | undefined {
  if (typeof value !== "object" || value === null) return undefined
  const meta = value as Record<string, unknown>
  const account = meta.account_state
  const resource = meta.resource_state
  if (account !== "connected" && account !== "disconnected" && account !== "configuration_error") return undefined
  if (resource !== "ready" && resource !== "credentials_error" && resource !== "provider_error" && resource !== "unavailable") return undefined
  return { account_state: account, resource_state: resource }
}

export interface DatedResourceAdapter<T> {
  url: (date: string, refresh: boolean) => string
  decode: (data: Record<string, unknown> | undefined) => T | undefined
  clear: () => void
  commit: (value: T) => void
  // A provider may encode a failed resource read in an otherwise valid 200.
  // Returning a message retains rows for the active date/context and surfaces the failure.
  onFailedSuccess?: (value: T, meta: ResourceMeta | undefined) => string | null
  errorMessage: (status: number | undefined) => string | null
  fallbackError: string
  accountUrl: string
  decodeAccount: (data: Record<string, unknown> | undefined) => boolean | undefined
}

function isAbort(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError"
}

/** One owner for date/context validity, cancellation, and account-read arbitration. */
export function useDatedResource<T>(
  state: ResourceStatus,
  getContext: () => string,
  adapter: DatedResourceAdapter<T>,
) {
  let requestSeq = 0
  let accountSeq = 0
  let epoch = 0
  let accountGeneration = 0
  let activeKey: string | null = null
  let activeDate: string | null = null
  let requestController: AbortController | null = null
  let accountController: AbortController | null = null
  const mutationControllers = new Set<AbortController>()
  let disposed = false

  function setAccount(account: AccountState, authoritative: boolean) {
    state.accountState = account
    state.connected = account === "connected" || account === "configuration_error"
    state.statusKnown = account !== "unknown"
    if (authoritative) accountGeneration += 1
  }

  function resetResource() {
    requestController?.abort()
    requestSeq += 1
    epoch += 1
    for (const controller of mutationControllers) controller.abort()
    mutationControllers.clear()
    adapter.clear()
    state.loading = false
    state.error = null
    state.resourceState = "idle"
  }

  function invalidateAccount(account: AccountState = "disconnected") {
    accountController?.abort()
    accountSeq += 1
    resetResource()
    setAccount(account, true)
  }

  const stopContextWatch = watch(getContext, () => {
    activeKey = null
    activeDate = null
    resetResource()
    accountController?.abort()
    accountSeq += 1
  }, { flush: "sync" })

  function identity() {
    return { epoch, date: activeDate, context: getContext() }
  }

  function isCurrent(snapshot: ReturnType<typeof identity>) {
    return !disposed && snapshot.epoch === epoch && snapshot.date === activeDate && snapshot.context === getContext()
  }

  function registerMutation() {
    const controller = new AbortController()
    mutationControllers.add(controller)
    return { signal: controller.signal, release: () => mutationControllers.delete(controller) }
  }

  async function load(date: string, refresh = false): Promise<void> {
    if (disposed) return
    const context = getContext()
    const key = JSON.stringify([date, context])
    const changed = activeKey !== null && activeKey !== key
    if (changed) resetResource()
    activeKey = key
    activeDate = date

    requestController?.abort()
    const controller = new AbortController()
    requestController = controller
    const seq = ++requestSeq
    const expectedEpoch = epoch
    if (!refresh) state.loading = true
    state.error = null

    let result: ApiResult
    try {
      result = await requestJson(adapter.url(date, refresh), "GET", undefined, { signal: controller.signal })
    } catch (error) {
      if (isAbort(error)) return
      throw error
    }
    if (disposed || seq !== requestSeq || expectedEpoch !== epoch || key !== activeKey || context !== getContext()) return
    state.loading = false
    requestController = null

    const rawMeta = result.data?.meta
    const meta = parseMeta(rawMeta)
    if (result.ok) {
      const value = adapter.decode(result.data)
      if (value === undefined || (rawMeta !== undefined && (!meta || meta.account_state === "disconnected"))) {
        state.resourceState = "unavailable"
        state.error = "Invalid server response."
        return
      }
      const failedMessage = adapter.onFailedSuccess?.(value, meta)
      if (failedMessage) {
        state.resourceState = meta?.resource_state ?? "unavailable"
        state.error = failedMessage
        setAccount(meta?.account_state ?? "connected", true)
        return
      }
      adapter.commit(value)
      state.resourceState = meta?.resource_state ?? "ready"
      setAccount(meta?.account_state ?? "connected", true)
      return
    }

    // A disconnected verdict removes rows even during a background poll.
    // Other failures preserve the last successful rows for this date.
    if (meta?.account_state === "disconnected") {
      resetResource()
      state.error = null
      state.resourceState = "unavailable"
      setAccount("disconnected", true)
      return
    }
    if (meta?.account_state === "connected" || meta?.account_state === "configuration_error") {
      setAccount(meta.account_state, true)
    }
    state.resourceState = meta?.resource_state ?? (result.status === undefined ? "network_error" : "unavailable")
    state.error = (meta?.resource_state === "credentials_error" ? adapter.errorMessage(result.status) : null)
      ?? (result.status === 502 || result.status === 504 ? adapter.errorMessage(result.status) : null)
      ?? extractErrorMessage(result.errors, adapter.fallbackError)
  }

  async function fetchAccountStatus(): Promise<void> {
    if (disposed) return
    accountController?.abort()
    const controller = new AbortController()
    accountController = controller
    const seq = ++accountSeq
    const startedGeneration = accountGeneration
    const startedContext = getContext()
    try {
      const result = await requestJson(adapter.accountUrl, "GET", undefined, { signal: controller.signal })
      if (disposed || seq !== accountSeq || startedGeneration !== accountGeneration || startedContext !== getContext()) return
      accountController = null
      if (result.ok) {
        const connected = adapter.decodeAccount(result.data)
        if (connected !== undefined) setAccount(connected ? "connected" : "disconnected", false)
      }
    } catch (error) {
      if (isAbort(error)) return
      throw error
    }
  }

  function dispose() {
    if (disposed) return
    disposed = true
    stopContextWatch()
    accountController?.abort()
    accountSeq += 1
    resetResource()
  }
  if (getCurrentScope()) onScopeDispose(dispose)

  return { load, fetchAccountStatus, invalidateAccount, identity, isCurrent, registerMutation, dispose }
}
