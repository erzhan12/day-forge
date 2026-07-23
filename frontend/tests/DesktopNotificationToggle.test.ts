// Component test for DesktopNotificationToggle (docs/features/0028_PLAN.md
// Phase 6). REQUIRED — the repeated-denied DOM-resync fix (G1) lives in the
// component's `@change` handler and cannot be exercised by composable tests
// alone. Uses the same per-test Notification stub isolation as the composable
// suite so the unsupported case's `undefined` stub cannot leak.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { flushPromises, mount } from "@vue/test-utils"
import DesktopNotificationToggle from "../src/components/DesktopNotificationToggle.vue"
import { DESKTOP_NOTIFICATIONS_KEY } from "../src/utils/desktopNotificationStorage"

class MockNotification {
  static permission: NotificationPermission = "default"
  static requestPermission = vi.fn<() => Promise<NotificationPermission>>()
  onclick: (() => void) | null = null
  close = vi.fn()
  constructor(
    public title: string,
    public options?: NotificationOptions,
  ) {}
}

const UNSUPPORTED = "This browser doesn't support desktop notifications."
const BLOCKED = "Browser blocked notifications. Allow them in site settings and try again."

beforeEach(() => {
  localStorage.clear()
  MockNotification.permission = "default"
  MockNotification.requestPermission = vi.fn(() => Promise.resolve("default"))
  vi.stubGlobal("Notification", MockNotification)
})

afterEach(() => {
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

describe("DesktopNotificationToggle", () => {
  it("unsupported on init (clean storage): switch disabled + doesn't-support hint", () => {
    vi.stubGlobal("Notification", undefined) // no stored flag either
    const wrapper = mount(DesktopNotificationToggle)
    const input = wrapper.get("input[type=checkbox]")
    expect((input.element as HTMLInputElement).disabled).toBe(true)
    expect(wrapper.text()).toContain(UNSUPPORTED)
    expect(wrapper.text()).not.toContain(BLOCKED)
    wrapper.unmount()
  })

  it("repeated-denied clicks keep the checkbox visually unchecked (DOM resync)", async () => {
    MockNotification.permission = "denied"
    MockNotification.requestPermission = vi.fn(() => Promise.resolve("denied"))
    const wrapper = mount(DesktopNotificationToggle)
    const input = wrapper.get("input[type=checkbox]")
    const el = input.element as HTMLInputElement

    // First click → denied. enabled stays false, permissionDenied flips true.
    await input.setValue(true)
    await flushPromises()
    expect(el.checked).toBe(false)

    // Second click is the regression trigger: neither enabled nor
    // permissionDenied changes, so only the explicit el.checked = enabled.value
    // write keeps the DOM in sync.
    await input.setValue(true)
    await flushPromises()
    expect(el.checked).toBe(false)
    wrapper.unmount()
  })

  it("distinct hint copy: denied (supported) shows the site-settings message only", async () => {
    MockNotification.permission = "denied"
    MockNotification.requestPermission = vi.fn(() => Promise.resolve("denied"))
    const wrapper = mount(DesktopNotificationToggle)
    await wrapper.get("input[type=checkbox]").setValue(true)
    await flushPromises()
    expect(wrapper.text()).toContain(BLOCKED)
    expect(wrapper.text()).not.toContain(UNSUPPORTED)
    wrapper.unmount()
  })

  it("distinct hint copy: unsupported shows the doesn't-support message only, never blocked", () => {
    vi.stubGlobal("Notification", undefined)
    const wrapper = mount(DesktopNotificationToggle)
    expect(wrapper.text()).toContain(UNSUPPORTED)
    expect(wrapper.text()).not.toContain(BLOCKED)
    expect(UNSUPPORTED).not.toBe(BLOCKED)
    wrapper.unmount()
  })

  it("granted happy path: checkbox stays checked, no hint", async () => {
    MockNotification.permission = "default"
    MockNotification.requestPermission = vi.fn(() => Promise.resolve("granted"))
    const wrapper = mount(DesktopNotificationToggle)
    const input = wrapper.get("input[type=checkbox]")
    await input.setValue(true)
    await flushPromises()
    expect((input.element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.text()).not.toContain(BLOCKED)
    expect(wrapper.text()).not.toContain(UNSUPPORTED)
    expect(readStored()).toBe("true")
    wrapper.unmount()
  })
})

function readStored(): string | null {
  return localStorage.getItem(DESKTOP_NOTIFICATIONS_KEY)
}
