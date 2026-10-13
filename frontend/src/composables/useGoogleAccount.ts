import { computed, reactive } from "vue"
import type { GoogleAccount } from "../types/calendar"
import type { ApiResult } from "./useHttp"
import { useIntegrationAccount } from "./useIntegrationAccount"

interface GoogleAccountState {
  accounts: GoogleAccount[]
  loading: boolean
  error: string | null
}

export function useGoogleAccount() {
  const state = reactive<GoogleAccountState>({ accounts: [], loading: false, error: null })
  const controller = useIntegrationAccount({
    state,
    readUrl: "/api/calendar/google/accounts/",
    accept: (data) => { state.accounts = (data?.accounts as GoogleAccount[]) ?? [] },
    lockMessage: "Another account operation is in progress.",
  })

  function connect(): void {
    window.location.href = "/api/calendar/google/connect/"
  }

  function disconnect(id: number): Promise<ApiResult> {
    return controller.write(
      "disconnect",
      `/api/calendar/google/accounts/${id}/`,
      "DELETE",
    )
  }

  return {
    state,
    connect,
    fetchAccounts: controller.read,
    disconnect,
    dispose: controller.dispose,
    _internals: {
      operationInFlight: computed(() => controller.operationInFlight.value !== null),
      writeCompletionTick: controller.writeCompletionTick,
    },
  }
}
