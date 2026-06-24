// RegenerateDraftButton must gate on useChat (not the deprecated useAI)
// so generate-draft cannot race an in-flight AI chat turn on an empty
// draft day.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount, type VueWrapper } from "@vue/test-utils"
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

let wrapper: VueWrapper | null = null

function mountButton(hasTemplate = true) {
  return mount(RegenerateDraftButton, {
    props: {
      hasTemplate,
      slotType: "weekday",
    },
  })
}

describe("RegenerateDraftButton", () => {
  beforeEach(() => {
    isProcessing.value = false
    apiHealthy.value = true
    isGeneratingDraft.value = false
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
  })

  it("is disabled while AI chat is processing", () => {
    isProcessing.value = true
    wrapper = mountButton()
    const btn = wrapper.find("button")
    expect(btn.attributes("disabled")).toBeDefined()
    expect(btn.classes()).toContain("disabled")
  })

  it("does not emit click when disabled due to chat processing", async () => {
    isProcessing.value = true
    wrapper = mountButton()
    await wrapper.find("button").trigger("click")
    expect(wrapper.emitted("click")).toBeUndefined()
  })

  it("emits click when enabled", async () => {
    wrapper = mountButton()
    await wrapper.find("button").trigger("click")
    expect(wrapper.emitted("click")).toHaveLength(1)
  })

  it("is disabled when AI is unhealthy", () => {
    apiHealthy.value = false
    wrapper = mountButton()
    expect(wrapper.find("button").attributes("disabled")).toBeDefined()
  })

  it("is disabled when no template is configured", () => {
    wrapper = mountButton(false)
    expect(wrapper.find("button").attributes("disabled")).toBeDefined()
    expect(wrapper.text()).toContain("No weekday template configured.")
  })
})
