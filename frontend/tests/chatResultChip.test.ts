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

  it("renders supplied suggestions in order and emits the exact clicked text", async () => {
    const suggestions = ["Move lunch later", "Protect focus time"]
    const wrapper = mount(ChatResultChip, {
      props: { showSuggestions: true, suggestions },
    })
    const buttons = wrapper.findAll(".suggestions button")
    expect(buttons.map((button) => button.text())).toEqual(suggestions)

    await buttons[1].trigger("click")
    expect(wrapper.emitted("suggestion")).toEqual([["Protect focus time"]])
  })

  it("renders duplicate suggestions as independent clickable buttons", async () => {
    const wrapper = mount(ChatResultChip, {
      props: { showSuggestions: true, suggestions: ["same", "same"] },
    })
    const buttons = wrapper.findAll(".suggestions button")
    expect(buttons).toHaveLength(2)

    await buttons[0].trigger("click")
    await buttons[1].trigger("click")
    expect(wrapper.emitted("suggestion")).toEqual([["same"], ["same"]])
  })

  it("renders no suggestion wrapper for an empty supplied list", () => {
    const wrapper = mount(ChatResultChip, {
      props: { showSuggestions: true, suggestions: [] },
    })
    expect(wrapper.find('[data-testid="chat-result-chip"]').exists()).toBe(false)
  })
})
