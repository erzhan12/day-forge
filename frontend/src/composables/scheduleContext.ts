import type { InjectionKey, Ref } from "vue"
import type { UndoAction } from "../types"
import type { useDrag } from "./useDrag"

export interface ScheduleUndoContext {
  pushUndo: (action: UndoAction) => void
}

export type ScheduleDragContext = Pick<ReturnType<typeof useDrag>,
  "startDrag" | "isDragging" | "dragBlockId" | "shiftedBlockIds">

export const ScheduleDisabledKey: InjectionKey<Readonly<Ref<boolean>>> = Symbol("scheduleDisabled")
export const ScheduleUndoKey: InjectionKey<ScheduleUndoContext> = Symbol("scheduleUndo")
export const ScheduleDragKey: InjectionKey<ScheduleDragContext> = Symbol("scheduleDrag")
export const ScheduleContainerKey: InjectionKey<Ref<HTMLElement | null>> = Symbol("scheduleContainer")
