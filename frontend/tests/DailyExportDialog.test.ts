import { afterEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import DailyExportDialog from "../src/components/DailyExportDialog.vue"

const BLOCKS = [
  {
    title: "Gym",
    start_time: "09:00",
    end_time: "10:00",
    category: "health",
    is_completed: false,
    sort_order: 0,
  },
]

function mountDialog() {
  return mount(DailyExportDialog, { props: { date: "2026-08-29", blocks: BLOCKS } })
}

afterEach(() => {
  vi.useRealTimers()
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
})

describe("DailyExportDialog", () => {
  it("seeds an editable preview from the supplied date and blocks", () => {
    const wrapper = mountDialog()
    expect((wrapper.find(".daily-export-preview").element as HTMLTextAreaElement).value).toBe(
      "## day-forge · 2026-08-29\n\nblocks: 0/1 done\n\n- [ ] 09:00 Gym (health) 1h",
    )
  })

  it("regenerates each pristine note change from the latest generated snapshot", async () => {
    const wrapper = mountDialog()
    const note = wrapper.find(".daily-export-note")
    await note.setValue("first note")
    expect(wrapper.find(".daily-export-preview").element.value).toContain("note: first note")
    await note.setValue("second note")
    expect(wrapper.find(".daily-export-preview").element.value).toContain("note: second note")
  })

  it("preserves a manual preview edit through later note changes", async () => {
    const wrapper = mountDialog()
    const preview = wrapper.find(".daily-export-preview")
    await preview.setValue("manually edited markdown")
    await wrapper.find(".daily-export-note").setValue("should not overwrite")
    expect(preview.element.value).toBe("manually edited markdown")
  })

  it("does not clear dirty state when a manual edit happens to equal a generated snapshot", async () => {
    const wrapper = mountDialog()
    const preview = wrapper.find(".daily-export-preview")
    const original = (preview.element as HTMLTextAreaElement).value
    await preview.setValue("manual")
    await preview.setValue(original)
    await wrapper.find(".daily-export-note").setValue("later")
    expect(preview.element.value).toBe(original)
  })

  it("copies the current editable textarea content and shows transient feedback", async () => {
    vi.useFakeTimers()
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } })
    const wrapper = mountDialog()
    await wrapper.find(".daily-export-preview").setValue("edited export")
    await wrapper.find(".daily-export-copy").trigger("click")
    await vi.runAllTicks()
    expect(writeText).toHaveBeenCalledWith("edited export")
    expect(wrapper.text()).toContain("Copied")
    vi.advanceTimersByTime(2000)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).not.toContain("Copied")
  })

  it("falls back to textarea selection when clipboard rejects or is absent", async () => {
    const wrapper = mountDialog()
    const textarea = wrapper.find(".daily-export-preview").element as HTMLTextAreaElement
    const focus = vi.spyOn(textarea, "focus")
    const select = vi.spyOn(textarea, "select")
    await wrapper.find(".daily-export-copy").trigger("click")
    await Promise.resolve()
    expect(focus).toHaveBeenCalled()
    expect(select).toHaveBeenCalled()
    expect(wrapper.text()).toContain("Copy manually")
  })

  it("uses the same fallback for a rejected clipboard promise", async () => {
    const writeText = vi.fn().mockRejectedValue(new Error("denied"))
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } })
    const wrapper = mountDialog()
    const textarea = wrapper.find(".daily-export-preview").element as HTMLTextAreaElement
    const focus = vi.spyOn(textarea, "focus")
    const select = vi.spyOn(textarea, "select")
    await wrapper.find(".daily-export-copy").trigger("click")
    await Promise.resolve()
    expect(focus).toHaveBeenCalled()
    expect(select).toHaveBeenCalled()
    expect(wrapper.text()).toContain("Copy manually")
  })

  it("does not run the feedback path after unmount while a clipboard write is pending", async () => {
    let resolveWrite: (() => void) | undefined
    const writeText = vi.fn().mockImplementation(
      () => new Promise<void>((resolve) => { resolveWrite = resolve }),
    )
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } })
    // Spy setTimeout: the success path (showFeedback) is the only caller, so a live
    // is-mounted guard means resolving the write AFTER unmount arms no new timer.
    const setTimeoutSpy = vi.spyOn(globalThis, "setTimeout")
    const wrapper = mountDialog()
    await wrapper.find(".daily-export-copy").trigger("click")
    wrapper.unmount()
    const callsBeforeResolve = setTimeoutSpy.mock.calls.length
    resolveWrite?.()
    await Promise.resolve()
    // Guard removed → showFeedback runs post-unmount → setTimeout called again.
    expect(setTimeoutSpy.mock.calls.length).toBe(callsBeforeResolve)
    setTimeoutSpy.mockRestore()
  })

  it("clears the armed feedback timer on unmount", async () => {
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } })
    const clearTimeoutSpy = vi.spyOn(globalThis, "clearTimeout")
    const wrapper = mountDialog()
    await wrapper.find(".daily-export-copy").trigger("click")
    await Promise.resolve() // resolve write → showFeedback arms the 2s timer
    expect(wrapper.text()).toContain("Copied")
    const callsBeforeUnmount = clearTimeoutSpy.mock.calls.length
    wrapper.unmount()
    // onUnmounted must clearTimeout the armed feedback timer (no post-unmount leak).
    expect(clearTimeoutSpy.mock.calls.length).toBeGreaterThan(callsBeforeUnmount)
    clearTimeoutSpy.mockRestore()
  })

  it("replaces a stale copy feedback timer on a second copy", async () => {
    vi.useFakeTimers()
    const writeText = vi.fn().mockResolvedValue(undefined)
    vi.stubGlobal("navigator", { ...navigator, clipboard: { writeText } })
    const wrapper = mountDialog()
    await wrapper.find(".daily-export-copy").trigger("click")
    await vi.runAllTicks()
    vi.advanceTimersByTime(1500)
    await wrapper.find(".daily-export-copy").trigger("click")
    await vi.runAllTicks()
    vi.advanceTimersByTime(600)
    await wrapper.vm.$nextTick()
    expect(wrapper.text()).toContain("Copied")
  })

  it("starts clean again when the dialog is remounted", async () => {
    const first = mountDialog()
    await first.find(".daily-export-note").setValue("temporary note")
    first.unmount()
    const second = mountDialog()
    expect((second.find(".daily-export-note").element as HTMLInputElement).value).toBe("")
    expect(second.find(".daily-export-preview").element.value).not.toContain("temporary note")
  })

  it("emits close from its button and backdrop but not inside the dialog", async () => {
    const wrapper = mountDialog()
    expect(wrapper.find('[role="dialog"]').attributes("aria-modal")).toBe("true")
    expect(wrapper.find('[role="dialog"]').attributes("aria-label")).toBeTruthy()
    await wrapper.find('[role="dialog"]').trigger("click")
    expect(wrapper.emitted("close")).toBeUndefined()
    await wrapper.find(".daily-export-close").trigger("click")
    expect(wrapper.emitted("close")).toHaveLength(1)
    await wrapper.find(".daily-export-backdrop").trigger("click")
    expect(wrapper.emitted("close")).toHaveLength(2)
  })
})
