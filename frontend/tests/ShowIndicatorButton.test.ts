import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import ShowIndicatorButton from "../src/components/ShowIndicatorButton.vue"

function mountBtn(props: Record<string, unknown> = {}) {
  return mount(ShowIndicatorButton, {
    props: { supported: true, isOpen: false, shouldRestore: false, error: null, ...props },
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

  it("shows enabled Hide indicator when open and emits close", async () => {
    const w = mountBtn({ supported: true, isOpen: true })
    const btn = w.find("button")
    expect(btn.text()).toContain("Hide indicator")
    expect(btn.attributes("disabled")).toBeUndefined()
    await btn.trigger("click")
    expect(w.emitted("close")).toHaveLength(1)
  })

  it("is disabled with a concise explanation when unsupported", () => {
    const w = mountBtn({ supported: false, isOpen: false })
    expect(w.find("button").attributes("disabled")).toBeDefined()
    expect(w.text().toLowerCase()).toContain("not supported")
  })

  it("label does not depend on active-block state (available with no current block)", () => {
    // No block/active prop exists, so the control is always present regardless
    // of whether a block is current.
    const w = mountBtn({ supported: true, isOpen: false })
    expect(w.find("button").exists()).toBe(true)
    expect(w.find("button").text()).toContain("Show indicator")
  })

  it("does not auto-emit on mount", () => {
    const w = mountBtn({ supported: true, isOpen: false })
    expect(w.emitted("open")).toBeUndefined()
  })

  it("exposes a distinct accessible restore affordance", () => {
    const normal = mountBtn({ shouldRestore: false }).get("button")
    const restore = mountBtn({ shouldRestore: true }).get("button")
    expect(restore.attributes("aria-description")).toBe("Reopen focus indicator")
    expect(normal.attributes("aria-description")).toBeUndefined()
  })

  it("renders an accessible error while leaving retry available", async () => {
    const w = mountBtn({ error: "Could not open indicator. Please try again." })
    const alert = w.get('[role="alert"]')
    expect(alert.text()).toBe("Could not open indicator. Please try again.")
    expect(w.get("button").attributes("disabled")).toBeUndefined()

    await w.get("button").trigger("click")
    expect(w.emitted("open")).toHaveLength(1)
  })
})
