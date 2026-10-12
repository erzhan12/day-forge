import { computed, getCurrentInstance, inject, onUnmounted, provide, readonly, shallowReadonly, ref, watch, type InjectionKey, type Ref } from "vue"
import { router } from "@inertiajs/vue3"
import type { Schedule, TimeBlock } from "../types"
import { readDate, type DateSource } from "../utils/dateSource"
import type { ApiResult } from "./useHttp"
import { useScheduleWriteCoordinator, type ScheduleWriteCoordinator } from "./scheduleWriteCoordinator"

export const SCHEDULE_CHANGED_MESSAGE = "Schedule changed. Refresh the page and try again."
export type MutationPhase = "idle" | "saving" | "synchronizing" | "conflict"
export type ScopeResetReason = "date" | "context" | "user" | "session" | "dispose"
export interface ScheduleRevisionCapture {
  date: string
  revision: number
  generation: number
  userGeneration: number
  userId?: number
  previousBlocks: TimeBlock[]
}
export interface ScheduleMutationOptions {
  expectedRevision?: number
  only?: string[]
  kind?: "forward" | "undo"
}
export interface ScheduleRevisionOptions {
  getContextKey?: () => string
  getBlocks?: () => TimeBlock[]
  getUserId?: () => number | null | undefined
  coordinator?: ScheduleWriteCoordinator
}
export interface ScheduleRevisionState {
  revision: Readonly<Ref<number | null>>
  schedule: Readonly<Ref<Schedule | null>>
  blocks: Readonly<Ref<TimeBlock[]>>
  phase: Readonly<Ref<MutationPhase>>
  busy: Readonly<Ref<boolean>>
  synchronizing: Readonly<Ref<boolean>>
  capture: (date: string) => ScheduleRevisionCapture | null
  begin: (date: string, expectedRevision?: number, only?: string[]) => ScheduleRevisionCapture | null
  settle: (capture: ScheduleRevisionCapture, result: ApiResult, options?: ScheduleMutationOptions) => Promise<ApiResult>
  accept: (capture: ScheduleRevisionCapture, data: ApiResult["data"]) => boolean
  invalidate: (capture: ScheduleRevisionCapture) => void
  isCurrent: (capture: ScheduleRevisionCapture) => boolean
  subscribeInvalidation: (listener: (date: string, reason: string) => void) => () => void
  subscribeScopeReset: (listener: (reason: ScopeResetReason) => void) => () => void
  reset: (reason?: ScopeResetReason) => void
}
export const ScheduleRevisionKey: InjectionKey<ScheduleRevisionState> = Symbol("scheduleRevision")
function validRevision(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value) && value >= 0
}
function validSchedule(value: unknown, date: string): value is Schedule {
  if (!value || typeof value !== "object") return false
  const schedule = value as Schedule
  return schedule.date === date && validRevision(schedule.revision) && Number.isSafeInteger(schedule.id)
    && ["draft", "active", "reviewed"].includes(schedule.status)
}
function validBlocks(value: unknown): value is TimeBlock[] {
  return Array.isArray(value) && value.every((block) => block && typeof block === "object"
    && Number.isSafeInteger(block.id) && typeof block.title === "string"
    && typeof block.start_time === "string" && typeof block.end_time === "string"
    && typeof block.category === "string" && typeof block.is_completed === "boolean"
    && Number.isSafeInteger(block.sort_order))
}
function cloneBlocks(blocks: readonly TimeBlock[]): TimeBlock[] { return blocks.map((block) => ({ ...block })) }
function sameBlocks(a: readonly TimeBlock[], b: readonly TimeBlock[]): boolean {
  return a.length === b.length && a.every((block, i) => Object.keys(block).every((key) => block[key as keyof TimeBlock] === b[i][key as keyof TimeBlock]))
}

// One page owns both the visible snapshot and the writer lease. Server responses
// can replace this snapshot atomically; props are only the bootstrap/reload input.
export function createScheduleRevision(
  date: DateSource,
  getSchedule: () => Pick<Schedule, "date" | "revision"> | undefined,
  options: ScheduleRevisionOptions = {},
): ScheduleRevisionState {
  const revision = ref<number | null>(null)
  const schedule = ref<Schedule | null>(null)
  const blocks = ref<TimeBlock[]>([])
  const phase = ref<MutationPhase>("idle")
  const busy = computed(() => phase.value !== "idle")
  const synchronizing = computed(() => phase.value === "synchronizing" || phase.value === "conflict")
  let currentDate = readDate(date)
  let currentUser = options.getUserId?.()
  let currentContext = options.getContextKey?.()
  let generation = 0
  let userGeneration = 0
  let highestRevision = -1
  let disposed = false
  const coordinator = options.coordinator
  let activeCapture: ScheduleRevisionCapture | null = null
  const writeTickets = new Map<ScheduleRevisionCapture, ReturnType<ScheduleWriteCoordinator["track"]>>()
  let handoffGeneration: number | null = null
  let handoffReadInFlight: number | null = null
  const pendingWrites = new Map<ScheduleRevisionCapture, { done: Promise<void>; release: () => void }>()
  let contextGateGeneration: number | null = null
  let lastPropsSchedule: Pick<Schedule, "date" | "revision"> | undefined
  let userScheduleBarrier: Pick<Schedule, "date" | "revision"> | undefined
  const invalidationListeners = new Set<(date: string, reason: string) => void>()
  const scopeListeners = new Set<(reason: ScopeResetReason) => void>()
  const invalidateHistory = (targetDate: string, reason: string) => invalidationListeners.forEach((fn) => fn(targetDate, reason))

  function reset(reason: ScopeResetReason = "session") {
    if (reason === "session" || reason === "user") coordinator?.clear()
    generation += 1
    handoffGeneration = null
    handoffReadInFlight = null
    contextGateGeneration = reason === "context" ? generation : null
    if (reason !== "date") userGeneration += 1
    activeCapture = null
    revision.value = null
    schedule.value = null
    blocks.value = []
    highestRevision = -1
    phase.value = "synchronizing"
    scopeListeners.forEach((fn) => fn(reason))
    if (reason === "dispose" || reason === "session") disposed = true
  }
  async function reconcileContext(contextGeneration: number, pending: Promise<void>[]) {
    await Promise.all(pending)
    const current = () => !disposed && generation === contextGeneration && contextGateGeneration === contextGeneration
    if (!current()) return
    // No old writer can still commit after this read begins. A successful
    // reload is the only authority allowed to release the context gate.
    const success = await refreshSchedule(["schedule_window"], current)
    if (!current() || !success) return
    if (ingestProps(true, contextGeneration) && current()) contextGateGeneration = null
  }
  function syncScope() {
    if (disposed) return
    const nextDate = readDate(date)
    const nextUser = options.getUserId?.()
    const nextContext = options.getContextKey?.()
    if (nextContext !== currentContext) {
      currentContext = nextContext
      if (!disposed && nextDate === currentDate && nextUser === currentUser) {
        userScheduleBarrier = lastPropsSchedule
        const pending = [...pendingWrites.entries()]
          .filter(([capture]) => capture.date === currentDate && capture.userId === (currentUser ?? undefined))
          .map(([, write]) => write.done)
        reset("context")
        const contextGeneration = generation
        void reconcileContext(contextGeneration, pending)
      }
    }
    if (nextUser !== currentUser) {
      userScheduleBarrier = lastPropsSchedule
      currentUser = nextUser
      disposed = false
      reset("user")
    }
    if (nextDate !== currentDate) {
      currentDate = nextDate
      reset("date")
    }
  }
  function ingestProps(authoritativeContextRead = false, expectedGeneration?: number): boolean {
    syncScope()
    if (expectedGeneration !== undefined && generation !== expectedGeneration) return false
    if (disposed || (options.getUserId && currentUser === null)) return false
    if (handoffGeneration === generation && !authoritativeContextRead) return false
    if (contextGateGeneration !== null && !authoritativeContextRead) return false
    const next = getSchedule()
    if (userScheduleBarrier && next === userScheduleBarrier) return false
    if (next?.date !== currentDate || !validRevision(next.revision) || next.revision < highestRevision) return false
    const incoming = options.getBlocks?.()
    // A newer canonical response wins over old props, even when the old
    // response happens to have the same revision but a different snapshot.
    if (next.revision === highestRevision && schedule.value && incoming && !sameBlocks(incoming, blocks.value) && phase.value === "idle") return false
    if (revision.value !== null && next.revision > highestRevision) invalidateHistory(currentDate, "external")
    userScheduleBarrier = undefined
    lastPropsSchedule = next
    highestRevision = next.revision
    revision.value = next.revision
    schedule.value = { ...next } as Schedule
    if (incoming) blocks.value = cloneBlocks(incoming)
    if (!activeCapture) phase.value = "idle"
    if (typeof currentUser === "number") coordinator?.acknowledge(currentUser, currentDate, next.revision, authoritativeContextRead)
    return true
  }
  function checkHandoff() {
    syncScope()
    if (disposed || activeCapture || typeof currentUser !== "number") return
    const record = coordinator?.inspect(currentUser, currentDate)
    if (!record) return
    const propsRevision = getSchedule()?.revision
    if (handoffGeneration === generation) {
      if (handoffReadInFlight !== generation && !record.pending.length && !record.dirty
        && validRevision(propsRevision) && propsRevision >= record.floor) {
        handoffGeneration = null
        ingestProps()
      }
      return
    }
    // The current owner already has a confirmed newer response. Its retained
    // Inertia props may still be old until another page visit completes.
    if (revision.value !== null && revision.value >= record.floor && !record.dirty && !record.pending.length) return
    if (!record.pending.length && !record.dirty && (!validRevision(propsRevision) || propsRevision >= record.floor)) return
    const capturedGeneration = generation
    const capturedUser = currentUser
    const capturedDate = currentDate
    handoffGeneration = capturedGeneration
    revision.value = null
    schedule.value = null
    blocks.value = []
    phase.value = "synchronizing"
    invalidateHistory(capturedDate, "external")
    void (async () => {
      await Promise.all(record.pending)
      const current = () => !disposed && generation === capturedGeneration
        && currentUser === capturedUser && currentDate === capturedDate
      if (!current()) return
      const settled = coordinator?.inspect(capturedUser, capturedDate)
      if (settled?.pending.length) { handoffGeneration = null; checkHandoff(); return }
      const latestProps = getSchedule()
      if (!settled?.dirty && validRevision(latestProps?.revision) && latestProps.revision >= (settled?.floor ?? -1)) {
        handoffGeneration = null
        ingestProps()
        return
      }
      handoffReadInFlight = capturedGeneration
      const refreshed = await refreshSchedule(settled?.only, current)
      if (handoffReadInFlight === capturedGeneration) handoffReadInFlight = null
      if (!current()) return
      const refreshedRevision = getSchedule()?.revision
      if (refreshed && validRevision(refreshedRevision) && refreshedRevision >= (settled?.floor ?? -1)
        && ingestProps(true, capturedGeneration)) {
        const revisionAfterRead = revision.value
        if (revisionAfterRead !== null && revisionAfterRead >= (settled?.floor ?? -1)) {
          coordinator?.acknowledge(capturedUser, capturedDate, revisionAfterRead, true)
          handoffGeneration = null
          phase.value = "idle"
        }
      }
    })()
  }
  watch(() => [readDate(date), options.getUserId?.(), options.getContextKey?.(), getSchedule(), options.getBlocks?.()] as const,
    () => { checkHandoff(); ingestProps() }, { immediate: true })
  function isCurrent(capture: ScheduleRevisionCapture) {
    syncScope()
    return !disposed && capture.date === currentDate && capture.generation === generation
  }
  function capture(requestDate: string): ScheduleRevisionCapture | null {
    const previousDate = currentDate
    syncScope()
    if (previousDate !== currentDate && !disposed && !activeCapture) ingestProps()
    if (disposed || busy.value || handoffGeneration === generation || requestDate !== currentDate
      || revision.value === null || (options.getUserId && currentUser === null)) return null
    return { date: currentDate, revision: revision.value, generation, userGeneration, userId: currentUser ?? undefined, previousBlocks: cloneBlocks(blocks.value) }
  }
  function accept(captured: ScheduleRevisionCapture, data: ApiResult["data"]): boolean {
    const next = data?.schedule
    if (!validRevision(data?.revision) || !validSchedule(next, captured.date) || next.revision !== data.revision) return false
    if (!isCurrent(captured)) return true
    if (data.revision < highestRevision) return false
    if (!validBlocks(data.blocks)) {
      // Ask/no-op responses can retain the known snapshot only at the
      // captured revision. A changed revision requires complete blocks.
      if (data.revision !== captured.revision || revision.value !== captured.revision) return false
    } else blocks.value = cloneBlocks(data.blocks)
    highestRevision = data.revision
    revision.value = data.revision
    schedule.value = { ...next }
    return true
  }
  function invalidate(captured: ScheduleRevisionCapture) {
    if (captured.userGeneration === userGeneration) invalidateHistory(captured.date, "unknown")
    if (isCurrent(captured)) { revision.value = null; phase.value = "synchronizing" }
  }
  async function reconcile(captured: ScheduleRevisionCapture, only?: string[]): Promise<boolean> {
    if (!isCurrent(captured)) return false
    const success = await refreshSchedule(only, () => isCurrent(captured))
    if (!isCurrent(captured)) return false
    if (success) ingestProps()
    return success && revision.value !== null && getSchedule()?.date === captured.date
  }
  const state: ScheduleRevisionState = {
    revision: readonly(revision), schedule: readonly(schedule), blocks: shallowReadonly(blocks),
    phase: readonly(phase), busy: readonly(busy), synchronizing: readonly(synchronizing),
    capture, isCurrent, accept, invalidate, reset,
    begin(requestDate, expectedRevision, only) {
      const captured = capture(requestDate)
      if (!captured) return null
      if (expectedRevision !== undefined && expectedRevision !== captured.revision) {
        invalidateHistory(requestDate, "conflict")
        return null
      }
      activeCapture = captured
      let release!: () => void
      const done = new Promise<void>((resolve) => { release = resolve })
      pendingWrites.set(captured, { done, release })
      if (captured.userId !== undefined && coordinator) writeTickets.set(captured, coordinator.track(captured.userId, captured.date, only))
      phase.value = "saving"
      return captured
    },
    async settle(captured, result, mutationOptions = {}) {
      const settlement = result.ok ? "accepted" : result.code === "session_invalid" || result.status === 401
        ? "rejected" : isScheduleRevisionConflict(result) || result.status === undefined || result.status >= 500 || result.status < 300
          ? "uncertain" : "rejected"
      const settledRevision = validRevision(result.data?.revision) ? result.data.revision : undefined
      let authoritativeReload = false
      try {
        // A departed day's unknown result must invalidate its history, even
        // though it must never update the new page or start a reload there.
        if (result.code === "session_invalid" || result.status === 401) {
          if (isCurrent(captured)) reset("session")
          return { ...result, mutation: undefined }
        }
        const unknown = !result.ok && (result.status === undefined || result.status >= 500 || result.status < 300)
        const conflict = isScheduleRevisionConflict(result)
        if ((unknown || conflict) && captured.userGeneration === userGeneration) invalidateHistory(captured.date, conflict ? "conflict" : "unknown")
        if (!isCurrent(captured)) {
          if (result.ok && captured.userGeneration === userGeneration) invalidateHistory(captured.date, "departed")
          return { ...result, mutation: undefined }
        }
        const accepted = result.ok && accept(captured, result.data)
        const acceptedRevision = revision.value
        const acceptedBlocks = cloneBlocks(blocks.value)
        const fallback = result.ok && !accepted
        if (fallback || unknown || conflict) {
          invalidateHistory(captured.date, fallback ? "unknown" : conflict ? "conflict" : "unknown")
          revision.value = null
          phase.value = conflict ? "conflict" : "synchronizing"
          const reconciled = await reconcile(captured, mutationOptions.only)
          authoritativeReload = reconciled
          if (isCurrent(captured)) {
            activeCapture = null
            phase.value = reconciled ? "idle" : conflict ? "conflict" : "synchronizing"
          }
          // A confirmed successful write remains successful after a failed
          // reload. Without a complete accepted snapshot it cannot create undo.
          return fallback ? { ...result, code: reconciled ? "schedule_reconciled" : "schedule_sync_failed",
            synchronizationError: reconciled ? undefined : "Saved, but the schedule could not be refreshed. Refresh before making another change.", mutation: undefined } : result
        }
        if (accepted && mutationOptions.only) {
          phase.value = "synchronizing"
          const reconciled = await reconcile(captured, mutationOptions.only)
          authoritativeReload = reconciled
          if (!reconciled) result = { ...result, code: "schedule_sync_failed", synchronizationError: "Saved, but the review could not be refreshed." }
        }
        if (!isCurrent(captured)) return { ...result, mutation: undefined }
        activeCapture = null
        phase.value = "idle"
        if (!accepted || revision.value !== acceptedRevision || !sameBlocks(acceptedBlocks, blocks.value)) return { ...result, mutation: undefined }
        return { ...result, mutation: {
          previousBlocks: cloneBlocks(captured.previousBlocks), previousRevision: captured.revision,
          expectedRevision: revision.value!, changed: !sameBlocks(captured.previousBlocks, blocks.value),
          date: captured.date, generation: captured.generation,
        } }
      } finally {
        const ticket = writeTickets.get(captured)
        writeTickets.delete(captured)
        ticket?.settle(settlement, settledRevision)
        if (ticket && captured.userId !== undefined && isCurrent(captured)
          && revision.value !== null && (settlement === "accepted" || authoritativeReload)) {
          coordinator?.acknowledge(captured.userId, captured.date, revision.value, authoritativeReload)
        }
        const pending = pendingWrites.get(captured)
        pendingWrites.delete(captured)
        pending?.release()
      }
    },
    subscribeInvalidation(listener) { invalidationListeners.add(listener); return () => invalidationListeners.delete(listener) },
    subscribeScopeReset(listener) { scopeListeners.add(listener); return () => scopeListeners.delete(listener) },
  }
  return state
}
export function provideScheduleRevision(date: DateSource, getSchedule: () => Schedule, options?: ScheduleRevisionOptions): ScheduleRevisionState {
  const coordinator = useScheduleWriteCoordinator()
  const state = createScheduleRevision(date, getSchedule, { ...options, coordinator })
  provide(ScheduleRevisionKey, state)
  onUnmounted(() => state.reset("dispose"))
  return state
}
export function useScheduleRevision(explicit?: ScheduleRevisionState): ScheduleRevisionState | undefined {
  return explicit ?? (getCurrentInstance() ? inject(ScheduleRevisionKey, undefined) : undefined)
}
export function scheduleRevisionFailure(): ApiResult {
  return { ok: false, status: 409, code: "schedule_changed", errors: { detail: SCHEDULE_CHANGED_MESSAGE } }
}
export function scheduleCaptureFailure(state?: ScheduleRevisionState, only?: string[]): ApiResult {
  if (state?.busy.value) {
    return { ok: false, status: 409, code: "schedule_synchronizing", errors: { detail: "Schedule is updating. Wait for it to finish, then try again." } }
  }
  void refreshSchedule(only)
  return scheduleRevisionFailure()
}
export async function runScheduleMutation(
  state: ScheduleRevisionState | undefined, date: string,
  send: (capture: ScheduleRevisionCapture) => Promise<ApiResult>, options: ScheduleMutationOptions = {},
): Promise<ApiResult> {
  const captured = state?.begin(date, options.expectedRevision, options.only)
  if (!captured) {
    // A historical restore mismatch is a real conflict, with the same
    // exclusive reconciliation lifecycle as a server rejection.
    const fresh = options.expectedRevision !== undefined ? state?.begin(date, undefined, options.only) : null
    if (fresh) return state!.settle(fresh, scheduleRevisionFailure(), options)
    return scheduleCaptureFailure(state, options.only)
  }
  try { return await state!.settle(captured, await send(captured), options) }
  catch (error) {
    // Aborting a client fetch is an unknown server outcome, so keep the
    // writer lease until reconciliation has completed before propagating it.
    await state!.settle(captured, { ok: false, errors: { detail: "The write result is unknown." } }, options)
    throw error
  }
}
export function refreshSchedule(only: string[] = ["blocks", "schedule"], isCurrent: () => boolean = () => true): Promise<boolean> {
  return new Promise((resolve) => {
    if (!isCurrent()) { resolve(false); return }
    let succeeded = false
    try {
      router.reload({ only: [...new Set(["blocks", "schedule", ...only, "auth_user_id", "schedule_window"])],
        onSuccess: () => { succeeded = isCurrent() },
        onError: () => { resolve(false) }, onCancel: () => { resolve(false) },
        onFinish: () => { resolve(succeeded && isCurrent()) },
      })
    } catch { resolve(false) }
  })
}
export function isScheduleRevisionConflict(result: ApiResult): boolean {
  return result.status === 409 && (result.code === "schedule_changed" || result.errors?.detail === "schedule_changed")
}
