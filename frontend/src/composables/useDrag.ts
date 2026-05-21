import { ref } from "vue"
import type { TimeBlock, UndoAction } from "../types"
import type { ApiResult } from "./useSchedule"
import { type DateSource, readDate } from "../utils/dateSource"
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
 *      non-dragged neighbour *forward* past the dragged block (preserving
 *      the neighbour's duration). Shifts always go forward — the dragged
 *      block is pinned, so even a non-dragged neighbour sitting *before*
 *      the dragged block gets moved forward past it rather than backward.
 *      See the "anchors dragged block when dropped onto an earlier block"
 *      test for the canonical example. After any shift the scan restarts
 *      to let changes cascade through additional neighbours.
 *   4. Reassign `sort_order = index * 10` so the result is deterministic.
 *
 * @param blocks            Current block list (not mutated).
 * @param draggedId         `id` of the block being moved.
 * @param newStartMinutes   Drop position in minutes since midnight.
 * @param newEndMinutes     Drop end in minutes since midnight (preserves
 *                          original duration).
 * @returns The resolved block list, or `null` if the cascade pushes any
 *          block past `DAY_END_MINUTES` (e.g. dragging a block onto the last
 *          slot leaves no room for the trailing neighbours to shift forward),
 *          or if the defensive iteration cap is exceeded (should never
 *          happen for valid input — see safety guard below).
 *
 * Complexity:
 *   Worst-case `O(n² log n)`: each shift requires an `O(n log n)` re-sort
 *   so the pairwise scan stays in O(n), and the cascade can require up to
 *   `O(n)` shifts. In practice `n ≤ ~30` (the backend caps reorder payloads
 *   at 100 blocks) so the constant factor is small and the scan runs in
 *   well under a millisecond on modern hardware. A defensive iteration
 *   guard inside the loop aborts with `null` if the shift count ever grows
 *   unreasonably — this should never trigger for valid input but prevents
 *   a future bug from freezing the browser.
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
  //
  // INVARIANT: the dragged block stays pinned at the drop position for the
  // entire loop. Only its neighbours move. We identify the dragged block by
  // `id` in every iteration, not by index, so the re-sort below is free to
  // relocate it within the array without breaking the algorithm.
  //
  // The re-sort after each shift exists only to keep `result` ordered by
  // start_time so the pairwise `currEnd > nextStart` scan can detect the
  // next collision in O(n). It is NOT used to find the dragged block.
  //
  // Safety: termination is already proven — each shift strictly advances a
  // block's `start_time` and the `newEnd > DAY_END_MINUTES` check bounds
  // the total motion. The `MAX_ITERATIONS` guard below is a belt-and-braces
  // check against a *future* bug introducing an infinite loop, and fails
  // fast so a broken algorithm can't freeze the UI.
  //
  // Sizing: in practice the cascade is O(n) — each affected block shifts at
  // most a handful of times before settling. With the backend's 100-block
  // payload cap, that's ≤ ~100 realistic iterations, so 1000 is a 10×
  // safety margin. If we ever hit it, returning null is a soft failure
  // (drop marked invalid, user retries) rather than a crash.
  let changed = true
  let iterations = 0
  const MAX_ITERATIONS = 1000
  while (changed) {
    if (++iterations > MAX_ITERATIONS) {
      console.error(
        "resolveConflicts: max iterations exceeded — possible infinite loop",
      )
      return null
    }
    changed = false
    for (let i = 0; i < result.length - 1; i++) {
      const currEnd = timeToMinutes(result[i].end_time)
      const nextStart = timeToMinutes(result[i + 1].start_time)
      if (currEnd > nextStart) {
        // Pick the neighbour to move — the dragged block is anchored, so if
        // it's the later one (i+1) we shift the earlier non-dragged block at
        // i forward past it; otherwise we shift i+1 forward past i.
        const shiftIdx =
          result[i + 1].id === draggedId ? i : i + 1
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
        // Re-sort: the shift above moved a block's start_time, which may
        // have changed its position in the ordered list. The top-of-loop
        // scan walks pairs by index and relies on the array being ordered
        // by start_time, so we re-sort before restarting to keep the
        // `currEnd > nextStart` invariant valid. See the top-level comment
        // above the loop for the full rationale.
        //
        // Perf note: this re-sort makes the loop O(n² log n) worst case
        // (up to n shifts × O(n log n) sort). For the backend's 100-block
        // reorder cap the constant is negligible (single-digit ms on
        // modern hardware — see the "resolves a 30-block full-day cascade"
        // test in useDrag.test.ts). A batched variant that collected all
        // shifts in a pass before sorting once would be O(n² + n log n);
        // worth the change only if we ever raise the 100-block cap.
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
  date: DateSource,
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
  isDisabled?: () => boolean,
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
  let snapshotDate = ""
  let originalBlock: TimeBlock | null = null
  let containerEl: HTMLElement | null = null
  let containerRect: DOMRect | null = null
  let containerPaddingTop = 0
  let blockDuration = 0
  let grabOffsetY = 0
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

    // Recalculate container rect to account for page scroll. Subtract
    // paddingTop so relativeY is measured from where blocks actually
    // render (not the outer edge of the container). Subtract
    // grabOffsetY so the cursor stays at the same spot within the
    // block the user grabbed, instead of the block jumping so its
    // top snaps to the cursor.
    containerRect = containerEl.getBoundingClientRect()
    const cursorY =
      e.clientY - containerRect.top - containerPaddingTop + containerEl.scrollTop
    const blockTopPx = cursorY - grabOffsetY
    const minuteOffset = blockTopPx / PX_PER_MINUTE
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
    ghostTop.value =
      containerPaddingTop + (newStart - DAY_START_MINUTES) * PX_PER_MINUTE

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
    // Suppress drag while a draft is generating (or any other parent
    // disable signal). Without this, the disable on TimeBlock /
    // GapSlot would be decorative — drag bypasses click-based mutation.
    if (isDisabled && isDisabled()) return
    snapshot = snapshotBlocks()
    snapshotDate = readDate(date)
    originalBlock = block
    containerEl = container
    containerRect = container.getBoundingClientRect()
    containerPaddingTop =
      parseFloat(getComputedStyle(container).paddingTop) || 0
    blockDuration =
      timeToMinutes(block.end_time) - timeToMinutes(block.start_time)
    dropValid = true
    pointerId = event.pointerId

    const startMinutes = timeToMinutes(block.start_time)
    // Offset between cursor and block top at grab time, in px
    // relative to the schedule-body content area. Reused in
    // updatePreview so the ghost follows the cursor from the same
    // relative position (cursor doesn't teleport to block top).
    const blockTopPx = (startMinutes - DAY_START_MINUTES) * PX_PER_MINUTE
    const cursorY =
      event.clientY - containerRect.top - containerPaddingTop + container.scrollTop
    grabOffsetY = cursorY - blockTopPx

    previewStartTime.value = block.start_time
    previewEndTime.value = block.end_time
    ghostTop.value = containerPaddingTop + blockTopPx
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

    // Snapshot module-scoped drag state into local constants BEFORE
    // resetState() so the in-flight undo action stays correctly bound to
    // *this* drag's pre-drag blocks. Two reasons:
    //
    //   1. resetState() clears `snapshot` to []. Without the local
    //      capture, the `pushUndo({ previousBlocks: snapshot })` below
    //      would always push an empty array, and undoing a drag would
    //      then restore the day with zero blocks (i.e. delete everything).
    //   2. Even if (1) were fixed by reading `snapshot` before reset,
    //      the await on `reorderBlocks` opens a window in which a
    //      second `startDrag()` can overwrite the module-scoped snapshot
    //      before this drag's `pushUndo` runs — so the first drag's
    //      undo would get the second drag's snapshot.
    //   3. `cleanup()` above has already released the pointer, so the
    //      user can navigate dates during `await reorderBlocks` — the
    //      undo's `scheduleDate` must stay bound to the day the drag
    //      actually mutated, not the day the user has navigated to.
    const savedSnapshot = snapshot
    const savedScheduleDate = snapshotDate
    const title = originalBlock.title
    const targetTime = previewStartTime.value

    // Build updates array for blocks that changed
    const originalMap = new Map(
      savedSnapshot.map((b) => [b.id, b]),
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

    resetState()

    if (updates.length === 0) return

    const result = await reorderBlocks(updates)
    if (result.ok) {
      pushUndo({
        description: `Moved "${title}" to ${targetTime}`,
        type: "drag",
        previousBlocks: savedSnapshot,
        scheduleDate: savedScheduleDate,
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
      } catch (e) {
        // Pointer capture may already be released (e.g. element detached
        // mid-drag, or browser auto-released on pointerup). Expected
        // failure modes are silent: `InvalidPointerId` (older Chrome /
        // spec name) and `NotFoundError` (current spec / MDN). Surface
        // anything else so real bugs aren't swallowed.
        const expected =
          e instanceof DOMException &&
          (e.name === "InvalidPointerId" || e.name === "NotFoundError")
        if (!expected) {
          console.warn("useDrag: failed to release pointer capture:", e)
        }
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
    containerPaddingTop = 0
    grabOffsetY = 0
    snapshot = []
    snapshotDate = ""
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
