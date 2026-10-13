import type { UndoAction } from "../types"
import type { ApiResult } from "./useSchedule"

/** Register history only for a confirmed diff and its controller-owned snapshot. */
export function registerMutationUndo(
  result: ApiResult,
  pushUndo: ((action: UndoAction) => void) | undefined,
  action: Pick<UndoAction, "description" | "type" | "silent">,
): void {
  const mutation = result.mutation
  if (!result.ok || !mutation?.changed || !pushUndo) return
  pushUndo({
    ...action,
    previousBlocks: mutation.previousBlocks,
    scheduleDate: mutation.date,
    previous_revision: mutation.previousRevision,
    expected_revision: mutation.expectedRevision,
    generation: mutation.generation,
  })
}
