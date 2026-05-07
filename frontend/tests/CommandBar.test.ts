// CommandBar tests after the feature-0007 rewrite. The component is now
// the bottom-dock chat surface backed by `useChat`; the previous
// single-shot `useAI` consumer has been retired.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount, VueWrapper } from "@vue/test-utils"
import { nextTick, ref } from "vue"

const setActiveDate = vi.fn()
const clearThread = vi.fn()
const submitTurn = vi.fn()
const isProcessing = ref(false)
const lastError = ref<string | null>(null)
const pendingAsk = ref<string | null>(null)
const apiHealthy = ref(true)
const messages = ref<
  {
    role: "user" | "assistant"
    content: string
    ask: string | null
    explanation: string | null
    ts: number
  }[]
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

import CommandBar from "../src/components/CommandBar.vue"

const BLOCK_A = {
  id: 1,
  title: "A",
  start_time: "09:00",
  end_time: "10:00",
  category: "work" as const,
  is_completed: false,
  sort_order: 0,
}

function makeSnapshot() {
  return [{ ...BLOCK_A }]
}

let wrapper: VueWrapper | null = null

function mountBar(overrides: Record<string, unknown> = {}) {
  wrapper = mount(CommandBar, {
    props: {
      date: "2026-04-18",
      snapshotBlocks: makeSnapshot,
      pushUndo: vi.fn(),
      ...overrides,
    },
    attachTo: document.body,
  })
  return wrapper
}

describe("CommandBar (chat dock)", () => {
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
  })

  it("registers the active date on mount", () => {
    mountBar()
    expect(setActiveDate).toHaveBeenCalledWith("2026-04-18")
  })

  it("submits the turn on Enter without Shift", async () => {
    submitTurn.mockResolvedValue(undefined)
    const pushUndo = vi.fn()
    const w = mountBar({ pushUndo })

    const ta = w.find("textarea.command-input")
    await ta.setValue("add gym")
    await ta.trigger("keydown", { key: "Enter" })
    await nextTick()

    expect(submitTurn).toHaveBeenCalledTimes(1)
    const [text, snap, undo] = submitTurn.mock.calls[0]
    expect(text).toBe("add gym")
    expect(typeof snap).toBe("function")
    expect(undo).toBe(pushUndo)
  })

  it("inserts a newline on Shift+Enter without submitting", async () => {
    const w = mountBar()
    const ta = w.find("textarea.command-input")
    await ta.setValue("hello")
    // Shift+Enter must NOT trigger submit. We simulate the keydown and
    // verify submitTurn was never called; the textarea's textContent
    // newline is the browser's job, not ours.
    await ta.trigger("keydown", { key: "Enter", shiftKey: true })
    expect(submitTurn).not.toHaveBeenCalled()
  })

  it("ignores submit while isProcessing", async () => {
    isProcessing.value = true
    const w = mountBar()
    const ta = w.find("textarea.command-input")
    await ta.setValue("hi")
    await ta.trigger("keydown", { key: "Enter" })
    expect(submitTurn).not.toHaveBeenCalled()
  })

  it("ignores empty / whitespace-only input", async () => {
    const w = mountBar()
    const ta = w.find("textarea.command-input")
    await ta.setValue("   ")
    await ta.trigger("keydown", { key: "Enter" })
    expect(submitTurn).not.toHaveBeenCalled()
  })

  it("focuses the textarea on '/' when focus is outside form fields", async () => {
    const w = mountBar()
    const ta = w.find("textarea.command-input")
      .element as HTMLTextAreaElement
    const focusSpy = vi.spyOn(ta, "focus")

    const evt = new KeyboardEvent("keydown", { key: "/", cancelable: true })
    document.dispatchEvent(evt)
    await nextTick()

    expect(focusSpy).toHaveBeenCalled()
    expect(evt.defaultPrevented).toBe(true)
  })

  it("ignores '/' while typing in another input/textarea", async () => {
    const w = mountBar()
    const ta = w.find("textarea.command-input")
      .element as HTMLTextAreaElement
    const focusSpy = vi.spyOn(ta, "focus")

    const other = document.createElement("textarea")
    document.body.appendChild(other)
    other.focus()
    const evt = new KeyboardEvent("keydown", {
      key: "/",
      cancelable: true,
      bubbles: true,
    })
    other.dispatchEvent(evt)
    await nextTick()

    expect(focusSpy).not.toHaveBeenCalled()
    document.body.removeChild(other)
  })

  it("renders an unhealthy status dot when apiHealthy is false", () => {
    apiHealthy.value = false
    const w = mountBar()
    expect(w.find(".status-dot.unhealthy").exists()).toBe(true)
    expect(w.find(".status-dot.healthy").exists()).toBe(false)
  })

  it("renders the latest few messages above the input", () => {
    messages.value = [
      {
        role: "user",
        content: "hi",
        ask: null,
        explanation: null,
        ts: 1,
      },
      {
        role: "assistant",
        content: "when?",
        ask: "when?",
        explanation: null,
        ts: 2,
      },
    ]
    pendingAsk.value = "when?"
    const w = mountBar()
    const bubbles = w.findAll(".bubble")
    expect(bubbles.length).toBe(2)
    expect(bubbles[0].text()).toBe("hi")
    expect(bubbles[1].text()).toBe("when?")
    // The assistant bubble that matches `pendingAsk` gets the highlight class.
    expect(bubbles[1].classes()).toContain("bubble-ask")
  })

  it("Clear button calls clearThread when the thread has messages", async () => {
    messages.value = [
      {
        role: "user",
        content: "hi",
        ask: null,
        explanation: null,
        ts: 1,
      },
    ]
    const w = mountBar()
    await w.find('[data-testid="chat-clear"]').trigger("click")
    expect(clearThread).toHaveBeenCalledOnce()
  })

  it("Clear button is hidden when the thread is empty", () => {
    const w = mountBar()
    expect(w.find('[data-testid="chat-clear"]').exists()).toBe(false)
  })

  it("disables the textarea when scheduleDisabled is provided as true", () => {
    const w = mount(CommandBar, {
      props: {
        date: "2026-04-18",
        snapshotBlocks: makeSnapshot,
        pushUndo: vi.fn(),
      },
      global: {
        provide: {
          scheduleDisabled: ref(true),
        },
      },
      attachTo: document.body,
    })
    wrapper = w
    const ta = w.find("textarea.command-input")
      .element as HTMLTextAreaElement
    expect(ta.disabled).toBe(true)
  })

  it("renders on all viewports in PR A (no useMediaQuery hide)", () => {
    // PR A keeps the bottom dock visible regardless of viewport width;
    // PR B will introduce the sidebar + flip this assertion.
    const original = window.innerWidth
    Object.defineProperty(window, "innerWidth", {
      configurable: true,
      value: 1440,
    })
    try {
      const w = mountBar()
      expect(w.find('[data-testid="command-bar"]').exists()).toBe(true)
    } finally {
      Object.defineProperty(window, "innerWidth", {
        configurable: true,
        value: original,
      })
    }
  })

  it("clears input and blurs on Escape", async () => {
    const w = mountBar()
    const ta = w.find("textarea.command-input")
    const taEl = ta.element as HTMLTextAreaElement
    await ta.setValue("some text")
    taEl.focus()
    await ta.trigger("keydown", { key: "Escape" })
    expect((taEl as HTMLTextAreaElement).value).toBe("")
  })
})
