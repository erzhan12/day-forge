import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import ShowIndicatorButton from "../src/components/ShowIndicatorButton.vue"

function mountBtn(props: Record<string, unknown> = {}) {
  return mount(ShowIndicatorButton, {
    props: { supported: true, isOpen: false, ...props },
  })
}

describe("ShowIndicatorButton", () => {
  it("shows 'Show indicator' when closed and emits 'open' on click", async () => {
    const w = mountBtn({ supported: true, isOpen: false })
    const btn = w.find("button")
    expect(btn.text()).toContain("Show indicator")
    expect(btn.attributes("disabled")).toBeUndefined()
    await btn.trigger("click")
    expect(w.emitted("open")).toHaveLength(1)
  })

  it("shows a disabled 'Indicator open' status when open, and does not emit", async () => {
    const w = mountBtn({ supported: true, isOpen: true })
    const btn = w.find("button")
    expect(btn.text()).toContain("Indicator open")
    expect(btn.attributes("disabled")).toBeDefined()
    await btn.trigger("click")
    expect(w.emitted("open")).toBeUndefined()
  })

  it("is disabled with a concise explanation when unsupported", () => {
    const w = mountBtn({ supported: false, isOpen: false })
    expect(w.find("button").attributes("disabled")).toBeDefined()
    expect(w.text().toLowerCase()).toContain("not supported")
  })

  it("label does not depend on active-block state (available with no current block)", () => {
    // The component takes only supported/isOpen — no block/active prop exists,
    // so the control is always present regardless of whether a block is current.
    const w = mountBtn({ supported: true, isOpen: false })
    expect(w.find("button").exists()).toBe(true)
    expect(w.find("button").text()).toContain("Show indicator")
  })

  it("does not auto-emit on mount", () => {
    const w = mountBtn({ supported: true, isOpen: false })
    expect(w.emitted("open")).toBeUndefined()
  })
})
