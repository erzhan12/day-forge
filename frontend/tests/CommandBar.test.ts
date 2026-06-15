// CommandBar tests after the feature-0007 rewrite. The component is now
// the bottom-dock chat surface backed by `useChat`; the previous
// single-shot `useAI` consumer has been retired.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { mount, VueWrapper } from "@vue/test-utils"
import { nextTick, ref } from "vue"
import { clearLocalStorage } from "./helpers/storage"

const setActiveDate = vi.fn()
const clearThread = vi.fn()
const submitTurn = vi.fn()
const isProcessing = ref(false)
const lastError = ref<string | null>(null)
const pendingAsk = ref<string | null>(null)
const apiHealthy = ref(true)
const draftInput = ref("")
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
    draftInput,
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
      variant: "dock" as const,
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
    draftInput.value = ""
    messages.value = []
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
    clearLocalStorage()
    vi.unstubAllGlobals()
    vi.clearAllMocks()
  })

  it("registers the active date on mount", () => {
    mountBar()
    expect(setActiveDate).toHaveBeenCalledWith("2026-04-18")
  })

  describe("placeholder rotation", () => {
    const PLACEHOLDER_ROTATION_MS = 6_000
    const PLACEHOLDER_0 = "tell me about your day…"
    const PLACEHOLDER_1 = "опиши свой день — я задам уточняющие вопросы"
    const PLACEHOLDER_2 = "add standup at 10:00 for 15 min"

    function textareaPlaceholder(w: VueWrapper): string {
      const ph = (w.find("textarea.command-input").element as HTMLTextAreaElement)
        .placeholder
      return ph.split(" (press / to focus")[0]
    }

    beforeEach(() => {
      vi.useFakeTimers()
      vi.spyOn(document, "hasFocus").mockReturnValue(true)
      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        value: "visible",
      })
    })

    afterEach(() => {
      vi.useRealTimers()
    })

    it("rotates placeholder while the tab is focused", async () => {
      const w = mountBar()
      expect(textareaPlaceholder(w)).toBe(PLACEHOLDER_0)
      vi.advanceTimersByTime(PLACEHOLDER_ROTATION_MS)
      await nextTick()
      expect(textareaPlaceholder(w)).toBe(PLACEHOLDER_1)
    })

    it("pauses rotation when the tab is hidden and resumes when visible", async () => {
      const w = mountBar()
      vi.advanceTimersByTime(PLACEHOLDER_ROTATION_MS)
      await nextTick()
      expect(textareaPlaceholder(w)).toBe(PLACEHOLDER_1)

      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        value: "hidden",
      })
      document.dispatchEvent(new Event("visibilitychange"))
      vi.advanceTimersByTime(PLACEHOLDER_ROTATION_MS)
      await nextTick()
      expect(textareaPlaceholder(w)).toBe(PLACEHOLDER_1)

      Object.defineProperty(document, "visibilityState", {
        configurable: true,
        value: "visible",
      })
      document.dispatchEvent(new Event("visibilitychange"))
      vi.advanceTimersByTime(PLACEHOLDER_ROTATION_MS)
      await nextTick()
      expect(textareaPlaceholder(w)).toBe(PLACEHOLDER_2)
    })

    it("pauses rotation when the window blurs and resumes on focus", async () => {
      const w = mountBar()
      vi.advanceTimersByTime(PLACEHOLDER_ROTATION_MS)
      await nextTick()
      expect(textareaPlaceholder(w)).toBe(PLACEHOLDER_1)

      vi.mocked(document.hasFocus).mockReturnValue(false)
      window.dispatchEvent(new Event("blur"))
      vi.advanceTimersByTime(PLACEHOLDER_ROTATION_MS)
      await nextTick()
      expect(textareaPlaceholder(w)).toBe(PLACEHOLDER_1)

      vi.mocked(document.hasFocus).mockReturnValue(true)
      window.dispatchEvent(new Event("focus"))
      vi.advanceTimersByTime(PLACEHOLDER_ROTATION_MS)
      await nextTick()
      expect(textareaPlaceholder(w)).toBe(PLACEHOLDER_2)
    })

    it("stops rotation and removes all listeners after unmount", async () => {
      const w = mountBar()
      vi.advanceTimersByTime(PLACEHOLDER_ROTATION_MS)
      await nextTick()
      expect(textareaPlaceholder(w)).toBe(PLACEHOLDER_1)

      w.unmount()
      wrapper = null

      expect(vi.getTimerCount()).toBe(0)
      expect(() => {
        document.dispatchEvent(new Event("visibilitychange"))
        window.dispatchEvent(new Event("focus"))
        window.dispatchEvent(new Event("blur"))
      }).not.toThrow()
    })

    it("only one timer runs when focus/blur events fire rapidly", async () => {
      mountBar()
      // fire events rapidly without advancing time; set hasFocus BEFORE each
      // event so the synchronous handler sees the correct state (mirrors browser)
      vi.mocked(document.hasFocus).mockReturnValue(false)
      window.dispatchEvent(new Event("blur"))
      vi.mocked(document.hasFocus).mockReturnValue(true)
      window.dispatchEvent(new Event("focus"))
      window.dispatchEvent(new Event("focus"))
      document.dispatchEvent(new Event("visibilitychange"))

      expect(vi.getTimerCount()).toBe(1)

      vi.advanceTimersByTime(PLACEHOLDER_ROTATION_MS)
      await nextTick()
      expect(textareaPlaceholder(wrapper!)).toBe(PLACEHOLDER_1)
    })
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
        variant: "dock" as const,
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

  it("clears input and blurs on Escape", async () => {
    const w = mountBar()
    const ta = w.find("textarea.command-input")
    const taEl = ta.element as HTMLTextAreaElement
    await ta.setValue("some text")
    taEl.focus()
    await ta.trigger("keydown", { key: "Escape" })
    expect((taEl as HTMLTextAreaElement).value).toBe("")
  })

  it("preserves an unsent draft across CommandBar remounts", async () => {
    const w = mountBar({ variant: "sidebar" as const })
    await w.find("textarea.command-input").setValue("schedule review prep")

    w.unmount()
    wrapper = null
    const remounted = mountBar({ variant: "sidebar" as const })
    const ta = remounted.find("textarea.command-input")
      .element as HTMLTextAreaElement

    expect(ta.value).toBe("schedule review prep")
  })

  // --- feature 0008: variant-aware behavior --------------------------

  it("variant=dock — root and textarea carry variant-dock class", () => {
    const w = mountBar({ variant: "dock" as const })
    expect(w.find('[data-testid="command-bar"]').classes()).toContain(
      "variant-dock",
    )
    expect(w.find("textarea.command-input").classes()).toContain("variant-dock")
  })

  it("variant=sidebar — root and textarea carry variant-sidebar class", () => {
    const w = mountBar({ variant: "sidebar" as const })
    expect(w.find('[data-testid="command-bar"]').classes()).toContain(
      "variant-sidebar",
    )
    expect(w.find("textarea.command-input").classes()).toContain(
      "variant-sidebar",
    )
  })

  it("variant=dock — textarea starts with rows=1 attribute", () => {
    const w = mountBar({ variant: "dock" as const })
    const ta = w.find("textarea.command-input")
      .element as HTMLTextAreaElement
    expect(ta.rows).toBe(1)
  })

  it("variant=sidebar — textarea starts with rows=6 attribute (Phase 2.2 first-paint contract)", () => {
    const w = mountBar({ variant: "sidebar" as const })
    const ta = w.find("textarea.command-input")
      .element as HTMLTextAreaElement
    expect(ta.rows).toBe(6)
  })

  it("variant=dock caps visible messages at 4 (latest only)", () => {
    messages.value = Array.from({ length: 6 }, (_, i) => ({
      role: "user" as const,
      content: `m${i + 1}`,
      ask: null,
      explanation: null,
      ts: i + 1,
    }))
    const w = mountBar({ variant: "dock" as const })
    const bubbles = w.findAll(".bubble")
    expect(bubbles.length).toBe(4)
    expect(bubbles[0].text()).toBe("m3")
    expect(bubbles[3].text()).toBe("m6")
  })

  it("variant=sidebar shows all messages (no cap)", () => {
    messages.value = Array.from({ length: 6 }, (_, i) => ({
      role: "user" as const,
      content: `m${i + 1}`,
      ask: null,
      explanation: null,
      ts: i + 1,
    }))
    const w = mountBar({ variant: "sidebar" as const })
    const bubbles = w.findAll(".bubble")
    expect(bubbles.length).toBe(6)
    expect(bubbles[0].text()).toBe("m1")
    expect(bubbles[5].text()).toBe("m6")
  })

  // --- permanent clear-btn regression cases --------------------------
  // Empirically captured during 0008 design review (see plan Phase
  // 5.1) — protection against future "simplifications" that would
  // re-break either the in-flight cancel UX (`ref(false)` should NOT
  // disable) or the draft-generation lockout (`ref(true)` should).

  it("clear button is enabled when scheduleDisabled is ref(false)", () => {
    messages.value = [
      {
        role: "user" as const,
        content: "hi",
        ask: null,
        explanation: null,
        ts: 1,
      },
    ]
    const w = mount(CommandBar, {
      props: {
        date: "2026-04-18",
        snapshotBlocks: makeSnapshot,
        pushUndo: vi.fn(),
        variant: "dock" as const,
      },
      global: { provide: { scheduleDisabled: ref(false) } },
      attachTo: document.body,
    })
    wrapper = w
    const btn = w.find('[data-testid="chat-clear"]')
      .element as HTMLButtonElement
    expect(btn.disabled).toBe(false)
  })

  it("clear button is disabled when scheduleDisabled is ref(true)", () => {
    messages.value = [
      {
        role: "user" as const,
        content: "hi",
        ask: null,
        explanation: null,
        ts: 1,
      },
    ]
    const w = mount(CommandBar, {
      props: {
        date: "2026-04-18",
        snapshotBlocks: makeSnapshot,
        pushUndo: vi.fn(),
        variant: "dock" as const,
      },
      global: { provide: { scheduleDisabled: ref(true) } },
      attachTo: document.body,
    })
    wrapper = w
    const btn = w.find('[data-testid="chat-clear"]')
      .element as HTMLButtonElement
    expect(btn.disabled).toBe(true)
  })
})
