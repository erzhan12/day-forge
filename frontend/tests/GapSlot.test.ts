import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import GapSlot from "../src/components/GapSlot.vue"

describe("GapSlot compact variant", () => {
  it("shows earlier hint on a compressed leading stub", () => {
    const wrapper = mount(GapSlot, {
      props: {
        startTime: "06:00",
        endTime: "09:00",
        durationMinutes: 180,
        compact: true,
      },
    })
    expect(wrapper.text()).toContain("Free — 3h")
    expect(wrapper.text()).toContain("earlier")
    expect(wrapper.text()).toContain("06:00 – 09:00")
    expect(wrapper.find(".gap-slot").classes()).toContain("compact")
  })

  it("shows later hint on a compressed trailing stub", () => {
    const wrapper = mount(GapSlot, {
      props: {
        startTime: "18:00",
        endTime: "23:00",
        durationMinutes: 300,
        compact: true,
      },
    })
    expect(wrapper.text()).toContain("later")
  })

  it("emits the full semantic range on click", async () => {
    const wrapper = mount(GapSlot, {
      props: {
        startTime: "06:00",
        endTime: "09:00",
        durationMinutes: 180,
        compact: true,
      },
    })
    await wrapper.trigger("click")
    expect(wrapper.emitted("add-here")).toEqual([
      [{ start_time: "06:00", end_time: "09:00" }],
    ])
  })
})
