import { router } from "@inertiajs/vue3"

function getCsrfToken(): string {
  const match = document.cookie.match(/XSRF-TOKEN=([^;]+)/)
  return match ? decodeURIComponent(match[1]) : ""
}

export interface ApiResult {
  ok: boolean
  data?: Record<string, unknown>
  errors?: Record<string, string | string[]>
}

async function apiFetch(
  url: string,
  method: string,
  body?: Record<string, unknown>,
): Promise<ApiResult> {
  let resp: Response
  try {
    resp = await fetch(url, {
      method,
      headers: {
        "Content-Type": "application/json",
        "X-XSRF-TOKEN": getCsrfToken(),
      },
      body: body ? JSON.stringify(body) : undefined,
    })
  } catch {
    return { ok: false, errors: { detail: "Network error. Please check your connection." } }
  }
  if (resp.ok) {
    let data: Record<string, unknown> | undefined
    const text = await resp.text()
    if (text) {
      try {
        data = JSON.parse(text)
      } catch {
        return { ok: false, errors: { detail: "Invalid server response." } }
      }
    }
    router.reload({ only: ["blocks"] })
    return { ok: true, data }
  }
  try {
    const data = await resp.json()
    return { ok: false, errors: data.errors }
  } catch {
    return { ok: false, errors: { detail: `Server error (${resp.status})` } }
  }
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
