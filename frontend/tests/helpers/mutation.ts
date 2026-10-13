import type { TimeBlock } from "../../src/types"

export function acceptedMutation(previousBlocks: TimeBlock[] = [], date = "2026-04-10", previousRevision = 3, changed = true) {
  return {
    ok: true as const,
    mutation: {
      previousBlocks: previousBlocks.map((block) => ({ ...block })),
      date,
      previousRevision,
      expectedRevision: previousRevision + (changed ? 1 : 0),
      changed,
      generation: 0,
    },
  }
}
