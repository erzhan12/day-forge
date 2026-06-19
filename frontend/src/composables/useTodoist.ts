// Schedule-page composable for read-only Todoist tasks.
//
// Mirrors `useCalendar.ts` (feature 0011). Per the stale-response guard:
// two commit tokens for fetchTasks (date + sequence) because two requests
// for the same date can interleave via retry, watch double-trigger, or
// refetch after a status change. Date alone is insufficient.
//
// `fetchTasks` and `fetchAccountStatus` own independent AbortControllers
// and seqs — they write disjoint state slices, so neither can supersede
// the other.
//
// CONNECTED-STATE DIVERGENCE from `useCalendar.ts` (0020 plan): the
// Todoist panel gates purely on `connected`, so `fetchTasks` must own
// `connected` on every terminal path. `GET /api/todoist/tasks/<date>/`
// returns 503 *only* when the account row does not exist, so any non-503
// error (401/500/502/504) proves the account is connected — the
// provider/config call merely failed. We therefore set `connected = true`
// on a non-503 error (so the error surfaces past the `!connected` gate)
// and set `statusKnown = true` on every non-abort, non-stale terminal
// path (useCalendar.ts omits this on its error branch — we do not
// replicate that). The abort early-return and the stale-commit-guard
// early-return intentionally touch neither `connected` nor `statusKnown`.

import { reactive, ref } from "vue"
import type { TodoistAccountStatus, TodoistTask } from "../types/todoist"
import { todayString } from "../utils/date"
import { requestJson } from "./useHttp"

interface TodoistState {
  tasks: TodoistTask[]
  loading: boolean
  error: string | null
  connected: boolean
  // Mirrors `connected` but distinguishes "not yet checked" from a
  // resolved disconnected status — the UI hides the panel for both,
  // but tests assert on the resolved state.
  statusKnown: boolean
}

function defaultState(): TodoistState {
  return {
    tasks: [],
    loading: false,
    error: null,
    connected: false,
    statusKnown: false,
  }
}

export function useTodoist() {
  const state = reactive<TodoistState>(defaultState())

  const tasksAbortController = ref<AbortController | null>(null)
  const latestRequestedTaskDate = ref<string | null>(null)
  const tasksRequestSeq = ref<number>(0)

  const accountStatusAbortController = ref<AbortController | null>(null)
  const accountStatusRequestSeq = ref<number>(0)

  function statusToMessage(status: number | undefined): string | null {
    switch (status) {
      case 401:
        return "Todoist credentials invalid. Reconnect in Settings."
      case 502:
      case 504:
        return "Todoist service unavailable. Try again later."
      case 503:
        return null // surfaced via `connected = false` rather than an error message
      default:
        return null
    }
  }

  async function fetchTasks(date: string): Promise<void> {
    tasksAbortController.value?.abort()
    const controller = new AbortController()
    tasksAbortController.value = controller

    latestRequestedTaskDate.value = date
    const seq = ++tasksRequestSeq.value
    const expectedDate = date

    state.loading = true
    state.error = null

    const tasksUrl =
      date === todayString()
        ? `/api/todoist/tasks/${date}/?carry_overdue=1`
        : `/api/todoist/tasks/${date}/`

    let result
    try {
      result = await requestJson(
        tasksUrl,
        "GET",
        undefined,
        { signal: controller.signal },
      )
    } catch (err) {
      // AbortError — swallow silently, do NOT touch state. The
      // superseding op owns `loading` / `error`.
      if (err instanceof DOMException && err.name === "AbortError") {
        return
      }
      throw err
    }

    // Commit guard: both tokens must match the request that resolved.
    if (
      expectedDate !== latestRequestedTaskDate.value ||
      seq !== tasksRequestSeq.value
    ) {
      return
    }

    state.loading = false
    if (result.ok) {
      const tasks = (result.data?.tasks as TodoistTask[]) ?? []
      state.tasks = tasks
      state.connected = true
      state.statusKnown = true
      return
    }
    if (result.status === 503) {
      state.tasks = []
      state.connected = false
      state.statusKnown = true
      return
    }
    // Non-503 error WITH a definitive server status (401/500/502/504): a
    // 503 is returned *only* when the account row does not exist, so a real
    // HTTP error status proves the account IS connected — elevate
    // `connected` so the error surfaces past the `!connected` panel gate
    // (the deliberate divergence from useCalendar.ts). A no-status failure
    // (network/parse error → `result.status === undefined`, see useHttp.ts)
    // proves nothing about account existence, so leave `connected`
    // untouched — we must not show the panel for a user who may not be
    // connected. We still mark `statusKnown` and surface the error so a
    // user who WAS already connected sees it.
    if (result.status !== undefined) {
      state.connected = true
    }
    state.statusKnown = true
    state.error = statusToMessage(result.status) ?? extractErrorMessage(result.errors)
  }

  async function fetchAccountStatus(): Promise<void> {
    accountStatusAbortController.value?.abort()
    const controller = new AbortController()
    accountStatusAbortController.value = controller

    const seq = ++accountStatusRequestSeq.value

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

    if (seq !== accountStatusRequestSeq.value) {
      return
    }

    if (result.ok) {
      const body = result.data as TodoistAccountStatus | undefined
      state.connected = Boolean(body?.connected)
      state.statusKnown = true
    }
  }

  return { state, fetchTasks, fetchAccountStatus }
}

function extractErrorMessage(
  errors: Record<string, string | string[]> | undefined,
): string {
  if (!errors) return "Todoist fetch failed"
  if (typeof errors.detail === "string") return errors.detail
  const first = Object.values(errors).flat()[0]
  return typeof first === "string" && first ? first : "Todoist fetch failed"
}
