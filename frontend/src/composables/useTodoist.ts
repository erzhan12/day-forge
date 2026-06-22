// Schedule-page composable for Todoist tasks (read + complete + live refresh).
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

  // Shared fetch body for both the initial load (`fetchTasks`) and the
  // manual/background refresh (`refreshTasks`).
  //   - `force`  → append `refresh=1` so the backend bypasses its read cache.
  //   - `silent` → skip the `loading=true` skeleton flip so existing rows
  //     stay visible during a background refresh (no skeleton flash). The
  //     commit is still atomic and the error clear / commit-guard / abort
  //     logic is unchanged.
  async function _fetchTasks(
    date: string,
    { force = false, silent = false }: { force?: boolean; silent?: boolean } = {},
  ): Promise<void> {
    tasksAbortController.value?.abort()
    const controller = new AbortController()
    tasksAbortController.value = controller

    latestRequestedTaskDate.value = date
    const seq = ++tasksRequestSeq.value
    const expectedDate = date

    if (!silent) {
      state.loading = true
    }
    state.error = null

    // Query flags are independent: `carry_overdue=1` (browser-local today)
    // and `refresh=1` (forced cache bypass) can both apply. Preserve the
    // existing carry_overdue logic exactly.
    const params: string[] = []
    if (date === todayString()) {
      params.push("carry_overdue=1")
    }
    if (force) {
      params.push("refresh=1")
    }
    const query = params.length > 0 ? `?${params.join("&")}` : ""
    const tasksUrl = `/api/todoist/tasks/${date}/${query}`

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
    // Non-503 error proving the account row EXISTS → elevate `connected`
    // so the error surfaces past the `!connected` panel gate (the
    // deliberate divergence from useCalendar.ts). Only statuses `>= 401`
    // qualify: the tasks view returns `503` *only* on
    // `TodoistAccount.DoesNotExist`, and a `401/500/502/504` reaches the
    // auth/provider layer — both prove the row exists. A `400` (malformed
    // date) is returned *before* the account-existence check, so it does
    // NOT prove existence; and a no-status failure (network/parse error →
    // `result.status === undefined`, see useHttp.ts) proves nothing either.
    // For those we leave `connected` untouched — must not show the panel
    // for a user who may not be connected — while still marking
    // `statusKnown` and surfacing the error so an already-connected user
    // sees it.
    if (result.status !== undefined && result.status >= 401) {
      state.connected = true
    }
    state.statusKnown = true
    state.error = statusToMessage(result.status) ?? extractErrorMessage(result.errors)
  }

  // Initial / date-change load — shows the skeleton on first fetch.
  function fetchTasks(date: string): Promise<void> {
    return _fetchTasks(date, { force: false, silent: false })
  }

  // Manual Refresh (PART B) / future polling — forces a provider re-fetch
  // (cache bypass) and runs silently so the existing rows stay visible
  // (no skeleton flash). The atomic commit replaces the list on success.
  function refreshTasks(date: string): Promise<void> {
    return _fetchTasks(date, { force: true, silent: true })
  }

  // Optimistic complete with surgical rollback (PART A). The row vanishes
  // immediately; on failure the attempted task is re-inserted at its index.
  // Operates on whatever the CURRENT `state.tasks` is at success/failure
  // time (never a snapshot captured at call time) so a concurrent
  // `refreshTasks` commit is never clobbered.
  async function completeTask(taskId: string): Promise<void> {
    const idx = state.tasks.findIndex((t) => t.id === taskId)
    const removed = idx >= 0 ? state.tasks[idx] : null

    // Optimistic remove.
    state.tasks = state.tasks.filter((t) => t.id !== taskId)

    const result = await requestJson(
      `/api/todoist/tasks/${taskId}/complete/`,
      "POST",
      undefined,
    )

    if (result.ok) {
      // Idempotent re-filter against the CURRENT list: a concurrent
      // `refreshTasks` commit may have re-inserted the just-closed task
      // before this ack landed (the provider GET can race ahead of the
      // close). Re-filtering guarantees it stays gone.
      state.tasks = state.tasks.filter((t) => t.id !== taskId)
      return
    }

    // Failure → surgical re-insert into the CURRENT list, and only if the
    // task is absent (a refresh may already have re-added it). A whole-list
    // restore would resurrect a stale snapshot and drop tasks a concurrent
    // refresh added — see the plan's §Failure scenario. `connected` /
    // `statusKnown` are untouched: a completion failure does not change the
    // connection state (the sidebar is already mounted).
    if (removed && !state.tasks.some((t) => t.id === taskId)) {
      const next = state.tasks.slice()
      next.splice(Math.min(idx, next.length), 0, removed)
      state.tasks = next
    }
    state.error =
      statusToMessage(result.status) ?? extractErrorMessage(result.errors)
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

  return { state, fetchTasks, refreshTasks, completeTask, fetchAccountStatus }
}

function extractErrorMessage(
  errors: Record<string, string | string[]> | undefined,
): string {
  if (!errors) return "Todoist fetch failed"
  if (typeof errors.detail === "string") return errors.detail
  const first = Object.values(errors).flat()[0]
  return typeof first === "string" && first ? first : "Todoist fetch failed"
}
