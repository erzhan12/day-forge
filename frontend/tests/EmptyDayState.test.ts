import { describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"

vi.mock("@inertiajs/vue3", () => ({
  Link: { name: "Link", props: ["href"], template: '<a :href="href"><slot /></a>' },
}))

import EmptyDayState from "../src/components/EmptyDayState.vue"

describe("EmptyDayState (0106)", () => {
  it("links the primary button to the templates topic", () => {
    const w = mount(EmptyDayState, { props: { date: "2026-11-22", slotType: "weekend" } })
    expect(w.get("h2").text()).toBe("No template for Sunday")
    const link = w.get('[data-testid="empty-day-create-template"]')
    expect(link.attributes("href")).toBe("/settings/#templates-rules")
    expect(link.text()).toBe("Create weekend template")
  })

  it("emits plan-with-ai", async () => {
    const w = mount(EmptyDayState, { props: { date: "2026-11-23", slotType: "weekday" } })
    await w.get('[data-testid="empty-day-plan-with-ai"]').trigger("click")
    expect(w.emitted("plan-with-ai")).toHaveLength(1)
  })
})
