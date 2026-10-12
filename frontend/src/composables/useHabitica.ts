import { reactive } from "vue"
import type { HabiticaTask } from "../types/habitica"
import { useDatedResource, type AccountState, type ResourceState } from "./useDatedResource"
import { useTaskCompletion } from "./useTaskCompletion"

interface HabiticaState {
  tasks: HabiticaTask[]
  loading: boolean
  error: string | null
  connected: boolean
  statusKnown: boolean
  accountState: AccountState
  resourceState: ResourceState
}

function errorMessage(status: number | undefined): string | null {
  if (status === 401) return "Habitica credentials invalid. Reconnect in Settings."
  if (status === 502 || status === 504) return "Habitica service unavailable. Try again later."
  return null
}

export function useHabitica(getContext: () => string = () => "") {
  const state = reactive<HabiticaState>({
    tasks: [], loading: false, error: null, connected: false, statusKnown: false,
    accountState: "unknown", resourceState: "idle",
  })
  let resetCompletion = () => {}
  let reconcileRows = (rows: HabiticaTask[]) => rows
  const controller = useDatedResource(state, getContext, {
    url: (date, refresh) => `/api/habitica/tasks/${date}/${refresh ? "?refresh=1" : ""}`,
    decode: (data) => Array.isArray(data?.tasks) ? data.tasks as HabiticaTask[] : undefined,
    clear: () => { state.tasks = []; resetCompletion() },
    commit: (tasks) => { state.tasks = reconcileRows(tasks) },
    errorMessage,
    fallbackError: "Habitica fetch failed",
    accountUrl: "/api/habitica/account/",
    decodeAccount: (data) => typeof data?.connected === "boolean" ? data.connected : undefined,
  })
  const completion = useTaskCompletion(controller, {
    url: (id) => `/api/habitica/tasks/${id}/complete/`,
    getRows: () => state.tasks,
    setRows: (tasks) => { state.tasks = tasks },
    setError: (error) => { state.error = error },
    errorMessage,
    fallbackError: "Habitica fetch failed",
  })
  resetCompletion = completion.reset
  reconcileRows = completion.reconcileRows
  return {
    state,
    fetchTasks: (date: string) => controller.load(date),
    refreshTasks: (date: string) => controller.load(date, true),
    completeTask: completion.completeTask,
    fetchAccountStatus: controller.fetchAccountStatus,
    invalidateAccount: controller.invalidateAccount,
    dispose: controller.dispose,
  }
}
