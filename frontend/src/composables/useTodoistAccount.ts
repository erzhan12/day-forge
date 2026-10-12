import { reactive } from "vue"
import type { ApiResult } from "./useHttp"
import { useIntegrationAccount } from "./useIntegrationAccount"
import type { TodoistAccountStatus } from "../types/todoist"

interface AccountState {
  status: TodoistAccountStatus | null
  loading: boolean
  error: string | null
}

const URL = "/api/todoist/account/"

export function useTodoistAccount() {
  const state = reactive<AccountState>({ status: null, loading: false, error: null })
  const controller = useIntegrationAccount({
    state,
    readUrl: URL,
    accept: (data) => { state.status = data as unknown as TodoistAccountStatus },
    lockMessage: "Another account operation is in progress. Please wait.",
  })

  function connect(payload: { token: string }): Promise<ApiResult> {
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
