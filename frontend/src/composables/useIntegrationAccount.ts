import { getCurrentScope, onScopeDispose, ref } from "vue"
import type { ApiResult } from "./useHttp"
import { requestJson } from "./useHttp"
import { extractErrorMessage } from "../utils/errorMessage"

interface AccountState {
  loading: boolean
  error: string | null
}

interface AccountControllerOptions {
  state: AccountState
  readUrl: string
  accept: (data: ApiResult["data"]) => void
  lockMessage: string
}

type Operation = "connect" | "disconnect"

const cancelledResult: ApiResult = {
  ok: false,
  errors: { detail: "Cancelled" },
}

function isAbortError(error: unknown): boolean {
  return error instanceof DOMException && error.name === "AbortError"
}

/** Coordinates account reads and writes for one Settings-page instance. */
export function useIntegrationAccount(options: AccountControllerOptions) {
  const operationInFlight = ref<Operation | null>(null)
  const writeCompletionTick = ref(0)
  let readSeq = 0
  let writeSeq = 0
  let readController: AbortController | null = null
  const writeControllers = new Set<AbortController>()
  let disposed = false

  async function read(): Promise<void> {
    if (disposed || operationInFlight.value !== null) return

    readController?.abort()
    const controller = new AbortController()
    readController = controller
    const seq = ++readSeq
    const tickAtEntry = writeCompletionTick.value

    try {
      const result = await requestJson(options.readUrl, "GET", undefined, {
        signal: controller.signal,
      })
      if (
        disposed || controller.signal.aborted || seq !== readSeq ||
        tickAtEntry !== writeCompletionTick.value ||
        operationInFlight.value !== null
      ) return
      if (result.ok) options.accept(result.data)
    } catch (error) {
      if (!isAbortError(error) && !disposed && !controller.signal.aborted) throw error
    } finally {
      if (readController === controller) readController = null
    }
  }

  async function write(
    operation: Operation,
    url: string,
    method: "POST" | "DELETE",
    payload?: Record<string, unknown>,
  ): Promise<ApiResult> {
    if (disposed) return cancelledResult
    if (operationInFlight.value !== null) {
      return { ok: false, errors: { detail: options.lockMessage } }
    }

    operationInFlight.value = operation
    // A read started before this mutation cannot establish its result.
    readSeq++
    readController?.abort()
    readController = null
    const seq = ++writeSeq
    const controller = new AbortController()
    writeControllers.add(controller)
    options.state.loading = true
    options.state.error = null

    try {
      const result = await requestJson(url, method, payload, {
        signal: controller.signal,
      })
      if (disposed || controller.signal.aborted) return cancelledResult
      if (seq !== writeSeq) return result

      writeCompletionTick.value++
      if (result.ok) {
        options.accept(result.data)
        options.state.error = null
      } else {
        options.state.error = extractErrorMessage(
          result.errors,
          "Account operation failed",
        )
      }
      return result
    } catch (error) {
      if (isAbortError(error) || disposed || controller.signal.aborted) {
        return cancelledResult
      }
      throw error
    } finally {
      writeControllers.delete(controller)
      if (seq === writeSeq) {
        operationInFlight.value = null
        options.state.loading = false
      }
    }
  }

  function dispose(): void {
    if (disposed) return
    disposed = true
    readSeq++
    writeSeq++
    readController?.abort()
    for (const controller of writeControllers) controller.abort()
    readController = null
    writeControllers.clear()
    operationInFlight.value = null
    options.state.loading = false
  }

  if (getCurrentScope()) onScopeDispose(dispose)

  return { read, write, dispose, operationInFlight, writeCompletionTick }
}
