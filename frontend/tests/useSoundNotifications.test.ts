// Sound-specific tests for useSoundNotifications (issue #56 /
// docs/features/0019_PLAN.md Phase 5). The crossed-since-last-sample detector
// cases now live in tests/useBlockBoundaryDetector.test.ts (feature 0028) —
// this file keeps the chime-synthesis assertions, the setting persistence /
// resume tests, and a wiring/gate test proving useSoundNotifications threads
// its real `enabled` ref into the shared detector. All minute values are
// minutes-since-midnight, e.g. "09:30" === 570.

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

describe("useSoundNotifications — chime synthesis", () => {
  it("start boundary fires a rising chime", async () => {
    const { wrapper, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570
    })
    await tick(nowMinutes, 569) // prime (first tick, exact-only, no fire)
    await tick(nowMinutes, 570) // window (569, 570] — start fires
    expect(createdOscillators.length).toBe(1)
    const osc = createdOscillators[0]
    expect(freqAt(osc, 1)).toBeGreaterThan(freqAt(osc, 0)) // rising

    // Wiring contract (plan §Web Audio): osc → gain → destination, the node is
    // actually started/stopped, and a click-free gain envelope is scheduled.
    // Without this, a regression that built a correct oscillator but never
    // connected it to destination (silent output) would still pass.
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

  it("end boundary fires a falling chime (distinct from start)", async () => {
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

  // REQUIRED wiring/gate test: proves useSoundNotifications threads its real
  // `enabled` ref into the shared detector. The detector's own gate cases live
  // in useBlockBoundaryDetector.test.ts (synthetic enabled ref); without this,
  // a mis-wire hardcoding `enabled: ref(true)` would still pass the synthesis
  // tests above while Schedule chimed with the toggle OFF.
  it("wires the setting into the detector: enabled → one chime", async () => {
    const { wrapper, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570)
    expect(createdOscillators.length).toBe(1)
    wrapper.unmount()
  })

  it("wires the setting into the detector: disabled → zero chimes", async () => {
    const { wrapper, nowMinutes } = mountDetector({
      enabled: false,
      blocks: [block(1, "09:30", "10:00")], // start 570
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570)
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
