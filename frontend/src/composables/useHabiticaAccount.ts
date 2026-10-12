import { reactive } from "vue"
import type { ApiResult } from "./useHttp"
import { useIntegrationAccount } from "./useIntegrationAccount"
import type { HabiticaAccountStatus } from "../types/habitica"

interface AccountState {
  status: HabiticaAccountStatus | null
  loading: boolean
  error: string | null
}

const URL = "/api/habitica/account/"

export function useHabiticaAccount() {
  const state = reactive<AccountState>({ status: null, loading: false, error: null })
  const controller = useIntegrationAccount({
    state,
    readUrl: URL,
    accept: (data) => { state.status = data as unknown as HabiticaAccountStatus },
    lockMessage: "Another account operation is in progress. Please wait.",
  })

  function connect(payload: { api_user_id: string; api_token: string }): Promise<ApiResult> {
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
