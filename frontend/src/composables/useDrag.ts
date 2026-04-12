import { ref } from "vue"
import type { TimeBlock, UndoAction } from "../types"
import type { ApiResult } from "./useSchedule"
import {
  DAY_START_MINUTES,
  DAY_END_MINUTES,
  PX_PER_MINUTE,
  SNAP_MINUTES,
  timeToMinutes,
  minutesToTime,
} from "../utils/scheduleTime"

/**
 * Resolve overlap conflicts after moving a block to a new time slot.
 *
 * Algorithm:
 *   1. Deep-clone every block. The dragged block is anchored at the requested
 *      `[newStartMinutes, newEndMinutes)` slot and never shifts again.
 *   2. Sort by `(start_time, sort_order)`.
 *   3. Walk neighbours pairwise. When two blocks overlap, shift the
 *      non-dragged neighbour (forward if it sits after the dragged block,
 *      backward into the open space if it sits before). Each shift preserves
 *      the neighbour's duration. After any shift the scan restarts to let
 *      changes cascade through additional neighbours.
 *   4. Reassign `sort_order = index * 10` so the result is deterministic.
 *
 * @param blocks            Current block list (not mutated).
 * @param draggedId         `id` of the block being moved.
 * @param newStartMinutes   Drop position in minutes since midnight.
 * @param newEndMinutes     Drop end in minutes since midnight (preserves
 *                          original duration).
 * @returns The resolved block list, or `null` if the cascade pushes any
 *          block past `DAY_END_MINUTES` (e.g. dragging a block onto the last
 *          slot leaves no room for the trailing neighbours to shift forward).
 *
 * @example
 *   // No-op when there's no overlap
 *   resolveConflicts(blocks, 1, 540, 600) // → blocks with #1 anchored at 09:00
 *
 * @example
 *   // Returns null: shifting the trailing block would push it past 23:00
 *   resolveConflicts([{id:1,...}, {id:2, end:23:00}], 1, 1370, 1380)
 */
export function resolveConflicts(
  blocks: TimeBlock[],
  draggedId: number,
  newStartMinutes: number,
  newEndMinutes: number,
): TimeBlock[] | null {
  // Deep clone blocks and apply the dragged block's new time
  const result: TimeBlock[] = blocks.map((b) => {
    const clone = { ...b }
    if (b.id === draggedId) {
      clone.start_time = minutesToTime(newStartMinutes)
      clone.end_time = minutesToTime(newEndMinutes)
    }
    return clone
  })

  // Sort by (start_time, sort_order)
  result.sort((a, b) => {
    const aStart = timeToMinutes(a.start_time)
    const bStart = timeToMinutes(b.start_time)
    if (aStart !== bStart) return aStart - bStart
    return a.sort_order - b.sort_order
  })

  // Walk forward and shift overlapping blocks.
  // The dragged block is anchored at the drop position and never shifts.
  // When the dragged block overlaps a neighbour, the neighbour moves instead.
  let changed = true
  while (changed) {
    changed = false
    for (let i = 0; i < result.length - 1; i++) {
      const currEnd = timeToMinutes(result[i].end_time)
      const nextStart = timeToMinutes(result[i + 1].start_time)
      if (currEnd > nextStart) {
        // Determine which block to shift — never shift the dragged block
        const shiftIdx =
          result[i + 1].id === draggedId ? i : i + 1
        // If the dragged block is the earlier one, it stays; shift i (earlier non-dragged) forward past the dragged block
        if (shiftIdx === i) {
          const shiftDuration =
            timeToMinutes(result[i].end_time) -
            timeToMinutes(result[i].start_time)
          const newStart = timeToMinutes(result[i + 1].end_time)
          const newEnd = newStart + shiftDuration
          if (newEnd > DAY_END_MINUTES) return null
          result[i].start_time = minutesToTime(newStart)
          result[i].end_time = minutesToTime(newEnd)
        } else {
          const shiftDuration =
            timeToMinutes(result[i + 1].end_time) - nextStart
          const newStart = currEnd
          const newEnd = newStart + shiftDuration
          if (newEnd > DAY_END_MINUTES) return null
          result[i + 1].start_time = minutesToTime(newStart)
          result[i + 1].end_time = minutesToTime(newEnd)
        }
        changed = true
        // Re-sort after shifting since positions changed
        result.sort((a, b) => {
          const aStart = timeToMinutes(a.start_time)
          const bStart = timeToMinutes(b.start_time)
          if (aStart !== bStart) return aStart - bStart
          return a.sort_order - b.sort_order
        })
        break // restart the scan from the beginning
      }
    }
  }

  // Reassign sort_order for deterministic ordering
  result.forEach((b, idx) => {
    b.sort_order = idx * 10
  })

  return result
}

export function useDrag(
  date: string,
  getCurrentBlocks: () => TimeBlock[],
  reorderBlocks: (
    updates: Array<{
      id: number
      start_time: string
      end_time: string
      sort_order: number
    }>,
  ) => Promise<ApiResult>,
  pushUndo: (action: UndoAction) => void,
  snapshotBlocks: () => TimeBlock[],
) {
  const isDragging = ref(false)
  const dragBlockId = ref<number | null>(null)
  const ghostTop = ref(0)
  const previewStartTime = ref("")
  const previewEndTime = ref("")
  const previewBlocks = ref<TimeBlock[]>([])
  const shiftedBlockIds = ref<Set<number>>(new Set())

  // Internal state (not reactive — used only during drag)
  let snapshot: TimeBlock[] = []
  let originalBlock: TimeBlock | null = null
  let containerEl: HTMLElement | null = null
  let containerRect: DOMRect | null = null
  let blockDuration = 0
  let dropValid = true
  let rafId = 0
  let pointerId = -1

  function onPointerMove(e: PointerEvent) {
    if (!isDragging.value || !containerEl) return
    cancelAnimationFrame(rafId)
    rafId = requestAnimationFrame(() => updatePreview(e))
  }

  function updatePreview(e: PointerEvent) {
    if (!containerEl || !originalBlock) return

    // Recalculate container rect to account for page scroll
    containerRect = containerEl.getBoundingClientRect()
    const relativeY = e.clientY - containerRect.top + containerEl.scrollTop
    const minuteOffset = relativeY / PX_PER_MINUTE
    const snapped =
      Math.round(minuteOffset / SNAP_MINUTES) * SNAP_MINUTES

    let newStart = DAY_START_MINUTES + snapped
    // Clamp to day window
    if (newStart < DAY_START_MINUTES) newStart = DAY_START_MINUTES
    if (newStart + blockDuration > DAY_END_MINUTES)
      newStart = DAY_END_MINUTES - blockDuration

    const newEnd = newStart + blockDuration

    previewStartTime.value = minutesToTime(newStart)
    previewEndTime.value = minutesToTime(newEnd)
    ghostTop.value = (newStart - DAY_START_MINUTES) * PX_PER_MINUTE

    // Resolve conflicts
    const resolved = resolveConflicts(
      getCurrentBlocks(),
      originalBlock.id,
      newStart,
      newEnd,
    )

    if (resolved === null) {
      dropValid = false
      shiftedBlockIds.value = new Set()
      previewBlocks.value = []
    } else {
      dropValid = true
      previewBlocks.value = resolved

      // Compute which blocks shifted
      const originalMap = new Map(
        getCurrentBlocks().map((b) => [b.id, b]),
      )
      const shifted = new Set<number>()
      for (const b of resolved) {
        const orig = originalMap.get(b.id)
        if (
          orig &&
          b.id !== originalBlock.id &&
          (b.start_time !== orig.start_time || b.end_time !== orig.end_time)
        ) {
          shifted.add(b.id)
        }
      }
      shiftedBlockIds.value = shifted
    }
  }

  function onPointerUp() {
    endDrag()
  }

  function onKeydown(e: KeyboardEvent) {
    if (e.key === "Escape") {
      cancelDrag()
    }
  }

  function startDrag(
    event: PointerEvent,
    block: TimeBlock,
    container: HTMLElement,
  ) {
    snapshot = snapshotBlocks()
    originalBlock = block
    containerEl = container
    containerRect = container.getBoundingClientRect()
    blockDuration =
      timeToMinutes(block.end_time) - timeToMinutes(block.start_time)
    dropValid = true
    pointerId = event.pointerId

    const startMinutes = timeToMinutes(block.start_time)
    previewStartTime.value = block.start_time
    previewEndTime.value = block.end_time
    ghostTop.value = (startMinutes - DAY_START_MINUTES) * PX_PER_MINUTE
    previewBlocks.value = []
    shiftedBlockIds.value = new Set()

    isDragging.value = true
    dragBlockId.value = block.id

    container.setPointerCapture(event.pointerId)
    container.addEventListener("pointermove", onPointerMove)
    container.addEventListener("pointerup", onPointerUp)
    document.addEventListener("keydown", onKeydown)
    document.body.classList.add("is-dragging")
  }

  async function endDrag() {
    if (!isDragging.value || !originalBlock) return
    cleanup()

    if (!dropValid || previewBlocks.value.length === 0) {
      resetState()
      return
    }

    // Build updates array for blocks that changed
    const originalMap = new Map(
      snapshot.map((b) => [b.id, b]),
    )
    const updates: Array<{
      id: number
      start_time: string
      end_time: string
      sort_order: number
    }> = []
    for (const b of previewBlocks.value) {
      const orig = originalMap.get(b.id)
      if (
        !orig ||
        b.start_time !== orig.start_time ||
        b.end_time !== orig.end_time ||
        b.sort_order !== orig.sort_order
      ) {
        updates.push({
          id: b.id,
          start_time: b.start_time,
          end_time: b.end_time,
          sort_order: b.sort_order,
        })
      }
    }

    const title = originalBlock.title
    const targetTime = previewStartTime.value

    resetState()

    if (updates.length === 0) return

    const result = await reorderBlocks(updates)
    if (result.ok) {
      pushUndo({
        description: `Moved "${title}" to ${targetTime}`,
        type: "drag",
        previousBlocks: snapshot,
        scheduleDate: date,
      })
    }
  }

  function cancelDrag() {
    cleanup()
    resetState()
  }

  function cleanup() {
    cancelAnimationFrame(rafId)
    if (containerEl) {
      try {
        containerEl.releasePointerCapture(pointerId)
      } catch {
        // Pointer capture may already be released (e.g. element detached
        // mid-drag, or browser auto-released on pointerup).
        console.debug("useDrag: pointer capture already released")
      }
      containerEl.removeEventListener("pointermove", onPointerMove)
      containerEl.removeEventListener("pointerup", onPointerUp)
    }
    document.removeEventListener("keydown", onKeydown)
    document.body.classList.remove("is-dragging")
  }

  function resetState() {
    isDragging.value = false
    dragBlockId.value = null
    ghostTop.value = 0
    previewStartTime.value = ""
    previewEndTime.value = ""
    previewBlocks.value = []
    shiftedBlockIds.value = new Set()
    originalBlock = null
    containerEl = null
    containerRect = null
    snapshot = []
    dropValid = true
  }

  return {
    isDragging,
    dragBlockId,
    ghostTop,
    previewStartTime,
    previewEndTime,
    previewBlocks,
    shiftedBlockIds,
    startDrag,
    endDrag,
    cancelDrag,
  }
}
