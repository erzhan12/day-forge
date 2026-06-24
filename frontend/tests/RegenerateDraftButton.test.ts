import { beforeEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import { ref } from "vue"

const isProcessing = ref(false)
const apiHealthy = ref(true)
const isGeneratingDraft = ref(false)

vi.mock("../src/composables/useChat", () => ({
  useChat: () => ({
    isProcessing,
    apiHealthy,
  }),
}))

vi.mock("../src/composables/useDraft", () => ({
  useDraft: () => ({
    isGeneratingDraft,
  }),
}))

import RegenerateDraftButton from "../src/components/RegenerateDraftButton.vue"

describe("RegenerateDraftButton", () => {
  beforeEach(() => {
    isProcessing.value = false
    apiHealthy.value = true
    isGeneratingDraft.value = false
  })

  function mountButton() {
    return mount(RegenerateDraftButton, {
      props: { hasTemplate: true, slotType: "weekday" },
    })
  }

  it("disables while chat is processing", () => {
    isProcessing.value = true
    const wrapper = mountButton()
    expect(wrapper.find(".regen-btn").attributes("disabled")).toBeDefined()
  })

  it("disables when chat reports AI unhealthy", () => {
    apiHealthy.value = false
    const wrapper = mountButton()
    expect(wrapper.find(".regen-btn").attributes("disabled")).toBeDefined()
  })

  it("emits click when enabled", async () => {
    const wrapper = mountButton()
    await wrapper.find(".regen-btn").trigger("click")
    expect(wrapper.emitted("click")).toHaveLength(1)
  })

  it("does not emit click while chat is processing", async () => {
    isProcessing.value = true
    const wrapper = mountButton()
    await wrapper.find(".regen-btn").trigger("click")
    expect(wrapper.emitted("click")).toBeUndefined()
  })
})
