import type { ApiResult } from "../composables/useHttp"

export const SCHEDULE_CHANGED_RETRY_MESSAGE =
  "Your schedule changed while AI was processing. Review the updated schedule and try again."

export function isScheduleChangedConflict(result: ApiResult): boolean {
  return (
    result.status === 409 && result.errors?.detail === "schedule_changed"
  )
}
