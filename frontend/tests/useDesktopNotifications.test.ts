// Desktop-notification composable (issue #100 / docs/features/0028_PLAN.md
// Phase 3 & 6). Detector-parity cases (mirroring the sound detector 1–13) plus
// the permission/setting flow with `Notification` mocked. All minute values
// are minutes-since-midnight, e.g. "09:30" === 570.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { defineComponent, nextTick, ref } from "vue"
import type { Ref } from "vue"
import { mount, type VueWrapper } from "@vue/test-utils"
import type { TimeBlock } from "../src/types"
import {
  DESKTOP_NOTIFICATIONS_KEY,
  readDesktopNotificationsEnabled,
} from "../src/utils/desktopNotificationStorage"
import {
  showDesktopNotification,
  useDesktopNotifications,
  useDesktopNotificationSetting,
} from "../src/composables/useDesktopNotifications"
import { SOUND_NOTIFICATIONS_KEY } from "../src/utils/soundNotificationStorage"
import { useSoundNotifications } from "../src/composables/useSoundNotifications"
import { closeAudioContext } from "../src/utils/audioContext"

// --- Notification mock ------------------------------------------------------

class MockNotification {
  static permission: NotificationPermission = "default"
  static requestPermission = vi.fn<() => Promise<NotificationPermission>>()
  static instances: MockNotification[] = []
  onclick: (() => void) | null = null
  close = vi.fn()
  constructor(
    public title: string,
    public options?: NotificationOptions,
  ) {
    MockNotification.instances.push(this)
  }
}

beforeEach(() => {
  // jsdom localStorage is real and persists across tests — reset it or a
  // seeded `true` bleeds into later cases. See plan §Phase 6.
  localStorage.clear()
  MockNotification.instances = []
  MockNotification.permission = "default"
  MockNotification.requestPermission = vi.fn(() => Promise.resolve("default"))
  vi.stubGlobal("Notification", MockNotification)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

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
  api: ReturnType<typeof useDesktopNotifications>
} {
  // Storage `true` alone is NOT enough — mount revalidation clears the flag
  // unless permission is already granted, so callers that want the ON path set
  // permission granted before mounting AND pass enabled:true.
  if (opts.enabled) localStorage.setItem(DESKTOP_NOTIFICATIONS_KEY, "true")
  const blocks = ref<TimeBlock[]>(opts.blocks)
  const nowMinutes = ref<number | null>(opts.nowMinutes ?? null)
  const hasNowDate = Object.prototype.hasOwnProperty.call(opts, "nowDate")
  const nowDate = ref<string | null>(hasNowDate ? opts.nowDate! : "2026-06-15")
  let api!: ReturnType<typeof useDesktopNotifications>
  const Harness = defineComponent({
    setup() {
      api = useDesktopNotifications(nowMinutes, nowDate, () => blocks.value)
      return {}
    },
    template: "<div />",
  })
  return { wrapper: mount(Harness), blocks, nowMinutes, nowDate, api }
}

function mountSetting(): {
  wrapper: VueWrapper
  api: ReturnType<typeof useDesktopNotificationSetting>
} {
  let api!: ReturnType<typeof useDesktopNotificationSetting>
  const Harness = defineComponent({
    setup() {
      api = useDesktopNotificationSetting()
      return {}
    },
    template: "<div />",
  })
  return { wrapper: mount(Harness), api }
}

async function tick(nowMinutes: Ref<number | null>, m: number | null) {
  nowMinutes.value = m
  await nextTick()
}

const instances = () => MockNotification.instances
const tagOf = (n: MockNotification) => n.options?.tag

// --- detector parity --------------------------------------------------------

describe("useDesktopNotifications — detector parity", () => {
  it("setting off → no Notification constructed", async () => {
    const { wrapper, nowMinutes } = mountDetector({
      enabled: false,
      blocks: [block(1, "09:30", "10:00")], // start 570
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570)
    expect(instances().length).toBe(0)
    wrapper.unmount()
  })

  it("start boundary → one notification, title/body/tag match copy spec", async () => {
    MockNotification.permission = "granted"
    const { wrapper, nowMinutes, nowDate } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570)
    expect(instances().length).toBe(1)
    const n = instances()[0]
    expect(n.title).toBe("Block started")
    expect(n.options?.body).toBe("block-1 · 09:30–10:00")
    expect(tagOf(n)).toBe(`day-forge:start:1:${nowDate.value}:570`)
    wrapper.unmount()
  })

  it("end boundary → falling copy, tag …:end:…:minute", async () => {
    MockNotification.permission = "granted"
    const { wrapper, nowMinutes, nowDate } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // end 600
    })
    await tick(nowMinutes, 599)
    await tick(nowMinutes, 600)
    expect(instances().length).toBe(1)
    const n = instances()[0]
    expect(n.title).toBe("Block ended")
    expect(n.options?.body).toBe("block-1 finished")
    expect(tagOf(n)).toBe(`day-forge:end:1:${nowDate.value}:600`)
    wrapper.unmount()
  })

  it("no double-fire for the same boundary on re-entry", async () => {
    MockNotification.permission = "granted"
    const { wrapper, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570)
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570)
    expect(instances().length).toBe(1)
    wrapper.unmount()
  })

  it("two blocks sharing a start minute → two notifications (distinct tags)", async () => {
    MockNotification.permission = "granted"
    const { wrapper, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00"), block(2, "09:30", "11:00")],
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570)
    expect(instances().length).toBe(2)
    expect(new Set(instances().map(tagOf)).size).toBe(2)
    wrapper.unmount()
  })

  it("coalesced multi-minute jump fires every boundary it leapt over", async () => {
    MockNotification.permission = "granted"
    const { wrapper, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [
        block(1, "09:31", "23:00"), // start 571 in, end 1380 out
        block(2, "09:28", "09:32"), // start 568 out, end 572 in
      ],
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 573)
    expect(instances().length).toBe(2)
    wrapper.unmount()
  })

  it("first tick of a date does not back-fill earlier boundaries", async () => {
    MockNotification.permission = "granted"
    const { wrapper, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:00", "10:00")], // start 540 / end 600
    })
    await tick(nowMinutes, 840) // 14:00 first tick, exact-only
    expect(instances().length).toBe(0)
    wrapper.unmount()
  })

  it("fired-Set resets on date navigation", async () => {
    MockNotification.permission = "granted"
    const { wrapper, nowMinutes, nowDate } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570
      nowDate: "2026-06-15",
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570)
    expect(instances().length).toBe(1)

    await tick(nowMinutes, null)
    nowDate.value = null
    await nextTick()
    nowDate.value = "2026-06-16"
    await nextTick()

    await tick(nowMinutes, 570)
    expect(instances().length).toBe(2)
    expect(tagOf(instances()[1])).toBe("day-forge:start:1:2026-06-16:570")
    wrapper.unmount()
  })

  it("off-today (nowDate null) never fires", async () => {
    MockNotification.permission = "granted"
    const { wrapper, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")],
      nowDate: null,
    })
    await tick(nowMinutes, 570)
    expect(instances().length).toBe(0)
    wrapper.unmount()
  })

  it("backward clock step fires nothing", async () => {
    MockNotification.permission = "granted"
    const { wrapper, nowMinutes } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:55", "10:05")], // start 595
    })
    await tick(nowMinutes, 600)
    await tick(nowMinutes, 595)
    expect(instances().length).toBe(0)
    wrapper.unmount()
  })

  it("re-timed boundary re-fires with the NEW minute in its tag", async () => {
    MockNotification.permission = "granted"
    const { wrapper, blocks, nowMinutes, nowDate } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570
    })
    await tick(nowMinutes, 569)
    await tick(nowMinutes, 570)
    expect(instances().length).toBe(1)

    blocks.value = [block(1, "09:45", "10:00")] // start 585
    await tick(nowMinutes, 584)
    await tick(nowMinutes, 585)
    expect(instances().length).toBe(2)
    // New minute in the tag proves the minute-in-tag alignment fix.
    expect(tagOf(instances()[1])).toBe(`day-forge:start:1:${nowDate.value}:585`)
    wrapper.unmount()
  })

  it("re-enabling after a disabled gap does not back-fire skipped boundaries", async () => {
    MockNotification.permission = "granted"
    MockNotification.requestPermission = vi.fn(() => Promise.resolve("granted"))
    const { wrapper, nowMinutes, api } = mountDetector({
      enabled: true,
      blocks: [block(1, "09:30", "10:00")], // start 570 / end 600
    })
    await tick(nowMinutes, 560)
    await api.setEnabled(false)
    await nextTick()
    await tick(nowMinutes, 565) // disabled: no fire, cursor not advanced
    await api.setEnabled(true) // watch(enabled) resets → fresh first tick
    await nextTick()
    await tick(nowMinutes, 601)
    expect(instances().length).toBe(0)
    wrapper.unmount()
  })
})

// --- permission / setting flow ----------------------------------------------

describe("useDesktopNotificationSetting — permission flow", () => {
  it("setEnabled(true) + granted → storage true, enabled true", async () => {
    MockNotification.requestPermission = vi.fn(() => Promise.resolve("granted"))
    const { wrapper, api } = mountSetting()
    await api.setEnabled(true)
    expect(readDesktopNotificationsEnabled()).toBe(true)
    expect(api.enabled.value).toBe(true)
    expect(api.permissionDenied.value).toBe(false)
    wrapper.unmount()
  })

  it("setEnabled(true) + denied → not persisted, permissionDenied true", async () => {
    MockNotification.requestPermission = vi.fn(() => Promise.resolve("denied"))
    const { wrapper, api } = mountSetting()
    await api.setEnabled(true)
    expect(readDesktopNotificationsEnabled()).toBe(false)
    expect(api.enabled.value).toBe(false)
    expect(api.permissionDenied.value).toBe(true)
    wrapper.unmount()
  })

  it("requestPermission rejecting is treated as denied, no unhandled rejection", async () => {
    MockNotification.requestPermission = vi.fn(() =>
      Promise.reject(new Error("TypeError")),
    )
    const { wrapper, api } = mountSetting()
    await expect(api.setEnabled(true)).resolves.toBeUndefined()
    expect(readDesktopNotificationsEnabled()).toBe(false)
    expect(api.enabled.value).toBe(false)
    expect(api.permissionDenied.value).toBe(true)
    wrapper.unmount()
  })

  it("stale-request race: late grant after setEnabled(false) stays OFF, no spurious hint", async () => {
    let resolvePermission!: (v: NotificationPermission) => void
    MockNotification.requestPermission = vi.fn(
      () =>
        new Promise<NotificationPermission>((r) => {
          resolvePermission = r
        }),
    )
    const { wrapper, api } = mountSetting()
    const pending = api.setEnabled(true) // suspends at the await
    await api.setEnabled(false) // supersedes — bumps requestSeq
    resolvePermission("granted") // late grant resolves
    await pending

    expect(api.enabled.value).toBe(false) // NOT resurrected to true
    expect(readDesktopNotificationsEnabled()).toBe(false)
    expect(api.permissionDenied.value).toBe(false) // no spurious "blocked" hint
    wrapper.unmount()
  })

  it("stale-request race: late DENIAL after setEnabled(false) leaves no spurious hint", async () => {
    // Sibling of the late-grant case: proves the unconditional guard also
    // stops the DENIED branch from stamping permissionDenied=true on a
    // checkbox the user already turned off.
    let resolvePermission!: (v: NotificationPermission) => void
    MockNotification.requestPermission = vi.fn(
      () =>
        new Promise<NotificationPermission>((r) => {
          resolvePermission = r
        }),
    )
    const { wrapper, api } = mountSetting()
    const pending = api.setEnabled(true) // suspends at the await
    await api.setEnabled(false) // supersedes — bumps requestSeq
    resolvePermission("denied") // late denial resolves
    await pending

    expect(api.enabled.value).toBe(false)
    expect(readDesktopNotificationsEnabled()).toBe(false)
    expect(api.permissionDenied.value).toBe(false) // guard blocked the hint
    wrapper.unmount()
  })

  it("unsupported browser: setEnabled(true) → notSupported true, permissionDenied false, no throw", async () => {
    vi.stubGlobal("Notification", undefined)
    const { wrapper, api } = mountSetting()
    await expect(api.setEnabled(true)).resolves.toBeUndefined()
    expect(api.enabled.value).toBe(false)
    expect(api.notSupported.value).toBe(true)
    expect(api.permissionDenied.value).toBe(false)
    wrapper.unmount()
  })

  it("unsupported browser on mount with stale storage true → off + flag cleared", () => {
    localStorage.setItem(DESKTOP_NOTIFICATIONS_KEY, "true")
    vi.stubGlobal("Notification", undefined)
    const { wrapper, api } = mountSetting()
    expect(api.enabled.value).toBe(false)
    expect(api.notSupported.value).toBe(true)
    expect(readDesktopNotificationsEnabled()).toBe(false) // stale flag cleared
    wrapper.unmount()
  })

  it("mount revalidation: storage true but permission denied → off + flag cleared", () => {
    localStorage.setItem(DESKTOP_NOTIFICATIONS_KEY, "true")
    MockNotification.permission = "denied"
    const { wrapper, api } = mountSetting()
    expect(api.enabled.value).toBe(false)
    expect(readDesktopNotificationsEnabled()).toBe(false)
    wrapper.unmount()
  })

  it("mount: storage true + permission granted → enabled true", () => {
    localStorage.setItem(DESKTOP_NOTIFICATIONS_KEY, "true")
    MockNotification.permission = "granted"
    const { wrapper, api } = mountSetting()
    expect(api.enabled.value).toBe(true)
    wrapper.unmount()
  })
})

// --- showDesktopNotification direct -----------------------------------------

describe("showDesktopNotification", () => {
  it("no-ops when permission !== granted", () => {
    MockNotification.permission = "default"
    showDesktopNotification("start", block(1, "09:30", "10:00"), "2026-06-15", 570)
    expect(instances().length).toBe(0)
  })

  it("onclick focuses the tab and closes the notification", () => {
    MockNotification.permission = "granted"
    const focusSpy = vi.spyOn(window, "focus").mockImplementation(() => {})
    showDesktopNotification("start", block(1, "09:30", "10:00"), "2026-06-15", 570)
    expect(instances().length).toBe(1)
    const n = instances()[0]
    n.onclick?.()
    expect(focusSpy).toHaveBeenCalledTimes(1)
    expect(n.close).toHaveBeenCalledTimes(1)
  })

  it("swallows a constructor throw (never breaks the render path)", () => {
    class ThrowingNotification {
      static permission: NotificationPermission = "granted"
      constructor() {
        throw new Error("boom")
      }
    }
    vi.stubGlobal("Notification", ThrowingNotification)
    expect(() =>
      showDesktopNotification("start", block(1, "09:30", "10:00"), "2026-06-15", 570),
    ).not.toThrow()
  })

  it("no-ops entirely when Notification is undefined", () => {
    vi.stubGlobal("Notification", undefined)
    expect(() =>
      showDesktopNotification("start", block(1, "09:30", "10:00"), "2026-06-15", 570),
    ).not.toThrow()
  })
})

// --- independent-cursor contract (dual channel) -----------------------------

// Mounting sound + desktop on the SAME nowMinutes/nowDate/getBlocks refs and
// disabling one channel must not stop the other — each detector owns its own
// lastSeenMinute/fired cursor (RULES.md §Desktop notifications). Requires a
// Web Audio mock in addition to the Notification mock stubbed above.

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
let dualOscillators: MockOscillator[] = []
class MockAudioContext {
  state = "suspended"
  currentTime = 0
  destination = {}
  resume = vi.fn(() => Promise.resolve())
  close = vi.fn(() => Promise.resolve())
  createOscillator = vi.fn(() => {
    const o = new MockOscillator()
    dualOscillators.push(o)
    return o
  })
  createGain = vi.fn(() => new MockGain())
}

describe("independent cursors: disabling desktop leaves sound firing", () => {
  it("sound fires and desktop does not after the desktop channel is disabled mid-run", async () => {
    dualOscillators = []
    // Both channels enabled + permitted at mount.
    localStorage.setItem(SOUND_NOTIFICATIONS_KEY, "true")
    localStorage.setItem(DESKTOP_NOTIFICATIONS_KEY, "true")
    MockNotification.permission = "granted"
    MockNotification.requestPermission = vi.fn(() => Promise.resolve("granted"))
    vi.stubGlobal("AudioContext", MockAudioContext)

    const blocks = ref<TimeBlock[]>([block(1, "09:30", "10:00")]) // start 570
    const nowMinutes = ref<number | null>(null)
    const nowDate = ref<string | null>("2026-06-15")
    let desktopApi!: ReturnType<typeof useDesktopNotifications>
    const Harness = defineComponent({
      setup() {
        const getBlocks = () => blocks.value
        useSoundNotifications(nowMinutes, nowDate, getBlocks)
        desktopApi = useDesktopNotifications(nowMinutes, nowDate, getBlocks)
        return {}
      },
      template: "<div />",
    })
    const wrapper = mount(Harness)

    await tick(nowMinutes, 569) // prime both cursors
    await desktopApi.setEnabled(false) // disable ONLY desktop mid-run
    await nextTick()
    await tick(nowMinutes, 570) // cross the start boundary

    expect(dualOscillators.length).toBe(1) // sound cursor advanced + fired
    expect(instances().length).toBe(0) // desktop stayed silent

    wrapper.unmount()
    closeAudioContext()
  })

  it("desktop fires and sound does not after the sound channel is disabled mid-run", async () => {
    dualOscillators = []
    localStorage.setItem(SOUND_NOTIFICATIONS_KEY, "true")
    localStorage.setItem(DESKTOP_NOTIFICATIONS_KEY, "true")
    MockNotification.permission = "granted"
    MockNotification.requestPermission = vi.fn(() => Promise.resolve("granted"))
    vi.stubGlobal("AudioContext", MockAudioContext)

    const blocks = ref<TimeBlock[]>([block(1, "09:30", "10:00")]) // start 570
    const nowMinutes = ref<number | null>(null)
    const nowDate = ref<string | null>("2026-06-15")
    let soundApi!: ReturnType<typeof useSoundNotifications>
    const Harness = defineComponent({
      setup() {
        const getBlocks = () => blocks.value
        soundApi = useSoundNotifications(nowMinutes, nowDate, getBlocks)
        useDesktopNotifications(nowMinutes, nowDate, getBlocks)
        return {}
      },
      template: "<div />",
    })
    const wrapper = mount(Harness)

    await tick(nowMinutes, 569) // prime both cursors
    soundApi.setEnabled(false) // disable ONLY sound mid-run
    await nextTick()
    await tick(nowMinutes, 570) // cross the start boundary

    expect(instances().length).toBe(1) // desktop cursor advanced + fired
    expect(dualOscillators.length).toBe(0) // sound stayed silent

    wrapper.unmount()
    closeAudioContext()
  })
})
