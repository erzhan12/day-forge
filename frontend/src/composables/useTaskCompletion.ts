import type { ApiResult } from "./useHttp"
import { requestJson } from "./useHttp"
import { extractErrorMessage } from "../utils/errorMessage"

interface CompletionOwner {
  identity: () => { epoch: number; date: string | null; context: string }
  isCurrent: (snapshot: { epoch: number; date: string | null; context: string }) => boolean
  registerMutation: () => { signal: AbortSignal; release: () => void }
  invalidateAccount: () => void
}

/** Keeps a completed task out of GETs that began before the completion POST. */
export function useTaskCompletion<T extends { id: string }>(
  owner: CompletionOwner,
  options: {
    url: (id: string) => string
    getRows: () => T[]
    setRows: (rows: T[]) => void
    setError: (message: string | null) => void
    errorMessage: (status: number | undefined) => string | null
    fallbackError: string
  },
) {
  const pending = new Set<string>()
  const completed = new Set<string>()

  function reset() {
    pending.clear()
    completed.clear()
  }

  function filterRows(rows: T[]): T[] {
    return rows.filter((row) => !pending.has(row.id) && !completed.has(row.id))
  }

  function reconcileRows(rows: T[]): T[] {
    const returnedIds = new Set(rows.map((row) => row.id))
    for (const id of completed) {
      if (!returnedIds.has(id)) completed.delete(id)
    }
    return filterRows(rows)
  }

  async function completeTask(taskId: string): Promise<void> {
    const snapshot = owner.identity()
    if (!owner.isCurrent(snapshot) || pending.has(taskId) || completed.has(taskId)) return
    const rows = options.getRows()
    const index = rows.findIndex((row) => row.id === taskId)
    if (index < 0) return
    const removed = rows[index]
    pending.add(taskId)
    options.setRows(filterRows(rows))
    const mutation = owner.registerMutation()
    let result: ApiResult
    try {
      result = await requestJson(options.url(taskId), "POST", undefined, { signal: mutation.signal })
    } catch (error) {
      if (error instanceof DOMException && error.name === "AbortError") return
      throw error
    } finally {
      mutation.release()
    }
    if (!owner.isCurrent(snapshot)) return
    const meta = result.data?.meta as { account_state?: string; resource_state?: string } | undefined
    if (meta?.account_state === "disconnected") {
      owner.invalidateAccount()
      return
    }
    pending.delete(taskId)
    if (result.ok) {
      completed.add(taskId)
      options.setRows(filterRows(options.getRows()))
      return
    }
    if (removed && !options.getRows().some((row) => row.id === taskId)) {
      const next = options.getRows().slice()
      next.splice(Math.min(index, next.length), 0, removed)
      options.setRows(next)
    }
    const providerMessage = result.status === 401
      ? (result.code === "integration_credentials_error" && meta?.resource_state === "credentials_error"
          ? options.errorMessage(result.status) : null)
      : options.errorMessage(result.status)
    options.setError(providerMessage ?? extractErrorMessage(result.errors, options.fallbackError))
  }

  return { completeTask, reconcileRows, reset }
}
