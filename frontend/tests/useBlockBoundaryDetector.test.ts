// Shared crossed-since-last-sample detector (feature 0028). These are the
// detector cases relocated from useSoundNotifications.test.ts (issue #56 /
// docs/features/0019_PLAN.md Phase 5), re-asserted against a spy `onBoundary`
// mock instead of the oscillator count. Drives the detector with plain refs —
// the crossed-since-last-sample logic is the unit under test, not the
// useNowMinutes sampler. All minute values are minutes-since-midnight, e.g.
// "09:30" === 570.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { defineComponent, nextTick, ref } from "vue"
import type { Ref } from "vue"
import { mount, type VueWrapper } from "@vue/test-utils"
import type { TimeBlock } from "../src/types"
import {
  useBlockBoundaryDetector,
  type BoundaryEvent,
} from "../src/composables/useBlockBoundaryDetector"

function block(id: number, start: string, end: string): TimeBlock {
  return {
    id,
    title: `block-${id}`,
    start_time: start,
    end_time: end,
    category: "work",
    is_completed: false,
    sort_order: id,
  }
}

function mountDetector(opts: {
  enabled: boolean
  blocks: TimeBlock[]
  nowDate?: string | null
  nowMinutes?: number | null
}): {
  wrapper: VueWrapper
  blocks: Ref<TimeBlock[]>
  nowMinutes: Ref<number | null>
  nowDate: Ref<string | null>
  enabled: Ref<boolean>
  onBoundary: ReturnType<typeof vi.fn>
} {
  const blocks = ref<TimeBlock[]>(opts.blocks)
  const nowMinutes = ref<number | null>(opts.nowMinutes ?? null)
  const hasNowDate = Object.prototype.hasOwnProperty.call(opts, "nowDate")
  const nowDate = ref<string | null>(hasNowDate ? opts.nowDate! : "2026-06-15")
  const enabled = ref<boolean>(opts.enabled)
  const onBoundary = vi.fn<(e: BoundaryEvent) => void>()
  const Harness = defineComponent({
    setup() {
      useBlockBoundaryDetector(nowMinutes, nowDate, () => blocks.value, {
        enabled,
        onBoundary,
      })
      return {}
    },
    template: "<div />",
  })
  return { wrapper: mount(Harness), blocks, nowMinutes, nowDate, enabled, onBoundary }
}

async function tick(nowMinutes: Ref<number | null>, m: number | null) {
  nowMinutes.value = m
  await nextTick()
}

beforeEach(() => {
  // No global stubs needed — the detector is pure ref arithmetic.
})

afterEach(() => {
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

describe("useBlockBoundaryDetector", () => {
  it("1. disabled: no callback at a block's start minute", async () => {
    const { wrapper, nowMinutes, onBoundary } = mountDetector({
      enabled: false,
      blocks: [block(1, "09:30", "10:00")], // start 570
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570)
    expect(onBoundary).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("2. start boundary fires with the full event payload", async () => {
    const { wrapper, nowMinutes, onBoundary } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570
    })
    await tick(nowMinutes, 569) // prime (first tick, exact-only, no fire)
    await tick(nowMinutes, 570) // window (569, 570] — start fires
    expect(onBoundary).toHaveBeenCalledTimes(1)
    const event = onBoundary.mock.calls[0][0] as BoundaryEvent
    expect(event).toMatchObject({
      type: "start",
      date: "2026-06-15",
      boundaryMinutes: 570,
    })
    expect(event.block.id).toBe(1)
    wrapper.unmount()
  })

  it("3. end boundary fires with type=end and its own minute", async () => {
    const { wrapper, nowMinutes, onBoundary } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // end 600
    })
    await tick(nowMinutes, 599)
    await tick(nowMinutes, 600) // end fires
    expect(onBoundary).toHaveBeenCalledTimes(1)
    expect(onBoundary.mock.calls[0][0]).toMatchObject({
      type: "end",
      boundaryMinutes: 600,
    })
    wrapper.unmount()
  })

  it("4. no double-fire for the same boundary on re-entry", async () => {
    const { wrapper, nowMinutes, onBoundary } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570) // fires once
    await tick(nowMinutes, 569) // backward step — no fire, lastSeen=569
    await tick(nowMinutes, 570) // 570 back in window but fired-Set blocks
    expect(onBoundary).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it("5. two blocks sharing a start minute both fire", async () => {
    const { wrapper, nowMinutes, onBoundary } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00"), block(2, "09:30", "11:00")], // both start 570
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570)
    expect(onBoundary).toHaveBeenCalledTimes(2) // independent fired keys
    wrapper.unmount()
  })

  it("6. a block added without remount is picked up", async () => {
    const { wrapper, blocks, nowMinutes, onBoundary } = mountDetector({
      enabled: true,
      blocks: [block(1, "08:00", "09:00")], // start 480 / end 540
    })
    await tick(nowMinutes, 660) // first tick, exact 660 — nothing fires
    blocks.value.push(block(2, "11:01", "12:00")) // start 661
    await tick(nowMinutes, 661) // window (660,661] — new block fires
    expect(onBoundary).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })

  it("7. coalesced multi-minute jump fires every boundary it leapt over", async () => {
    const { wrapper, nowMinutes, onBoundary } = mountDetector({
      enabled: true,
      blocks: [
        block(1, "09:31", "23:00"), // start 571 (in window), end 1380 (out)
        block(2, "09:28", "09:32"), // start 568 (<= prev, out), end 572 (in window)
      ],
    })
    await tick(nowMinutes, 569) // prime
    await tick(nowMinutes, 573) // throttled jump skipping 570/571/572
    // start@571 and end@572 fire; start@568 (before prev) and end@1380 do not.
    expect(onBoundary).toHaveBeenCalledTimes(2)
    wrapper.unmount()
  })

  it("8. first tick of a date does not back-fill earlier boundaries", async () => {
    const { wrapper, nowMinutes, onBoundary } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:00", "10:00")], // start 540 / end 600
    })
    await tick(nowMinutes, 840) // 14:00 — first tick, exact-840 only
    expect(onBoundary).not.toHaveBeenCalled() // morning boundaries not replayed
    wrapper.unmount()
  })

  it("9. fired-Set + lastSeenMinute reset on date navigation", async () => {
    const { wrapper, nowMinutes, nowDate, onBoundary } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570
      nowDate: "2026-06-15",
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570) // fires on date A
    expect(onBoundary).toHaveBeenCalledTimes(1)

    // Simulate navigation: off-today, then into a new today.
    await tick(nowMinutes, null)
    nowDate.value = null
    await nextTick()
    nowDate.value = "2026-06-16"
    await nextTick()

    await tick(nowMinutes, 570) // treated as first tick of date B — fires again
    expect(onBoundary).toHaveBeenCalledTimes(2)
    expect(onBoundary.mock.calls[1][0]).toMatchObject({ date: "2026-06-16" })
    wrapper.unmount()
  })

  it("10. off-today (nowDate null) never fires", async () => {
    const { wrapper, nowMinutes, onBoundary } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570
      nowDate: null,
    })
    await tick(nowMinutes, 570) // would-be boundary, but off-today
    expect(onBoundary).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("11. backward clock step fires nothing (no stale burst)", async () => {
    const { wrapper, nowMinutes, onBoundary } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:55", "10:05")], // start 595 / end 605
    })
    await tick(nowMinutes, 600) // first tick, exact 600 — no fire
    await tick(nowMinutes, 595) // clock moved back — no fire even though now===595
    expect(onBoundary).not.toHaveBeenCalled()
    wrapper.unmount()
  })

  it("12. a re-timed boundary fires again with the NEW minute", async () => {
    const { wrapper, blocks, nowMinutes, onBoundary } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570) // original start fires (key start:1:date:570)
    expect(onBoundary).toHaveBeenCalledTimes(1)

    // User edits block 1 to start 09:45 — re-flow with the SAME id, new time.
    blocks.value = [block(1, "09:45", "10:00")] // start 585
    await tick(nowMinutes, 584)
    await tick(nowMinutes, 585) // new start (key start:1:date:585) — not suppressed
    expect(onBoundary).toHaveBeenCalledTimes(2)
    expect(onBoundary.mock.calls[1][0]).toMatchObject({ boundaryMinutes: 585 })
    wrapper.unmount()
  })

  it("13. re-enabling after a disabled gap does not back-fire skipped boundaries", async () => {
    const { wrapper, nowMinutes, enabled, onBoundary } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570 / end 600
    })
    await tick(nowMinutes, 560) // first tick, exact — no boundary, lastSeen=560
    enabled.value = false
    await nextTick()
    await tick(nowMinutes, 565) // disabled gate: no fire AND lastSeen not advanced
    enabled.value = true // watch(enabled) resets lastSeenMinute → fresh first tick
    await nextTick()
    // Without the reset, prev would be 560 and the window (560, 601] would
    // back-fire start@570 and end@600. With it, this is a first tick → exact-
    // 601 only → nothing fires.
    await tick(nowMinutes, 601)
    expect(onBoundary).not.toHaveBeenCalled()
    wrapper.unmount()
  })
})
