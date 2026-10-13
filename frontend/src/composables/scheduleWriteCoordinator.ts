import { inject, provide, watch, type InjectionKey } from "vue"
import { usePage } from "@inertiajs/vue3"

type Settlement = "accepted" | "uncertain" | "rejected"
interface WriteRecord {
  pending: Set<Promise<void>>
  floor: number
  dirty: boolean
  only: Set<string>
}
export interface ScheduleWriteCoordinator {
  track: (userId: number, date: string, only?: string[]) => { done: Promise<void>; settle: (outcome: Settlement, revision?: number) => void }
  inspect: (userId: number, date: string) => { pending: Promise<void>[]; floor: number; dirty: boolean; only: string[] }
  acknowledge: (userId: number, date: string, revision: number, authoritative: boolean) => void
  clear: () => void
}
export const ScheduleWriteCoordinatorKey: InjectionKey<ScheduleWriteCoordinator> = Symbol("scheduleWriteCoordinator")

export function createScheduleWriteCoordinator(): ScheduleWriteCoordinator {
  const records = new Map<string, WriteRecord>()
  let epoch = 0
  const key = (userId: number, date: string) => `${userId}:${date}`
  const get = (userId: number, date: string) => {
    const recordKey = key(userId, date)
    let record = records.get(recordKey)
    if (!record) {
      record = { pending: new Set(), floor: -1, dirty: false, only: new Set() }
      records.set(recordKey, record)
    }
    return record
  }
  return {
    track(userId, date, only) {
      const record = get(userId, date)
      only?.forEach((field) => record.only.add(field))
      const capturedEpoch = epoch
      let release!: () => void
      const done = new Promise<void>((resolve) => { release = resolve })
      record.pending.add(done)
      return { done, settle(outcome, revision) {
        if (capturedEpoch === epoch) {
          record.pending.delete(done)
          if (outcome === "uncertain") record.dirty = true
          if (outcome === "accepted") {
            if (revision === undefined) record.dirty = true
            else record.floor = Math.max(record.floor, revision)
          }
        }
        release()
      } }
    },
    inspect(userId, date) {
      const record = records.get(key(userId, date))
      return { pending: [...(record?.pending ?? [])], floor: record?.floor ?? -1,
        dirty: record?.dirty ?? false, only: [...(record?.only ?? [])] }
    },
    acknowledge(userId, date, revision, authoritative) {
      const recordKey = key(userId, date)
      const record = records.get(recordKey)
      if (!record || record.pending.size || revision < record.floor || (record.dirty && !authoritative)) return
      record.dirty = false
    },
    clear() { epoch += 1; records.clear() },
  }
}

export function provideScheduleWriteCoordinator() {
  const coordinator = createScheduleWriteCoordinator()
  const page = usePage()
  provide(ScheduleWriteCoordinatorKey, coordinator)
  watch(() => [page?.component, page?.props?.auth_user_id] as const, ([component, userId], previous) => {
    const priorUserId = previous?.[1]
    if (component === "Login" || userId === null
      || (priorUserId !== undefined && userId !== undefined && userId !== priorUserId)) coordinator.clear()
  }, { flush: "sync" })
  return coordinator
}

export function useScheduleWriteCoordinator() { return inject(ScheduleWriteCoordinatorKey, undefined) }
