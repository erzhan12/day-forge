// ChatSidebar tests — controlled open state, header/rail toggle,
// a11y attributes, and unmount-via-v-if of CommandBar when collapsed.
// See 0008_PLAN.md Phase 5.2.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount, VueWrapper } from "@vue/test-utils"
import { ref } from "vue"
import { clearLocalStorage } from "./helpers/storage"

const setActiveDate = vi.fn()
const clearThread = vi.fn()
const submitTurn = vi.fn()
const isProcessing = ref(false)
const lastError = ref<string | null>(null)
const pendingAsk = ref<string | null>(null)
const apiHealthy = ref(true)
const messages = ref<
  Array<{
    role: "user" | "assistant"
    content: string
    ask: string | null
    explanation: string | null
    ts: number
  }>
>([])

vi.mock("../src/composables/useChat", () => ({
  useChat: () => ({
    messages,
    isProcessing,
    lastError,
    pendingAsk,
    apiHealthy,
    setActiveDate,
    clearThread,
    submitTurn,
  }),
}))

import ChatSidebar from "../src/components/ChatSidebar.vue"

let wrapper: VueWrapper | null = null

beforeEach(() => {
  vi.clearAllMocks()
  isProcessing.value = false
  lastError.value = null
  pendingAsk.value = null
  apiHealthy.value = true
  messages.value = []
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  clearLocalStorage()
  vi.unstubAllGlobals()
  vi.clearAllMocks()
})

function mountSidebar(open: boolean) {
  return mount(ChatSidebar, {
    props: {
      date: "2026-04-18",
      snapshotBlocks: () => [],
      pushUndo: vi.fn(),
      open,
      "onUpdate:open": (v: boolean) => {
        wrapper?.setProps({ open: v })
      },
    },
    attachTo: document.body,
  })
}

describe("ChatSidebar — open state", () => {
  it("names the complementary landmark", () => {
    wrapper = mountSidebar(true)
    expect(wrapper.find('[data-testid="chat-sidebar"]').attributes("aria-label"))
      .toBe("AI chat")
  })

  it("renders CommandBar and #chat-sidebar-body when open", () => {
    wrapper = mountSidebar(true)
    expect(wrapper.find('[data-testid="command-bar"]').exists()).toBe(true)
    expect(wrapper.find("#chat-sidebar-body").exists()).toBe(true)
  })

  it("toggle button has aria-expanded=true and Collapse label when open", () => {
    wrapper = mountSidebar(true)
    const btn = wrapper.find('[data-testid="chat-sidebar-toggle"]')
    expect(btn.attributes("aria-expanded")).toBe("true")
    expect(btn.attributes("aria-label")).toBe("Collapse AI chat panel")
    expect(btn.attributes("type")).toBe("button")
    expect(btn.attributes("aria-controls")).toBe("chat-sidebar-body")
  })
})

describe("ChatSidebar — collapsed state", () => {
  it("does NOT render CommandBar when collapsed", () => {
    wrapper = mountSidebar(false)
    expect(wrapper.find('[data-testid="command-bar"]').exists()).toBe(false)
  })

  it("does NOT render #chat-sidebar-body when collapsed", () => {
    wrapper = mountSidebar(false)
    expect(wrapper.find("#chat-sidebar-body").exists()).toBe(false)
  })

  it("toggle button has aria-expanded=false and Expand label when collapsed", () => {
    wrapper = mountSidebar(false)
    const btn = wrapper.find('[data-testid="chat-sidebar-toggle"]')
    expect(btn.attributes("aria-expanded")).toBe("false")
    expect(btn.attributes("aria-label")).toBe("Expand AI chat panel")
    expect(btn.attributes("type")).toBe("button")
    expect(btn.attributes("aria-controls")).toBe("chat-sidebar-body")
  })
})

describe("ChatSidebar — toggle behavior", () => {
  it("emits update:open with negated value on click (open → false)", async () => {
    wrapper = mountSidebar(true)
    await wrapper.find('[data-testid="chat-sidebar-toggle"]').trigger("click")
    const emitted = wrapper.emitted("update:open")
    expect(emitted).toBeTruthy()
    expect(emitted![0]).toEqual([false])
  })

  it("emits update:open with negated value on click (collapsed → true)", async () => {
    wrapper = mountSidebar(false)
    await wrapper.find('[data-testid="chat-sidebar-toggle"]').trigger("click")
    const emitted = wrapper.emitted("update:open")
    expect(emitted).toBeTruthy()
    expect(emitted![0]).toEqual([true])
  })

  it("does NOT touch localStorage on its own", async () => {
    const getItem = vi.fn(() => null)
    const setItem = vi.fn()
    const original = globalThis.localStorage
    vi.stubGlobal("localStorage", {
      ...original,
      setItem,
      getItem,
    })
    wrapper = mountSidebar(true)
    await wrapper.find('[data-testid="chat-sidebar-toggle"]').trigger("click")
    expect(getItem).not.toHaveBeenCalled()
    expect(setItem).not.toHaveBeenCalled()
  })
})
