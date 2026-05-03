import { router } from "@inertiajs/vue3"
import { type ApiResult, requestJson } from "./useHttp"

export type { ApiResult }

async function apiFetch(
  url: string,
  method: string,
  body?: Record<string, unknown>,
): Promise<ApiResult> {
  const result = await requestJson(url, method, body)
  if (result.ok) {
    router.reload({ only: ["blocks", "schedule"] })
  }
  return result
}

export function useSchedule(date: string) {
  function createBlock(data: {
    title: string
    start_time: string
    end_time: string
    category: string
  }): Promise<ApiResult> {
    return apiFetch(`/api/schedules/${date}/blocks/`, "POST", data)
  }

  function updateBlock(
    id: number,
    data: Record<string, unknown>,
  ): Promise<ApiResult> {
    return apiFetch(`/api/blocks/${id}/`, "PATCH", data)
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
    }>,
  ): Promise<ApiResult> {
    return apiFetch("/api/blocks/reorder/", "POST", { updates })
  }

  function restoreBlocks(
    targetDate: string,
    blocks: Array<{
      title: string
      start_time: string
      end_time: string
      category: string
      is_completed: boolean
      sort_order: number
    }>,
  ): Promise<ApiResult> {
    return apiFetch(
      `/api/schedules/${targetDate}/blocks/restore/`,
      "POST",
      { blocks },
    )
  }

  return { createBlock, updateBlock, deleteBlock, reorderBlocks, restoreBlocks }
}
