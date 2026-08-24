import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import FocusIndicatorView from "../src/components/FocusIndicatorView.vue"

// Sentinel private strings that must NEVER appear in the PiP view.
const PRIVATE = ["Standup with Bob", "work", "2026-08-12", "09:00", "10:00"]

function mountView(props: Record<string, unknown> = {}) {
  return mount(FocusIndicatorView, {
    props: {
      active: true,
      progressPercent: 42,
      errorState: false,
      ...props,
    },
  })
}

describe("FocusIndicatorView", () => {
  it("renders an accessible progressbar when active", () => {
    const w = mountView({ active: true, progressPercent: 42 })
    const bar = w.find('[role="progressbar"]')
    expect(bar.exists()).toBe(true)
    expect(bar.attributes("aria-valuemin")).toBe("0")
    expect(bar.attributes("aria-valuemax")).toBe("100")
    expect(bar.attributes("aria-valuenow")).toBe("42")
  })

  it("shows remaining minutes after the bar, matching the timeline badge", () => {
    const w = mountView({ remainingMinutes: 23 })
    const label = w.find(".fi-remaining")
    expect(label.exists()).toBe(true)
    expect(label.text()).toBe("23m left")
    const html = w.html()
    expect(html.indexOf("fi-bar")).toBeLessThan(html.indexOf("fi-remaining"))
    expect(w.find("button").exists()).toBe(false)
    for (const s of PRIVATE) expect(html).not.toContain(s)
  })

  it("formats hour-plus remaining the same as the timeline badge", () => {
    expect(mountView({ remainingMinutes: 90 }).find(".fi-remaining").text()).toBe(
      "1h 30m left",
    )
  })

  it("hides remaining minutes when inactive", () => {
    const w = mountView({ active: false, remainingMinutes: 23 })
    expect(w.find(".fi-remaining").exists()).toBe(false)
  })

  it("does not render a Complete control", () => {
    const w = mountView({ active: true })
    expect(w.find("button").exists()).toBe(false)
    expect(w.find(".fi-complete").exists()).toBe(false)
    for (const s of PRIVATE) expect(w.html()).not.toContain(s)
  })

  it("renders neutral (no bar, no Complete) when inactive", () => {
    const w = mountView({ active: false })
    expect(w.find('[role="progressbar"]').exists()).toBe(false)
    expect(w.find("button").exists()).toBe(false)
  })

  it("in error state keeps the bar and shows a generic retry affordance", () => {
    const w = mountView({ active: true, errorState: true })
    expect(w.find('[role="progressbar"]').exists()).toBe(true)
    expect(w.find("button").exists()).toBe(false)
    const retry = w.find(".fi-retry")
    expect(retry.exists()).toBe(true)
    expect(retry.text()).toBe("Retry")
    expect(retry.attributes("role")).toBe("alert")
    const html = w.html()
    for (const s of PRIVATE) expect(html).not.toContain(s)
  })

  it("conveys state via a non-color data attribute (not color alone)", () => {
    expect(mountView({ active: true }).find(".focus-indicator").attributes("data-state")).toBe(
      "active",
    )
    expect(
      mountView({ active: false }).find(".focus-indicator").attributes("data-state"),
    ).toBe("neutral")
    expect(
      mountView({ active: true, errorState: true }).find(".focus-indicator").attributes(
        "data-state",
      ),
    ).toBe("error")
  })
})
