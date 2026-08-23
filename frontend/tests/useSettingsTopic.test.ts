import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { defineComponent, h, nextTick } from "vue"
import { mount, type VueWrapper } from "@vue/test-utils"

import { useSettingsTopic } from "../src/composables/useSettingsTopic"

const Harness = defineComponent({
  setup() {
    const topic = useSettingsTopic()
    return () =>
      h("div", [
        h("span", { "data-testid": "active" }, topic.activeTopic.value),
        h(
          "button",
          { onClick: () => topic.setTopic("schedule") },
          "Schedule",
        ),
      ])
  },
})

let wrapper: VueWrapper | null = null

beforeEach(() => {
  window.history.replaceState({}, "", "/settings/")
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.restoreAllMocks()
})

describe("useSettingsTopic", () => {
  it("initializes from the current hash", () => {
    window.history.replaceState({}, "", "/settings/#notifications")
    wrapper = mount(Harness)
    expect(wrapper.get('[data-testid="active"]').text()).toBe("notifications")
  })

  it("setTopic updates the active topic and URL hash synchronously", async () => {
    wrapper = mount(Harness)
    await wrapper.get("button").trigger("click")
    expect(wrapper.get('[data-testid="active"]').text()).toBe("schedule")
    expect(window.location.hash).toBe("#schedule")
  })

  it("reacts to hashchange and falls back for unknown hashes", async () => {
    wrapper = mount(Harness)
    window.history.replaceState({}, "", "/settings/#integrations")
    window.dispatchEvent(new HashChangeEvent("hashchange"))
    await nextTick()
    expect(wrapper.get('[data-testid="active"]').text()).toBe("integrations")

    window.history.replaceState({}, "", "/settings/#unknown")
    window.dispatchEvent(new HashChangeEvent("hashchange"))
    await nextTick()
    expect(wrapper.get('[data-testid="active"]').text()).toBe("appearance")
  })

  it("removes its hashchange listener on unmount", () => {
    const removeSpy = vi.spyOn(window, "removeEventListener")
    wrapper = mount(Harness)
    wrapper.unmount()
    wrapper = null
    expect(removeSpy).toHaveBeenCalledWith("hashchange", expect.any(Function))
  })
})
