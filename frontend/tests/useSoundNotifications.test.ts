// Boundary-cross detector + setting helper for sound notifications
// (issue #56 / docs/features/0019_PLAN.md Phase 5). Drives the detector with
// plain refs (the crossed-since-last-sample logic is the unit under test —
// not the useNowMinutes sampler) and mocks the Web Audio + localStorage
// globals. All minute values are minutes-since-midnight, e.g.
// hhmmToMinutes("09:30") === 570.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { defineComponent, nextTick, ref } from "vue"
import type { Ref } from "vue"
import { mount, type VueWrapper } from "@vue/test-utils"
import type { TimeBlock } from "../src/types"
import { SOUND_NOTIFICATIONS_KEY } from "../src/utils/soundNotificationStorage"
import { closeAudioContext, getAudioContext } from "../src/utils/audioContext"
import {
  useSoundNotifications,
  useSoundNotificationSetting,
} from "../src/composables/useSoundNotifications"

// --- Web Audio mocks --------------------------------------------------------

let createdOscillators: MockOscillator[] = []
let resumeSpy: ReturnType<typeof vi.fn>
let closeSpy: ReturnType<typeof vi.fn>

class MockOscillator {
  frequency = { setValueAtTime: vi.fn() }
  connect = vi.fn()
  start = vi.fn()
  stop = vi.fn()
}

class MockGain {
  gain = {
    setValueAtTime: vi.fn(),
    linearRampToValueAtTime: vi.fn(),
    exponentialRampToValueAtTime: vi.fn(),
  }
  connect = vi.fn()
}

class MockAudioContext {
  state = "suspended"
  currentTime = 0
  destination = {}
  resume = (...args: unknown[]) => resumeSpy(...args)
  close = (...args: unknown[]) => closeSpy(...args)
  createOscillator = vi.fn(() => {
    const o = new MockOscillator()
    createdOscillators.push(o)
    return o
  })
  createGain = vi.fn(() => new MockGain())
}

// --- localStorage mock ------------------------------------------------------

type StorageMock = {
  store: Record<string, string>
  getItem: ReturnType<typeof vi.fn>
  setItem: ReturnType<typeof vi.fn>
  removeItem: ReturnType<typeof vi.fn>
  clear: ReturnType<typeof vi.fn>
  key: ReturnType<typeof vi.fn>
  length: number
}

function makeStorage(): StorageMock {
  const store: Record<string, string> = {}
  return {
    store,
    getItem: vi.fn((k: string) => (k in store ? store[k] : null)),
    setItem: vi.fn((k: string, v: string) => {
      store[k] = v
    }),
    removeItem: vi.fn((k: string) => {
      delete store[k]
    }),
    clear: vi.fn(() => {
      for (const k of Object.keys(store)) delete store[k]
    }),
    key: vi.fn((i: number) => Object.keys(store)[i] ?? null),
    length: 0,
  }
}

let storage: StorageMock

// --- helpers ----------------------------------------------------------------

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
  api: ReturnType<typeof useSoundNotifications>
} {
  if (opts.enabled) storage.store[SOUND_NOTIFICATIONS_KEY] = "true"
  const blocks = ref<TimeBlock[]>(opts.blocks)
  const nowMinutes = ref<number | null>(opts.nowMinutes ?? null)
  // `??` would turn an explicit `nowDate: null` into the default — use an
  // own-property check so test 10 can start off-today.
  const hasNowDate = Object.prototype.hasOwnProperty.call(opts, "nowDate")
  const nowDate = ref<string | null>(hasNowDate ? opts.nowDate! : "2026-06-15")
  let api!: ReturnType<typeof useSoundNotifications>
  const Harness = defineComponent({
    setup() {
      api = useSoundNotifications(nowMinutes, nowDate, () => blocks.value)
      return {}
    },
    template: "<div />",
  })
  return { wrapper: mount(Harness), blocks, nowMinutes, nowDate, api }
}

async function tick(nowMinutes: Ref<number | null>, m: number | null) {
  nowMinutes.value = m
  await nextTick()
}

function freqAt(osc: MockOscillator, call: number): number {
  return osc.frequency.setValueAtTime.mock.calls[call][0] as number
}

beforeEach(() => {
  createdOscillators = []
  resumeSpy = vi.fn(() => Promise.resolve())
  closeSpy = vi.fn(() => Promise.resolve())
  storage = makeStorage()
  vi.stubGlobal("localStorage", storage)
  vi.stubGlobal("AudioContext", MockAudioContext)
})

afterEach(() => {
  closeAudioContext() // reset the module-level singleton between tests
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

describe("useSoundNotifications — detector", () => {
  it("1. setting off: no sound at a block's start minute", async () => {
    const { wrapper, nowMinutes } = mountDetector({
      enabled: false,
      blocks: [block(1, "09:30", "10:00")], // start 570
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570)
    expect(createdOscillators.length).toBe(0)
    wrapper.unmount()
  })

  it("2. start boundary fires a rising chime", async () => {
    const { wrapper, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570
    })
    await tick(nowMinutes, 569) // prime (first tick, exact-only, no fire)
    await tick(nowMinutes, 570) // window (569, 570] — start fires
    expect(createdOscillators.length).toBe(1)
    const osc = createdOscillators[0]
    expect(freqAt(osc, 1)).toBeGreaterThan(freqAt(osc, 0)) // rising

    // Wiring contract (plan §Web Audio): osc → gain → destination, the
    // node is actually started/stopped, and a click-free gain envelope is
    // scheduled. Without this, a regression that built a correct oscillator
    // but never connected it to destination (silent output) would still pass.
    expect(osc.connect).toHaveBeenCalledTimes(1)
    const gainNode = osc.connect.mock.calls[0][0] as MockGain
    const ctx = getAudioContext()
    expect(gainNode.connect).toHaveBeenCalledWith(ctx!.destination)
    expect(osc.start).toHaveBeenCalledTimes(1)
    expect(osc.stop).toHaveBeenCalledTimes(1)
    expect(gainNode.gain.linearRampToValueAtTime).toHaveBeenCalled()
    expect(gainNode.gain.exponentialRampToValueAtTime).toHaveBeenCalled()
    wrapper.unmount()
  })

  it("3. end boundary fires a falling chime (distinct from start)", async () => {
    const { wrapper, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // end 600
    })
    await tick(nowMinutes, 599)
    await tick(nowMinutes, 600) // end fires
    expect(createdOscillators.length).toBe(1)
    const osc = createdOscillators[0]
    expect(freqAt(osc, 1)).toBeLessThan(freqAt(osc, 0)) // falling
    wrapper.unmount()
  })

  it("4. no double-fire for the same boundary on re-entry", async () => {
    const { wrapper, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570) // fires once
    await tick(nowMinutes, 569) // backward step — no fire, lastSeen=569
    await tick(nowMinutes, 570) // 570 back in window (569,570] but fired-Set blocks
    expect(createdOscillators.length).toBe(1)
    wrapper.unmount()
  })

  it("5. two blocks sharing a start minute both fire", async () => {
    const { wrapper, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00"), block(2, "09:30", "11:00")], // both start 570
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570)
    expect(createdOscillators.length).toBe(2) // independent fired keys
    wrapper.unmount()
  })

  it("6. a block added without remount is picked up", async () => {
    const { wrapper, blocks, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [block(1, "08:00", "09:00")], // start 480 / end 540
    })
    await tick(nowMinutes, 660) // first tick, exact 660 — nothing fires
    blocks.value.push(block(2, "11:01", "12:00")) // start 661
    await tick(nowMinutes, 661) // window (660,661] — new block fires
    expect(createdOscillators.length).toBe(1)
    wrapper.unmount()
  })

  it("7. coalesced multi-minute jump fires every boundary it leapt over", async () => {
    const { wrapper, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [
        block(1, "09:31", "23:00"), // start 571 (in window), end 1380 (out)
        block(2, "09:28", "09:32"), // start 568 (<= prev, out), end 572 (in window)
      ],
    })
    await tick(nowMinutes, 569) // prime
    await tick(nowMinutes, 573) // throttled jump skipping 570/571/572
    // start@571 and end@572 fire; start@568 (before prev) and end@1380 do not.
    expect(createdOscillators.length).toBe(2)
    wrapper.unmount()
  })

  it("8. first tick of a date does not back-fill earlier boundaries", async () => {
    const { wrapper, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:00", "10:00")], // start 540 / end 600
    })
    await tick(nowMinutes, 840) // 14:00 — first tick, exact-840 only
    expect(createdOscillators.length).toBe(0) // morning boundaries not replayed
    wrapper.unmount()
  })

  it("9. fired-Set + lastSeenMinute reset on date navigation", async () => {
    const { wrapper, nowMinutes, nowDate } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570
      nowDate: "2026-06-15",
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570) // fires on date A
    expect(createdOscillators.length).toBe(1)

    // Simulate navigation: off-today, then into a new today.
    await tick(nowMinutes, null)
    nowDate.value = null
    await nextTick()
    nowDate.value = "2026-06-16"
    await nextTick()

    await tick(nowMinutes, 570) // treated as first tick of date B — fires again
    expect(createdOscillators.length).toBe(2)
    wrapper.unmount()
  })

  it("10. off-today (nowDate null) never fires", async () => {
    const { wrapper, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570
      nowDate: null,
    })
    await tick(nowMinutes, 570) // would-be boundary, but off-today
    expect(createdOscillators.length).toBe(0)
    wrapper.unmount()
  })

  it("11. backward clock step fires nothing (no stale burst)", async () => {
    const { wrapper, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:55", "10:05")], // start 595 / end 605
    })
    await tick(nowMinutes, 600) // first tick, exact 600 — no fire
    await tick(nowMinutes, 595) // clock moved back — no fire even though now===595
    expect(createdOscillators.length).toBe(0)
    wrapper.unmount()
  })

  it("12. a re-timed boundary fires again after the original already fired", async () => {
    const { wrapper, blocks, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570) // original start fires (key start:1:date:570)
    expect(createdOscillators.length).toBe(1)

    // User edits block 1 to start 09:45 — re-flow with the SAME id, new time.
    blocks.value = [block(1, "09:45", "10:00")] // start 585
    await tick(nowMinutes, 584)
    await tick(nowMinutes, 585) // new start (key start:1:date:585) — not suppressed
    expect(createdOscillators.length).toBe(2)
    wrapper.unmount()
  })

  it("13. re-enabling after a disabled gap does not back-fire skipped boundaries", async () => {
    const { wrapper, nowMinutes, api } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570 / end 600
    })
    await tick(nowMinutes, 560) // first tick, exact — no boundary, lastSeen=560
    api.setEnabled(false)
    await nextTick()
    await tick(nowMinutes, 565) // disabled gate: no fire AND lastSeen not advanced
    api.setEnabled(true) // watch(enabled) resets lastSeenMinute → fresh first tick
    await nextTick()
    // Without the reset, prev would be 560 and the window (560, 601] would
    // back-fire start@570 and end@600. With it, this is a first tick → exact-
    // 601 only → nothing fires.
    await tick(nowMinutes, 601)
    expect(createdOscillators.length).toBe(0)
    wrapper.unmount()
  })
})

describe("useSoundNotificationSetting — autoplay unlock + persistence", () => {
  function mountSetting(): {
    wrapper: VueWrapper
    api: ReturnType<typeof useSoundNotificationSetting>
  } {
    let api!: ReturnType<typeof useSoundNotificationSetting>
    const Harness = defineComponent({
      setup() {
        api = useSoundNotificationSetting()
        return {}
      },
      template: "<div />",
    })
    return { wrapper: mount(Harness), api }
  }

  it("14. setEnabled(true) resumes the singleton and persists true", () => {
    const { wrapper, api } = mountSetting()
    api.setEnabled(true)
    expect(resumeSpy).toHaveBeenCalledTimes(1)
    expect(storage.store[SOUND_NOTIFICATIONS_KEY]).toBe("true")

    api.setEnabled(false)
    expect(storage.store[SOUND_NOTIFICATIONS_KEY]).toBe("false")
    wrapper.unmount()
  })

  it("14b. a rejected resume() does not throw out of setEnabled", () => {
    resumeSpy = vi.fn(() => Promise.reject(new Error("NotAllowedError")))
    const { wrapper, api } = mountSetting()
    expect(() => api.setEnabled(true)).not.toThrow()
    wrapper.unmount()
  })
})
