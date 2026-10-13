import { type DateSource, readDate } from "../utils/dateSource"
import { type ApiResult, type RequestOptions, requestJson } from "./useHttp"

import { useScheduleRevision, runScheduleMutation, type ScheduleRevisionState } from "./useScheduleRevision"

export type { ApiResult }

export interface ScheduleRequestOptions extends RequestOptions {
  scheduleDate?: string
  expectedRevision?: number
  kind?: "forward" | "undo"
}

export function useSchedule(date: DateSource, explicitRevision?: ScheduleRevisionState) {
  const revision = useScheduleRevision(explicitRevision)

  async function apiFetch(
    url: string,
    method: string,
    body: Record<string, unknown> = {},
    options?: ScheduleRequestOptions,
    targetDate = options?.scheduleDate ?? readDate(date),
  ): Promise<ApiResult> {
    return runScheduleMutation(revision, targetDate, (capture) =>
      requestJson(url, method, { ...body, expected_revision: capture.revision }, { ...options, expectedUserId: capture.userId }),
      { expectedRevision: options?.expectedRevision, kind: options?.kind },
    )
  }

  function createBlock(data: {
    title: string
    start_time: string
    end_time: string
    category: string
  }): Promise<ApiResult> {
    return apiFetch(`/api/schedules/${readDate(date)}/blocks/`, "POST", data)
  }

  // From-event create (feature 0026): the only client path allowed to
  // submit off-grid times (external events carry arbitrary minutes).
  function createBlockFromEvent(data: {
    title: string
    start_time: string
    end_time: string
    category: string
  }): Promise<ApiResult> {
    return apiFetch(
      `/api/schedules/${readDate(date)}/blocks/from-event/`,
      "POST",
      data,
    )
  }

  function updateBlock(
    id: number,
    data: Record<string, unknown>,
    options?: ScheduleRequestOptions,
  ): Promise<ApiResult> {
    return apiFetch(`/api/blocks/${id}/`, "PATCH", data, options)
  }

  function deleteBlock(id: number): Promise<ApiResult> {
    return apiFetch(`/api/blocks/${id}/`, "DELETE")
  }

  function reorderBlocks(
    updates: Array<{
      id: number
      start_time: string
      end_time: string
      sort_order: number
      restore_proof?: string
    }>,
  ): Promise<ApiResult> {
    return apiFetch("/api/blocks/reorder/", "POST", { updates })
  }

  function restoreBlocks(
    targetDate: string,
    blocks: Array<{
      id?: number
      title: string
      start_time: string
      end_time: string
      category: string
      is_completed: boolean
      sort_order: number
    }>,
    expectedRevision: number,
  ): Promise<ApiResult> {
    return apiFetch(
      `/api/schedules/${targetDate}/blocks/restore/`,
      "POST",
      { blocks },
      { expectedRevision, kind: "undo" },
      targetDate,
    )
  }

  return {
    createBlock,
    createBlockFromEvent,
    updateBlock,
    deleteBlock,
    reorderBlocks,
    restoreBlocks,
  }
}
