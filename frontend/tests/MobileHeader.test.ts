import { afterEach, describe, expect, it, vi } from "vitest"
import { mount, type VueWrapper } from "@vue/test-utils"
import { nextTick } from "vue"

const { visit } = vi.hoisted(() => ({ visit: vi.fn() }))
vi.mock("@inertiajs/vue3", () => ({
  router: { visit },
  Link: { props: ["href"], template: "<a :href='href'><slot /></a>" },
}))

import MobileHeader from "../src/components/MobileHeader.vue"

let wrapper: VueWrapper | null = null

function mountHeader(props: Partial<{ date: string; showAnalytics: boolean; showCalendars: boolean }> = {}) {
  wrapper = mount(MobileHeader, {
    props: { date: "2026-11-27", showAnalytics: true, showCalendars: true, ...props },
    attachTo: document.body,
  })
  return wrapper
}

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  visit.mockClear()
})

describe("MobileHeader (feature 0113)", () => {
  it("shows the short date and nothing from the desktop header", () => {
    const w = mountHeader()
    expect(w.get('[data-testid="mobile-date"]').text()).toBe("Fri, Nov 27")
    const text = w.text()
    for (const word of ["Undo", "Show indicator", "Today", "Regenerate", "Draft", "View analytics"]) {
      expect(text).not.toContain(word)
    }
    expect(w.findAll("button")).toHaveLength(3)
  })

  it("moves one civil day with the arrows, across a month end", async () => {
    const w = mountHeader({ date: "2026-11-30" })
    await w.get('[data-testid="mobile-next"]').trigger("click")
    expect(visit).toHaveBeenLastCalledWith("/schedule/2026-12-01/")
    await w.get('[data-testid="mobile-prev"]').trigger("click")
    expect(visit).toHaveBeenLastCalledWith("/schedule/2026-11-29/")
  })

  it("opens a menu with Settings, View analytics, Calendars and Log out", async () => {
    const w = mountHeader()
    expect(w.find('[data-testid="mobile-menu"]').exists()).toBe(false)
    await w.get('[data-testid="mobile-gear"]').trigger("click")
    const menu = w.get('[data-testid="mobile-menu"]')
    expect(menu.get('[data-testid="mobile-menu-settings"]').attributes("href")).toBe("/settings/")
    expect(menu.get('[data-testid="mobile-menu-analytics"]').attributes("href")).toBe("/analytics/2026-11-27/")
    expect(menu.find('[data-testid="mobile-menu-calendars"]').exists()).toBe(true)
    const items = menu.findAll("a, button").map((el) => el.text())
    expect(items).toEqual(["Settings", "View analytics", "Calendars", "Log out"])
  })

  it("omits View analytics and Calendars when they do not apply", async () => {
    const w = mountHeader({ showAnalytics: false, showCalendars: false })
    await w.get('[data-testid="mobile-gear"]').trigger("click")
    const items = w.get('[data-testid="mobile-menu"]').findAll("a, button").map((el) => el.text())
    expect(items).toEqual(["Settings", "Log out"])
  })

  it("moves focus into the menu, wraps Tab, and closes on Escape with focus back on the gear", async () => {
    const w = mountHeader()
    const gear = w.get('[data-testid="mobile-gear"]').element as HTMLElement
    gear.focus()
    await w.get('[data-testid="mobile-gear"]').trigger("click")
    await nextTick()
    const menu = w.get('[data-testid="mobile-menu"]')
    const buttons = menu.findAll("a, button").map((el) => el.element as HTMLElement)
    expect(document.activeElement).toBe(buttons[0])
    buttons[buttons.length - 1].focus()
    await menu.trigger("keydown", { key: "Tab" })
    expect(document.activeElement).toBe(buttons[0])
    await menu.trigger("keydown", { key: "Tab", shiftKey: true })
    expect(document.activeElement).toBe(buttons[buttons.length - 1])
    await menu.trigger("keydown", { key: "Escape" })
    await nextTick()
    await nextTick()
    expect(w.find('[data-testid="mobile-menu"]').exists()).toBe(false)
    expect(document.activeElement).toBe(gear)
  })

  it("closes on a backdrop tap", async () => {
    const w = mountHeader()
    await w.get('[data-testid="mobile-gear"]').trigger("click")
    await w.get('[data-testid="mobile-menu-backdrop"]').trigger("click")
    expect(w.find('[data-testid="mobile-menu"]').exists()).toBe(false)
  })

  it("emits calendars and logout and closes the menu", async () => {
    const w = mountHeader()
    await w.get('[data-testid="mobile-gear"]').trigger("click")
    await w.get('[data-testid="mobile-menu-calendars"]').trigger("click")
    expect(w.emitted("calendars")).toHaveLength(1)
    expect(w.find('[data-testid="mobile-menu"]').exists()).toBe(false)
    await w.get('[data-testid="mobile-gear"]').trigger("click")
    await w.get('[data-testid="mobile-menu-logout"]').trigger("click")
    expect(w.emitted("logout")).toHaveLength(1)
    expect(w.find('[data-testid="mobile-menu"]').exists()).toBe(false)
  })
})
