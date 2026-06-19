// Settings-page composable for the Todoist account.
//
// Per the 0020 plan, this composable enforces (mirroring
// useCalendarAccount):
//   1. UI-level serialisation lock (`accountOperationInFlight`) so a
//      Connect + Disconnect can't race on the server. The lock blocks
//      a second mutation from even firing a network call, and also
//      blocks `fetchAccountStatus` (a mid-mutation read has nothing
//      useful to read).
//   2. Per-op AbortControllers for cancellation (component unmount).
//   3. Split commit tokens: writes share `latestAccountWriteSeq`,
//      reads have their own `statusReadSeq`, and reads additionally
//      gate on `writeCompletionTick` — a write that completed during
//      a read's flight drops the read. Why a shared seq across reads
//      and writes is wrong: it lets a read (older state observation)
//      supersede a write (newer state intent). See the scenario in
//      the plan.

import { reactive, ref } from "vue"
import type { ApiResult } from "./useHttp"
import { requestJson } from "./useHttp"
import type { TodoistAccountStatus } from "../types/todoist"

interface AccountState {
  status: TodoistAccountStatus | null
  loading: boolean
  error: string | null
}

function defaultState(): AccountState {
  return { status: null, loading: false, error: null }
}

type Operation = "connect" | "disconnect"

export function useTodoistAccount() {
  const state = reactive<AccountState>(defaultState())

  // Serialisation lock: only one connect/disconnect at a time.
  const accountOperationInFlight = ref<Operation | null>(null)

  // Per-op abort controllers (cancellation only — separate from commit guard).
  const connectAbortController = ref<AbortController | null>(null)
  const disconnectAbortController = ref<AbortController | null>(null)
  const statusAbortController = ref<AbortController | null>(null)

  // Split commit tokens — see header comment.
  const latestAccountWriteSeq = ref<number>(0)
  const statusReadSeq = ref<number>(0)
  const writeCompletionTick = ref<number>(0)

  function lockRejection(): ApiResult {
    return {
      ok: false,
      errors: {
        detail: "Another account operation is in progress. Please wait.",
      },
    }
  }

  async function connect(payload: { token: string }): Promise<ApiResult> {
    if (accountOperationInFlight.value !== null) return lockRejection()
    accountOperationInFlight.value = "connect"

    connectAbortController.value?.abort()
    const controller = new AbortController()
    connectAbortController.value = controller
    const seq = ++latestAccountWriteSeq.value

    state.loading = true
    state.error = null

    try {
      let result
      try {
        result = await requestJson(
          "/api/todoist/account/",
          "POST",
          payload,
          { signal: controller.signal },
        )
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          // Aborted writes don't commit; do nothing to state.
          return { ok: false, errors: { detail: "Cancelled" } }
        }
        throw err
      }

      if (seq !== latestAccountWriteSeq.value) {
        // Stale write — newer write seq has been issued. Drop.
        return result
      }

      // CRITICAL: bump the tick BEFORE writing state so any concurrent
      // read sees the bump on its commit check.
      writeCompletionTick.value++

      state.loading = false
      if (result.ok) {
        state.status = result.data as unknown as TodoistAccountStatus
        state.error = null
      } else {
        state.error = extractErrorMessage(result.errors)
      }
      return result
    } finally {
      // ALWAYS clear the lock, even if the commit guard dropped the
      // response — otherwise the lock leaks and freezes the UI.
      accountOperationInFlight.value = null
    }
  }

  async function disconnect(): Promise<ApiResult> {
    if (accountOperationInFlight.value !== null) return lockRejection()
    accountOperationInFlight.value = "disconnect"

    disconnectAbortController.value?.abort()
    const controller = new AbortController()
    disconnectAbortController.value = controller
    const seq = ++latestAccountWriteSeq.value

    state.loading = true
    state.error = null

    try {
      let result
      try {
        result = await requestJson(
          "/api/todoist/account/",
          "DELETE",
          undefined,
          { signal: controller.signal },
        )
      } catch (err) {
        if (err instanceof DOMException && err.name === "AbortError") {
          return { ok: false, errors: { detail: "Cancelled" } }
        }
        throw err
      }

      if (seq !== latestAccountWriteSeq.value) return result

      writeCompletionTick.value++

      state.loading = false
      if (result.ok) {
        state.status = result.data as unknown as TodoistAccountStatus
        state.error = null
      } else {
        state.error = extractErrorMessage(result.errors)
      }
      return result
    } finally {
      accountOperationInFlight.value = null
    }
  }

  async function fetchAccountStatus(): Promise<void> {
    // Reads bounce off the serialisation lock (see plan): no point
    // reading state mid-mutation — the mutation's response is the
    // authoritative next status.
    if (accountOperationInFlight.value !== null) return

    statusAbortController.value?.abort()
    const controller = new AbortController()
    statusAbortController.value = controller

    const seq = ++statusReadSeq.value
    const tickAtEntry = writeCompletionTick.value

    let result
    try {
      result = await requestJson(
        "/api/todoist/account/",
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

    // Belt-and-suspenders: if any write committed during this read's
    // flight, drop the read. The write already updated `status` to a
    // more authoritative value, and the read's payload is pre-write.
    if (
      seq !== statusReadSeq.value ||
      tickAtEntry !== writeCompletionTick.value
    ) {
      return
    }

    if (result.ok) {
      state.status = result.data as unknown as TodoistAccountStatus
    }
  }

  return {
    state,
    connect,
    disconnect,
    fetchAccountStatus,
    // Exposed for tests so the regression-coverage scenarios can probe
    // the lock-bypass cases.
    _internals: {
      accountOperationInFlight,
      writeCompletionTick,
    },
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
