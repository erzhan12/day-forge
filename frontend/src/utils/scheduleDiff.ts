import type { TimeBlock } from "../types"

// Comparison key: the combination that uniquely determines whether a block
// is "the same" from the user's perspective. ``id`` is included so a
// remove + re-add at the same time/title still counts as a change.
const blockKey = (b: TimeBlock): string =>
  `${b.id}|${b.title}|${b.start_time}|${b.end_time}|${b.category}|${b.is_completed}|${b.sort_order}`

/**
 * Returns true when the AI response touched the schedule in any visible way.
 *
 * Used to gate undo-stack pushes: a 200 with ``actions: []`` should not
 * register an undo entry, even though the AI considered the request a
 * success (e.g. clarifying-question turn or chit-chat reply).
 */
export function scheduleChanged(
  snapshot: TimeBlock[],
  responseBlocks: unknown,
): boolean {
  if (!Array.isArray(responseBlocks)) return false
  const before = new Set(snapshot.map(blockKey))
  const after = new Set(
    (responseBlocks as TimeBlock[]).map((b) => blockKey(b)),
  )
  if (before.size !== after.size) return true
  for (const k of before) if (!after.has(k)) return true
  return false
}
