import { describe, it, expect, vi, beforeEach, afterEach } from "vitest"
import { mount, VueWrapper } from "@vue/test-utils"
import { ref, nextTick } from "vue"

const submitCommand = vi.fn()
const isProcessing = ref(false)
const lastError = ref<string | null>(null)
const lastExplanation = ref<string | null>(null)
const apiHealthy = ref(true)
const clearError = vi.fn(() => { lastError.value = null })

vi.mock("../src/composables/useAI", () => ({
  useAI: () => ({
    isProcessing, lastError, lastExplanation, apiHealthy,
    submitCommand, clearError,
  }),
}))

import CommandBar from "../src/components/CommandBar.vue"

const BLOCK_A = { id: 1, title: "A", start_time: "09:00", end_time: "10:00", category: "work" as const, is_completed: false, sort_order: 0 }
const BLOCK_B = { id: 2, title: "Standup", start_time: "10:00", end_time: "10:15", category: "work" as const, is_completed: false, sort_order: 1 }

function makeSnapshot() {
  return [{ ...BLOCK_A }]
}

// Track the mounted wrapper so `afterEach` can always tear it down — without
// this the placeholder-rotation `setInterval` in CommandBar.vue keeps ticking
// against a detached DOM, leaking between tests.
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

describe("CommandBar", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    isProcessing.value = false
    lastError.value = null
    lastExplanation.value = null
    apiHealthy.value = true
  })

  afterEach(() => {
    wrapper?.unmount()
    wrapper = null
  })

  it("submits on Enter and pushes undo when blocks changed", async () => {
    // Response includes a new block — schedule changed → undo must be registered.
    submitCommand.mockResolvedValue({
      ok: true,
      explanation: "Added standup",
      data: { blocks: [BLOCK_A, BLOCK_B] },
    })
    const pushUndo = vi.fn()
    const w = mountBar({ pushUndo })

    const input = w.find(".command-input")
    await input.setValue("add standup at 10")
    await w.find("form").trigger("submit")
    await nextTick()

    expect(submitCommand).toHaveBeenCalledWith("2026-04-18", "add standup at 10")
    expect(pushUndo).toHaveBeenCalledOnce()
    const action = pushUndo.mock.calls[0][0]
    expect(action.type).toBe("ai")
    expect(action.description).toBe("Added standup")
    expect(action.scheduleDate).toBe("2026-04-18")
    // Input clears on success.
    expect((input.element as HTMLInputElement).value).toBe("")
  })

  it("does not push undo when AI succeeds but schedule is unchanged (zero actions)", async () => {
    // LLM replied with a clarification — same blocks back, no mutations applied.
    submitCommand.mockResolvedValue({
      ok: true,
      explanation: "Cannot add block at 23:40 — outside working hours.",
      data: { blocks: [BLOCK_A] },
    })
    const pushUndo = vi.fn()
    const w = mountBar({ pushUndo })

    const input = w.find(".command-input")
    await input.setValue("add call at 23:40 for 5 min")
    await w.find("form").trigger("submit")
    await nextTick()

    expect(pushUndo).not.toHaveBeenCalled()
    // Input still clears — the command was handled successfully.
    expect((input.element as HTMLInputElement).value).toBe("")
  })

  it("does not push undo on failure, keeps input contents", async () => {
    submitCommand.mockResolvedValue({ ok: false, errors: { detail: "nope" } })
    const pushUndo = vi.fn()
    const w = mountBar({ pushUndo })

    const input = w.find(".command-input")
    await input.setValue("bad command")
    await w.find("form").trigger("submit")
    await nextTick()

    expect(pushUndo).not.toHaveBeenCalled()
    expect((input.element as HTMLInputElement).value).toBe("bad command")
  })

  it("ignores submit while isProcessing", async () => {
    isProcessing.value = true
    const w = mountBar()
    await w.find(".command-input").setValue("hi")
    await w.find("form").trigger("submit")
    expect(submitCommand).not.toHaveBeenCalled()
  })

  it("ignores empty / whitespace-only commands", async () => {
    const w = mountBar()
    await w.find(".command-input").setValue("   ")
    await w.find("form").trigger("submit")
    expect(submitCommand).not.toHaveBeenCalled()
  })

  it("takes snapshot via the prop (DataCloneError regression guard)", async () => {
    submitCommand.mockResolvedValue({
      ok: true,
      explanation: "ok",
      data: { blocks: [BLOCK_A, BLOCK_B] },
    })
    const snapshotBlocks = vi.fn(makeSnapshot)
    const w = mountBar({ snapshotBlocks })
    await w.find(".command-input").setValue("hi")
    await w.find("form").trigger("submit")
    await nextTick()
    expect(snapshotBlocks).toHaveBeenCalledOnce()
  })

  it("focuses the input when '/' is pressed outside an editable field", async () => {
    const w = mountBar()
    const inputEl = w.find(".command-input").element as HTMLInputElement
    const focusSpy = vi.spyOn(inputEl, "focus")

    const evt = new KeyboardEvent("keydown", { key: "/", cancelable: true })
    document.dispatchEvent(evt)
    await nextTick()

    expect(focusSpy).toHaveBeenCalled()
    expect(evt.defaultPrevented).toBe(true)
  })

  it("ignores '/' while typing in another input", async () => {
    const w = mountBar()
    const inputEl = w.find(".command-input").element as HTMLInputElement
    const focusSpy = vi.spyOn(inputEl, "focus")

    const other = document.createElement("input")
    document.body.appendChild(other)
    other.focus()
    const evt = new KeyboardEvent("keydown", { key: "/", cancelable: true, bubbles: true })
    other.dispatchEvent(evt)
    await nextTick()

    expect(focusSpy).not.toHaveBeenCalled()
    document.body.removeChild(other)
  })

  it("renders red status dot when apiHealthy is false", () => {
    apiHealthy.value = false
    const w = mountBar()
    expect(w.find(".status-dot.unhealthy").exists()).toBe(true)
    expect(w.find(".status-dot.healthy").exists()).toBe(false)
  })

  it("clears the error when the user edits the input", async () => {
    lastError.value = "stale error"
    const w = mountBar()
    expect(w.find(".error-row").exists()).toBe(true)
    await w.find(".command-input").setValue("n")
    expect(clearError).toHaveBeenCalled()
    // clearError mock nulls lastError, so the error-row disappears.
    await nextTick()
    expect(w.find(".error-row").exists()).toBe(false)
  })

  it("clears input and error when Escape is pressed", async () => {
    lastError.value = "bad"
    const w = mountBar()
    const input = w.find(".command-input")
    await input.setValue("some text")
    await input.trigger("keydown", { key: "Escape" })
    expect((input.element as HTMLInputElement).value).toBe("")
    expect(clearError).toHaveBeenCalled()
  })
})
