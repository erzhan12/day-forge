import { afterEach, describe, expect, it } from "vitest"
import { mount, VueWrapper } from "@vue/test-utils"
import GapSlot4a from "../src/components/GapSlot4a.vue"

let wrapper: VueWrapper | null = null
afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

function mountGap(props: Partial<InstanceType<typeof GapSlot4a>["$props"]> = {}) {
  wrapper = mount(GapSlot4a, {
    props: {
      startTime: "12:10", endTime: "15:00", durationMinutes: 170,
      heightPx: 60, edgeHint: null, disabled: false, ...props,
    },
  })
  return wrapper
}

describe("GapSlot4a (0106)", () => {
  it("shows Free · 2h 50m and 12:10–15:00 on a gap row", () => {
    const w = mountGap()
    expect(w.get('[data-testid="gap-4a-label"]').text()).toBe("Free · 2h 50m")
    expect(w.get('[data-testid="gap-4a-range"]').text()).toBe("12:10–15:00")
    expect(w.get("button").attributes("aria-label")).toBe("Add a block between 12:10 and 15:00")
  })

  it("renders an always-visible + button", () => {
    const w = mountGap()
    const plus = w.get('[data-testid="gap-4a-plus"]')
    expect(plus.text()).toBe("+")
    expect(plus.element.tagName).not.toBe("BUTTON")
    expect(w.findAll("button")).toHaveLength(1)
  })

  it("emits the grid-snapped gap range on click and on Enter", async () => {
    const w = mountGap({ startTime: "12:07", endTime: "14:58", durationMinutes: 171 })
    await w.get("button").trigger("click")
    await w.get("button").trigger("keydown", { key: "Enter" })
    expect(w.emitted("add-here-4a")?.[0]).toEqual([{ start_time: "12:10", end_time: "14:55" }])
    // A native button turns Enter into click; the handler must not double-fire.
    expect(w.emitted("add-here-4a")).toHaveLength(1)
  })

  it("is inert when the gap has no 5-minute slot", async () => {
    const w = mountGap({ startTime: "12:07", endTime: "12:09", durationMinutes: 2, heightPx: 4 })
    const button = w.get("button")
    expect(button.attributes("disabled")).toBeDefined()
    await button.trigger("click")
    expect(w.emitted("add-here-4a")).toBeUndefined()
    expect(w.find('[data-testid="gap-4a-plus"]').exists()).toBe(false)
  })

  it("keeps earlier/later on edge stubs and none on a whole-window gap", () => {
    expect(mountGap({ edgeHint: "earlier" }).text()).toContain("earlier")
    wrapper!.unmount()
    expect(mountGap({ edgeHint: "later" }).text()).toContain("later")
    wrapper!.unmount()
    const whole = mountGap({ edgeHint: null }).text()
    expect(whole).not.toContain("earlier")
    expect(whole).not.toContain("later")
  })

  it("renders no label and no + under 28px but stays clickable", async () => {
    const w = mountGap({ startTime: "12:10", endTime: "12:20", durationMinutes: 10, heightPx: 20 })
    expect(w.find('[data-testid="gap-4a-label"]').exists()).toBe(false)
    expect(w.find('[data-testid="gap-4a-plus"]').exists()).toBe(false)
    await w.get("button").trigger("click")
    expect(w.emitted("add-here-4a")?.[0]).toEqual([{ start_time: "12:10", end_time: "12:20" }])
  })

  it("is inert when disabled", async () => {
    const w = mountGap({ disabled: true })
    await w.get("button").trigger("click")
    expect(w.emitted("add-here-4a")).toBeUndefined()
  })
})
