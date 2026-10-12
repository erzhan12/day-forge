import { reactive } from "vue"
import type { ApiResult } from "./useHttp"
import { useIntegrationAccount } from "./useIntegrationAccount"
import type { CalDAVAccountStatus } from "../types/calendar"

interface AccountState {
  status: CalDAVAccountStatus | null
  loading: boolean
  error: string | null
}

const URL = "/api/calendar/account/"

export function useCalendarAccount() {
  const state = reactive<AccountState>({ status: null, loading: false, error: null })
  const controller = useIntegrationAccount({
    state,
    readUrl: URL,
    accept: (data) => { state.status = data as unknown as CalDAVAccountStatus },
    lockMessage: "Another account operation is in progress. Please wait.",
  })

  function connect(payload: {
    apple_id: string
    password: string
    base_url?: string
  }): Promise<ApiResult> {
    return controller.write("connect", URL, "POST", payload)
  }

  function disconnect(): Promise<ApiResult> {
    return controller.write("disconnect", URL, "DELETE")
  }

  return {
    state,
    connect,
    disconnect,
    fetchAccountStatus: controller.read,
    dispose: controller.dispose,
    _internals: {
      accountOperationInFlight: controller.operationInFlight,
      writeCompletionTick: controller.writeCompletionTick,
    },
  }
}
