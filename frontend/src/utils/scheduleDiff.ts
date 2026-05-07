import type { TimeBlock } from "../types"

/**
 * Stable string key for set-based block diffing.
 *
 * Concatenates every user-visible field that the AI / drag / completion
 * paths can mutate: the DB `id` (so a remove + re-add of an identical
 * block still registers as a change), the textual `title`, the time
 * window (`start_time`, `end_time`), the `category` enum, the
 * `is_completed` flag, and `sort_order`. The pipe delimiter `|` is safe
 * because none of those fields can legitimately contain it — `category`
 * is a closed enum, times are `HH:MM`, ids/sort orders are integers,
 * `is_completed` is a boolean, and titles with embedded `|` are still
 * unambiguous because every field's position is fixed.
 */
const blockKey = (b: TimeBlock): string =>
  `${b.id}|${b.title}|${b.start_time}|${b.end_time}|${b.category}|${b.is_completed}|${b.sort_order}`

/**
 * Returns true when the AI response touched the schedule in any visible way.
 *
 * Used to gate undo-stack pushes: a 200 with ``actions: []`` should not
 * register an undo entry, even though the AI considered the request a
 * success (e.g. clarifying-question turn or chit-chat reply).
 *
 * @param snapshot - The block array as it stood before the AI request was
 *   sent (captured by `useUndo.snapshotBlocks` at submit time).
 * @param responseBlocks - Whatever the server returned in `data.blocks`.
 *   Typed as `unknown` because the chat response shape allows `null` /
 *   missing for non-applied turns; this function is the type guard.
 * @returns `true` if the set of blockKeys differs between snapshot and
 *   response — i.e. at least one block was added, removed, or mutated
 *   in a user-visible field. `false` if the response did not change
 *   the schedule (or `responseBlocks` is not an array).
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
