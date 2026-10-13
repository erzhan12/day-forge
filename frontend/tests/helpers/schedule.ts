import { ScheduleUndoKey, ScheduleDragKey, ScheduleContainerKey } from "../../src/composables/scheduleContext"
import { ref } from "vue"
import { vi } from "vitest"
import { createScheduleRevision } from "../../src/composables/useScheduleRevision"
import { readDate, type DateSource } from "../../src/utils/dateSource"
import type { UserCategory } from "../../src/types"

export function makeCategories(): UserCategory[] {
  return [
    { id: 1, slug: "work", label: "Work", color_id: "blue", sort_order: 0, is_sink: false, is_new_block_default: true },
    { id: 2, slug: "personal", label: "Personal", color_id: "violet", sort_order: 1, is_sink: false, is_new_block_default: false },
    { id: 3, slug: "health", label: "Health", color_id: "emerald", sort_order: 2, is_sink: false, is_new_block_default: false },
    { id: 4, slug: "other", label: "Other", color_id: "gray", sort_order: 3, is_sink: true, is_new_block_default: false },
  ]
}

// Supply the page context when mounting a real block outside Schedule.vue.
export function makeScheduleProvides() {
  return {
    [ScheduleUndoKey]: { pushUndo: vi.fn(), snapshotBlocks: vi.fn(() => []) },
    [ScheduleDragKey]: {
      startDrag: vi.fn(),
      isDragging: ref(false),
      dragBlockId: ref<number | null>(null),
      shiftedBlockIds: ref(new Set<number>()),
    },
    [ScheduleContainerKey]: ref<HTMLElement | null>(null),
  }
}

export function makeRevisionState(date: DateSource, revision = 0) {
  return createScheduleRevision(date, () => ({ id: 1, date: readDate(date), status: "active" as const, revision }), { getBlocks: () => [] })
}

export function revisionEnvelope(date: string, revision = 1) {
  return { blocks: [], revision, schedule: { id: 1, date, status: "active", revision } }
}
