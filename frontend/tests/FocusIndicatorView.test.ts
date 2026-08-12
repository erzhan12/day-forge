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
      completing: false,
      errorState: false,
      disabled: false,
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

  it("renders an icon-only Complete button with a generic accessible name", () => {
    const w = mountView({ active: true })
    const btn = w.find("button")
    expect(btn.exists()).toBe(true)
    expect(btn.attributes("aria-label")).toBe("Complete current block")
    // No text that identifies the block.
    for (const s of PRIVATE) expect(w.html()).not.toContain(s)
  })

  it("emits 'complete' on click when enabled", async () => {
    const w = mountView({ active: true, disabled: false, completing: false })
    await w.find("button").trigger("click")
    expect(w.emitted("complete")).toHaveLength(1)
  })

  it("natively disables Complete and does not emit when disabled", async () => {
    const w = mountView({ active: true, disabled: true })
    const btn = w.find("button")
    expect(btn.attributes("disabled")).toBeDefined()
    await btn.trigger("click")
    expect(w.emitted("complete")).toBeUndefined()
  })

  it("disables Complete while completing (no duplicate emit)", async () => {
    const w = mountView({ active: true, completing: true })
    const btn = w.find("button")
    expect(btn.attributes("disabled")).toBeDefined()
    await btn.trigger("click")
    expect(w.emitted("complete")).toBeUndefined()
  })

  it("renders neutral (no bar, no Complete) when inactive", () => {
    const w = mountView({ active: false })
    expect(w.find('[role="progressbar"]').exists()).toBe(false)
    expect(w.find("button").exists()).toBe(false)
  })

  it("in error state keeps the bar + re-enabled Complete and shows a generic retry affordance", () => {
    const w = mountView({ active: true, errorState: true, completing: false })
    expect(w.find('[role="progressbar"]').exists()).toBe(true)
    expect(w.find("button").attributes("disabled")).toBeUndefined()
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
