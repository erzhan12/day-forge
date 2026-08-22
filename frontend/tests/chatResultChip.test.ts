import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"

import ChatResultChip from "../src/components/ChatResultChip.vue"
import type { AppliedBlockResult } from "../src/composables/useChat"

const RESULT: AppliedBlockResult[] = [
  {
    title: "Deep work",
    start_time: "09:00",
    end_time: "10:30",
    category: "work",
    change: "changed",
  },
  {
    title: "Gym",
    start_time: "18:00",
    end_time: "19:00",
    category: "health",
    change: "added",
  },
]

describe("ChatResultChip", () => {
  it("renders each applied row as change · start–end · title", () => {
    const wrapper = mount(ChatResultChip, { props: { result: RESULT } })
    expect(wrapper.text()).toContain("Applied")
    expect(wrapper.text()).toContain("changed · 09:00–10:30 · Deep work")
    expect(wrapper.text()).toContain("added · 18:00–19:00 · Gym")
  })

  it("renders no applied markup when result is empty or omitted", () => {
    const empty = mount(ChatResultChip, { props: { result: [] } })
    expect(empty.text()).not.toContain("Applied")
    empty.unmount()

    const omitted = mount(ChatResultChip)
    expect(omitted.text()).not.toContain("Applied")
    omitted.unmount()
  })

  it("renders the three static suggestions and emits the clicked text", async () => {
    const wrapper = mount(ChatResultChip, { props: { showSuggestions: true } })
    const buttons = wrapper.findAll(".suggestions button")
    expect(buttons).toHaveLength(3)
    expect(buttons.map((button) => button.text())).toEqual([
      "Plan my remaining day",
      "Add a focused work block",
      "Make room for a break",
    ])

    await buttons[1].trigger("click")
    expect(wrapper.emitted("suggestion")).toEqual([["Add a focused work block"]])
  })
})
