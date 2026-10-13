import { describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"

const { visit } = vi.hoisted(() => ({ visit: vi.fn() }))
vi.mock("@inertiajs/vue3", () => ({
  router: { visit },
  Link: { template: "<a><slot /></a>" },
}))

import DateNavigator from "../src/components/DateNavigator.vue"

describe("DateNavigator", () => {
  it("uses the saved-zone today supplied by the page", async () => {
    const wrapper = mount(DateNavigator, {
      props: { date: "2026-03-07", today: "2026-03-08" },
    })
    await wrapper.get(".today-btn").trigger("click")
    expect(visit).toHaveBeenLastCalledWith("/schedule/2026-03-08/")
    await wrapper.setProps({ today: "2026-03-07" })
    expect(wrapper.find(".today-btn").exists()).toBe(false)
  })

  it("moves one civil day across DST boundaries", async () => {
    const wrapper = mount(DateNavigator, {
      props: { date: "2026-03-08", today: "2026-03-08" },
    })
    await wrapper.findAll(".nav-btn")[2].trigger("click")
    expect(visit).toHaveBeenLastCalledWith("/schedule/2026-03-09/")
    await wrapper.findAll(".nav-btn")[0].trigger("click")
    expect(visit).toHaveBeenLastCalledWith("/schedule/2026-03-07/")
  })
})
