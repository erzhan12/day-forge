import { ScheduleUndoKey, ScheduleDragKey, ScheduleContainerKey, ScheduleDisabledKey } from "../src/composables/scheduleContext"
import { describe, it, expect, vi, beforeEach, beforeAll, afterAll, afterEach } from "vitest"
import { flushPromises, mount, enableAutoUnmount } from "@vue/test-utils"
import { ref } from "vue"
import { acceptedMutation } from "./helpers/mutation"

// Mock useSchedule
const mockUpdateBlock = vi.fn()
const mockDeleteBlock = vi.fn()
vi.mock("../src/composables/useSchedule", () => ({
  useSchedule: () => ({
    updateBlock: mockUpdateBlock,
    deleteBlock: mockDeleteBlock,
  }),
}))

// TimeBlock now uses useActiveTheme, which reads usePage().props.
// Default to Classic for the existing tests; the dedicated theme
// reactivity test file exercises the reactive path explicitly.
vi.mock("@inertiajs/vue3", () => ({
  usePage: () => ({ props: { ui_preferences: { theme: "classic" } } }),
}))

import DeleteBlockDialog from "../src/components/DeleteConfirmationDialog.vue"
import TimeBlock from "../src/components/TimeBlock.vue"
import type { TimeBlock as TimeBlockType } from "../src/types"

enableAutoUnmount(afterEach)

// jsdom does not implement native dialog methods or browser focus behavior.
// Focus containment, Escape, and focus restoration are checked in the browser.
beforeAll(() => {
  HTMLDialogElement.prototype.showModal = function () { this.open = true }
  HTMLDialogElement.prototype.close = function () { this.open = false }
})
afterAll(() => {
  Reflect.deleteProperty(HTMLDialogElement.prototype, "showModal")
  Reflect.deleteProperty(HTMLDialogElement.prototype, "close")
})

function makeBlock(overrides: Partial<TimeBlockType> = {}): TimeBlockType {
  return {
    id: 1,
    title: "Test Block",
    start_time: "09:00",
    end_time: "10:00",
    category: "work",
    is_completed: false,
    sort_order: 0,
    ...overrides,
  }
}

const mockPushUndo = vi.fn()

function mountWithProvide(props: {
  block: TimeBlockType
  date: string
  isCurrent?: boolean
  remainingMinutes?: number | null
}) {
  return mount(TimeBlock, {
    props,
    global: {
      stubs: { teleport: true },
      provide: {
        [ScheduleUndoKey]: { pushUndo: mockPushUndo },
        [ScheduleDragKey]: {
          startDrag: vi.fn(),
          isDragging: ref(false),
          dragBlockId: ref(null),
          shiftedBlockIds: ref(new Set()),
        },
        [ScheduleContainerKey]: ref(null),
      },
    },
  })
}

describe("TimeBlock", () => {
  beforeEach(() => {
    vi.clearAllMocks()
    mockUpdateBlock.mockReset()
    mockDeleteBlock.mockReset()
  })

  it("renders block title and times", () => {
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    expect(wrapper.text()).toContain("Test Block")
    expect(wrapper.text()).toContain("09:00")
    expect(wrapper.text()).toContain("10:00")
  })

  it("computes duration correctly", () => {
    const wrapper = mountWithProvide({ block: makeBlock({ start_time: "09:00", end_time: "10:30" }), date: "2026-04-10" })
    expect(wrapper.text()).toContain("1h 30m")
  })

  it("formats whole-hour durations without trailing minutes", () => {
    const oneHour = mountWithProvide({
      block: makeBlock({ start_time: "09:00", end_time: "10:00" }),
      date: "2026-04-10",
    })
    expect(oneHour.find(".duration").text()).toBe("1h")

    const twoHours = mountWithProvide({
      block: makeBlock({ start_time: "09:00", end_time: "11:00" }),
      date: "2026-04-10",
    })
    expect(twoHours.find(".duration").text()).toBe("2h")
  })

  it("keeps compact 30-minute blocks in compact layout", () => {
    const wrapper = mountWithProvide({
      block: makeBlock({ start_time: "09:00", end_time: "09:30" }),
      date: "2026-04-10",
    })
    expect(wrapper.find(".time-block").classes()).toContain("compact")
    expect(wrapper.find(".duration").exists()).toBe(false)
  })

  it("shows remaining time on an active compact block", () => {
    const wrapper = mountWithProvide({
      block: makeBlock({ start_time: "09:00", end_time: "09:30" }),
      date: "2026-04-10",
      isCurrent: true,
      remainingMinutes: 23,
    })

    expect(wrapper.find(".remaining-badge").text()).toBe("23m left")
  })

  it("shows remaining time on an active expanded block while preserving total duration", () => {
    const wrapper = mountWithProvide({
      block: makeBlock({ start_time: "09:00", end_time: "10:30" }),
      date: "2026-04-10",
      isCurrent: true,
      remainingMinutes: 60,
    })

    expect(wrapper.find(".duration").text()).toBe("1h 30m")
    expect(wrapper.find(".remaining-badge").text()).toBe("1h left")
  })

  it("omits remaining time for inactive blocks", () => {
    const wrapper = mountWithProvide({
      block: makeBlock(),
      date: "2026-04-10",
      isCurrent: false,
      remainingMinutes: 23,
    })

    expect(wrapper.find(".remaining-badge").exists()).toBe(false)
  })

  it("toggles completion on checkbox change", async () => {
    mockUpdateBlock.mockResolvedValue(acceptedMutation([makeBlock()]))
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    expect(mockUpdateBlock).toHaveBeenCalledWith(
      1,
      { is_completed: true },
      { scheduleDate: "2026-04-10" },
    )
  })

  it("checkbox flips immediately on click before PATCH resolves", async () => {
    let resolveUpdate: (v: { ok: boolean }) => void = () => {}
    mockUpdateBlock.mockReturnValueOnce(
      new Promise<{ ok: boolean }>((res) => {
        resolveUpdate = res
      }),
    )
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    // Optimistic: checkbox reflects the new value before the PATCH resolves,
    // and shows the saving state while the request is in flight.
    expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.find(".time-block").classes()).toContain("completed")
    expect(wrapper.find(".checkbox").classes()).toContain("saving")
    resolveUpdate(acceptedMutation([makeBlock()]))
    await flushPromises()
    expect(mockPushUndo).toHaveBeenCalledTimes(1)
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "toggle", silent: true }),
    )
    expect(wrapper.text()).not.toContain("Failed to update")
  })

  it.each([400, 403, 404, 409, 500, undefined])("reverts on status %s after one attempt", async (status) => {
    mockUpdateBlock.mockResolvedValue({ ok: false, status })
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    await flushPromises()
    expect(mockUpdateBlock).toHaveBeenCalledOnce()
    expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.text()).toContain("Failed to update")
    expect(mockPushUndo).not.toHaveBeenCalled()
  })

  it("serializes rapid checkbox clicks and retains the latest optimistic value", async () => {
    let resolveFirst!: (value: ReturnType<typeof acceptedMutation>) => void
    mockUpdateBlock.mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve }))
      .mockResolvedValueOnce(acceptedMutation([makeBlock({ is_completed: true })], "2026-04-10", 4))
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    await wrapper.find(".checkbox").trigger("change")
    expect(mockUpdateBlock).toHaveBeenCalledOnce()
    expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(false)
    resolveFirst(acceptedMutation([makeBlock()]))
    await flushPromises()
    expect(mockUpdateBlock).toHaveBeenCalledTimes(2)
    expect(mockPushUndo).toHaveBeenCalledTimes(2)
    expect(mockPushUndo.mock.calls[1][0]).toMatchObject({ description: 'Unchecked "Test Block"', expected_revision: 5 })
    expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.find(".checkbox").classes()).not.toContain("saving")
  })

  it("cancels a queued toggle after conflict and shows the reconciled block", async () => {
    let resolveFirst!: (value: { ok: boolean; status: number }) => void
    mockUpdateBlock.mockReturnValueOnce(new Promise((resolve) => { resolveFirst = resolve }))
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    await wrapper.find(".checkbox").trigger("change")
    // Reconciliation reports the completion changed by another writer.
    await wrapper.setProps({ block: makeBlock({ is_completed: true }) })
    resolveFirst({ ok: false, status: 409 })
    await flushPromises()
    expect(mockUpdateBlock).toHaveBeenCalledOnce()
    expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(true)
    expect(wrapper.text()).toContain("Failed to update")
    expect(wrapper.find(".checkbox").classes()).not.toContain("saving")
  })

  it("retains confirmed mutation history when a row unmounts during its request", async () => {
    let resolveWrite!: (value: ReturnType<typeof acceptedMutation>) => void
    mockUpdateBlock.mockReturnValueOnce(new Promise((resolve) => { resolveWrite = resolve }))
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    wrapper.unmount()
    resolveWrite(acceptedMutation([makeBlock()]))
    await flushPromises()
    expect(mockPushUndo).toHaveBeenCalledOnce()
  })

  it("resets reused row UI without aborting an accepted write", async () => {
    let resolveWrite!: (value: ReturnType<typeof acceptedMutation>) => void
    mockUpdateBlock.mockReturnValueOnce(new Promise((resolve) => { resolveWrite = resolve }))
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    await wrapper.setProps({ block: makeBlock({ id: 99 }) })
    expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(false)
    expect(wrapper.find(".checkbox").classes()).not.toContain("saving")
    resolveWrite(acceptedMutation([makeBlock()]))
    await flushPromises()
    expect(mockUpdateBlock).toHaveBeenCalledOnce()
    expect(mockUpdateBlock.mock.calls[0][2]).not.toHaveProperty("signal")
    expect(mockPushUndo).toHaveBeenCalledOnce()
    expect(wrapper.text()).not.toContain("Failed to update")
  })

  it("clears an earlier error when a later explicit toggle succeeds", async () => {
    mockUpdateBlock.mockResolvedValueOnce({ ok: false }).mockResolvedValueOnce(acceptedMutation([makeBlock()]))
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    await flushPromises()
    expect(wrapper.text()).toContain("Failed to update")
    await wrapper.find(".checkbox").trigger("change")
    await flushPromises()
    expect(wrapper.text()).not.toContain("Failed to update")
  })

  it("does not clobber a newer optimistic value when an older reload lands mid-flight", async () => {
    // With a chain in flight (saving), an older chain's success reload can flip
    // props.block.is_completed. The saving-guarded watcher must keep the newer
    // optimistic value rather than snapping the checkbox to the stale prop.
    mockUpdateBlock.mockReturnValue(new Promise<{ ok: boolean }>(() => {}))
    const wrapper = mountWithProvide({
      block: makeBlock({ id: 1, is_completed: false }),
      date: "2026-04-10",
    })
    await wrapper.find(".checkbox").trigger("change") // optimistic check, chain 1 pending
    await wrapper.find(".checkbox").trigger("change") // optimistic uncheck, chain 2 pending (saving)
    expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(false)
    // Older chain's reload flips the prop true mid-flight (same block id).
    await wrapper.setProps({ block: makeBlock({ id: 1, is_completed: true }) })
    // Guard preserves the newer optimistic uncheck.
    expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(false)
  })

  it("disables the checkbox while the schedule is disabled", async () => {
    // scheduleDisabled (provided by Schedule.vue during AI processing) must
    // natively disable the checkbox — otherwise a click flips the native
    // control with no reactive change, re-creating the desync it guards against.
    const wrapper = mount(TimeBlock, {
      props: { block: makeBlock(), date: "2026-04-10" },
      global: {
        provide: {
          [ScheduleUndoKey]: { pushUndo: mockPushUndo },
          [ScheduleDragKey]: {
            startDrag: vi.fn(),
            isDragging: ref(false),
            dragBlockId: ref(null),
            shiftedBlockIds: ref(new Set()),
          },
          [ScheduleContainerKey]: ref(null),
          [ScheduleDisabledKey]: ref(true),
        },
      },
    })
    expect((wrapper.find(".checkbox").element as HTMLInputElement).disabled).toBe(true)
    await wrapper.find(".checkbox").trigger("change")
    expect(mockUpdateBlock).not.toHaveBeenCalled()
  })

  it("disables the compact-layout checkbox while the schedule is disabled", async () => {
    // The compact (<=30m) branch renders a separate <input>; assert it also
    // carries the native disabled state (both branches bind :disabled="disabled").
    const wrapper = mount(TimeBlock, {
      props: {
        block: makeBlock({ start_time: "09:00", end_time: "09:25" }),
        date: "2026-04-10",
      },
      global: {
        provide: {
          [ScheduleUndoKey]: { pushUndo: mockPushUndo },
          [ScheduleDragKey]: {
            startDrag: vi.fn(),
            isDragging: ref(false),
            dragBlockId: ref(null),
            shiftedBlockIds: ref(new Set()),
          },
          [ScheduleContainerKey]: ref(null),
          [ScheduleDisabledKey]: ref(true),
        },
      },
    })
    expect(wrapper.find(".time-block").classes()).toContain("compact")
    expect((wrapper.find(".checkbox").element as HTMLInputElement).disabled).toBe(true)
    await wrapper.find(".checkbox").trigger("change")
    expect(mockUpdateBlock).not.toHaveBeenCalled()
  })

  it("settles a rejected response without retrying or leaving the spinner", async () => {
    mockUpdateBlock.mockRejectedValue(new TypeError("network died mid-body"))
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    await flushPromises()
    expect(mockUpdateBlock).toHaveBeenCalledOnce()
    expect(wrapper.find(".checkbox").classes()).not.toContain("saving")
    expect(wrapper.text()).toContain("Failed to update")
  })

  it("toggles completion on the compact-layout checkbox", async () => {
    // The compact (<=30m) and expanded branches render separate <input>s;
    // exercise the compact one so a regression in either branch is caught.
    mockUpdateBlock.mockResolvedValue(acceptedMutation([makeBlock()]))
    const wrapper = mountWithProvide({
      block: makeBlock({ start_time: "09:00", end_time: "09:30" }),
      date: "2026-04-10",
    })
    expect(wrapper.find(".time-block").classes()).toContain("compact")
    await wrapper.find(".checkbox").trigger("change")
    expect(mockUpdateBlock).toHaveBeenCalledWith(
      1,
      { is_completed: true },
      { scheduleDate: "2026-04-10" },
    )
    await flushPromises()
    expect((wrapper.find(".checkbox").element as HTMLInputElement).checked).toBe(true)
  })

  it("enters edit mode on title click", async () => {
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    expect(wrapper.find(".title-input").exists()).toBe(false)
    await wrapper.find(".title").trigger("click")
    expect(wrapper.find(".title-input").exists()).toBe(true)
    expect((wrapper.find(".title-input").element as HTMLInputElement).value).toBe("Test Block")
  })

  it("saves title on enter and exits edit mode", async () => {
    mockUpdateBlock.mockResolvedValue(acceptedMutation([makeBlock()]))
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".title").trigger("click")
    const input = wrapper.find(".title-input")
    await input.setValue("New Title")
    await input.trigger("keydown.enter")
    expect(mockUpdateBlock).toHaveBeenCalledWith(1, { title: "New Title" })
  })

  it("does not double-save when blur fires after enter", async () => {
    // Regression for the ``@keydown.enter`` + ``@blur`` race. Both
    // bind to ``saveTitle``. Pressing Enter eventually unmounts the
    // input which fires blur, triggering a second invocation. Without
    // taking ``editing`` down BEFORE the network await, that second
    // call could proceed all the way to a duplicate PATCH + duplicate
    // undo entry.
    //
    // The end-to-end variant of this test lives at
    // frontend/scripts/playwright/timeblock-double-save.mjs — it caught
    // a sibling-bug that this unit test alone missed (a guard that
    // worked for concurrent re-entry but not for sequential re-entry
    // through a finally-cleared flag). Keep both: the unit test pins
    // the contract; the e2e script pins the real-browser timing.
    let resolveFirst: (v: { ok: boolean }) => void = () => {}
    mockUpdateBlock.mockReturnValueOnce(
      new Promise<{ ok: boolean }>((res) => {
        resolveFirst = res
      }),
    )
    const wrapper = mountWithProvide({
      block: makeBlock(),
      date: "2026-04-10",
    })
    await wrapper.find(".title").trigger("click")
    const input = wrapper.find(".title-input")
    await input.setValue("New Title")
    await input.trigger("keydown.enter")
    await input.trigger("blur")
    resolveFirst(acceptedMutation([makeBlock()]))
    await flushPromises()
    expect(mockUpdateBlock).toHaveBeenCalledTimes(1)
    expect(mockPushUndo).toHaveBeenCalledTimes(1)
  })

  it("cancels editing on escape without saving", async () => {
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".title").trigger("click")
    await wrapper.find(".title-input").trigger("keydown.escape")
    expect(wrapper.find(".title-input").exists()).toBe(false)
    expect(mockUpdateBlock).not.toHaveBeenCalled()
  })

  it("does not save if title unchanged", async () => {
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".title").trigger("click")
    await wrapper.find(".title-input").trigger("keydown.enter")
    expect(mockUpdateBlock).not.toHaveBeenCalled()
  })

  it("calls delete after confirm", async () => {
    mockDeleteBlock.mockResolvedValue(acceptedMutation([makeBlock()]))
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".delete-btn").trigger("click")
    expect(mockDeleteBlock).not.toHaveBeenCalled()
    expect(wrapper.find("dialog").text()).toContain("Test Block")
    await wrapper.find(".confirm-delete").trigger("click")
    expect(wrapper.find("dialog").exists()).toBe(false)
    expect(mockDeleteBlock).toHaveBeenCalledWith(1)
  })

  it("does not delete if confirm cancelled", async () => {
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".delete-btn").trigger("click")
    await wrapper.find(".cancel-delete").trigger("click")
    expect(wrapper.find("dialog").exists()).toBe(false)
    expect(mockDeleteBlock).not.toHaveBeenCalled()
  })

  it("cancels deletion on the dialog cancel event (Escape)", async () => {
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".delete-btn").trigger("click")
    await wrapper.find("dialog").trigger("cancel")
    expect(wrapper.find("dialog").exists()).toBe(false)
    expect(mockDeleteBlock).not.toHaveBeenCalled()
  })

  it("keeps dialog keyboard input out of the page shortcut handler", async () => {
    const wrapper = mount(DeleteBlockDialog, { props: { heading: "Delete block?", message: "Delete Test Block?" } })
    const pageShortcut = vi.fn()
    document.addEventListener("keydown", pageShortcut)
    try {
      const button = document.querySelector<HTMLButtonElement>("dialog .cancel-delete")!
      button.dispatchEvent(new KeyboardEvent("keydown", { key: "z", metaKey: true, bubbles: true }))
      expect(pageShortcut).not.toHaveBeenCalled()
    } finally {
      document.removeEventListener("keydown", pageShortcut)
      wrapper.unmount()
    }
  })

  it.each([
    { date: "2026-04-11" },
    { block: makeBlock({ id: 2 }) },
    { block: makeBlock({ title: "Changed elsewhere" }) },
  ])("dismisses confirmation when its context changes: %j", async (change) => {
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".delete-btn").trigger("click")
    await wrapper.setProps(change)
    expect(wrapper.find("dialog").exists()).toBe(false)
    expect(mockDeleteBlock).not.toHaveBeenCalled()
  })

  it("dismisses confirmation and disables deletion while another write is busy", async () => {
    const busy = ref(false)
    const wrapper = mount(TimeBlock, {
      props: { block: makeBlock(), date: "2026-04-10" },
      global: { stubs: { teleport: true }, provide: { [ScheduleDisabledKey]: busy } },
    })
    await wrapper.find(".delete-btn").trigger("click")
    busy.value = true
    await flushPromises()
    expect(wrapper.find("dialog").exists()).toBe(false)
    expect(wrapper.find(".delete-btn").attributes("disabled")).toBeDefined()
    expect(mockDeleteBlock).not.toHaveBeenCalled()
  })

  it("submits only once if confirmation is repeated before the next render", async () => {
    mockDeleteBlock.mockResolvedValue(acceptedMutation([makeBlock()]))
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".delete-btn").trigger("click")
    const dialog = wrapper.findComponent(DeleteBlockDialog)
    dialog.vm.$emit("confirm")
    dialog.vm.$emit("confirm")
    await flushPromises()
    expect(mockDeleteBlock).toHaveBeenCalledTimes(1)
  })

  it("shows deletion failure without recording Undo", async () => {
    mockDeleteBlock.mockResolvedValue({ ok: false })
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".delete-btn").trigger("click")
    await wrapper.find(".confirm-delete").trigger("click")
    await flushPromises()
    expect(wrapper.text()).toContain("Failed to delete")
    expect(mockPushUndo).not.toHaveBeenCalled()
  })

  it("shows completed styling", () => {
    const wrapper = mountWithProvide({ block: makeBlock({ is_completed: true }), date: "2026-04-10" })
    expect(wrapper.find(".time-block").classes()).toContain("completed")
    expect(wrapper.find(".title-completed").exists()).toBe(true)
  })

  it("shows error on failed title update", async () => {
    mockUpdateBlock.mockResolvedValue({ ok: false })
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".title").trigger("click")
    await wrapper.find(".title-input").setValue("Changed")
    await wrapper.find(".title-input").trigger("keydown.enter")
    await vi.dynamicImportSettled()
    expect(wrapper.text()).toContain("Failed to update title")
    // Failure path re-opens the input so the user can retry without
    // losing their typed value (paired with ``editing.value = true``
    // on the failure branch in saveTitle).
    expect(wrapper.find(".title-input").exists()).toBe(true)
  })

  it("renders drag handle", () => {
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    expect(wrapper.find(".drag-handle").exists()).toBe(true)
  })

  it("pushUndo called on successful title save", async () => {
    mockUpdateBlock.mockResolvedValue(acceptedMutation([makeBlock()]))
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".title").trigger("click")
    await wrapper.find(".title-input").setValue("New Title")
    await wrapper.find(".title-input").trigger("keydown.enter")
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "edit", silent: true }),
    )
  })

  it("pushUndo called on successful toggle", async () => {
    mockUpdateBlock.mockResolvedValue(acceptedMutation([makeBlock()]))
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "toggle", silent: true }),
    )
  })

  it("pushUndo called on successful delete", async () => {
    mockDeleteBlock.mockResolvedValue(acceptedMutation([makeBlock()]))
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".delete-btn").trigger("click")
    await wrapper.find(".confirm-delete").trigger("click")
    expect(mockPushUndo).toHaveBeenCalledWith(
      expect.objectContaining({ type: "delete", silent: true }),
    )
  })

  it("pushUndo NOT called on failed update", async () => {
    mockUpdateBlock.mockResolvedValue({ ok: false })
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".title").trigger("click")
    await wrapper.find(".title-input").setValue("New")
    await wrapper.find(".title-input").trigger("keydown.enter")
    await vi.dynamicImportSettled()
    expect(mockPushUndo).not.toHaveBeenCalled()
  })

  // Issue #21: if the user navigates to a different date while a
  // mutation is in flight, the undo entry must still restore to the
  // date the mutation started on, not whatever ``props.date`` happens
  // to read at pushUndo time.

  it("ignores stale toggle history after date navigation", async () => {
    let resolveUpdate: (v: { ok: boolean }) => void = () => {}
    mockUpdateBlock.mockReturnValueOnce(
      new Promise<{ ok: boolean }>((res) => {
        resolveUpdate = res
      }),
    )
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".checkbox").trigger("change")
    await wrapper.setProps({ date: "2026-04-11" })
    resolveUpdate({ ok: true })
    await flushPromises()
    expect(mockPushUndo).not.toHaveBeenCalled()
  })

  it("ignores stale edit history after date navigation", async () => {
    let resolveUpdate: (v: { ok: boolean }) => void = () => {}
    mockUpdateBlock.mockReturnValueOnce(
      new Promise<{ ok: boolean }>((res) => {
        resolveUpdate = res
      }),
    )
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".title").trigger("click")
    await wrapper.find(".title-input").setValue("Renamed")
    await wrapper.find(".title-input").trigger("keydown.enter")
    await wrapper.setProps({ date: "2026-04-11" })
    resolveUpdate({ ok: true })
    await flushPromises()
    expect(mockPushUndo).not.toHaveBeenCalled()
  })

  it("ignores stale delete history after date navigation", async () => {
    let resolveDelete: (v: { ok: boolean }) => void = () => {}
    mockDeleteBlock.mockReturnValueOnce(
      new Promise<{ ok: boolean }>((res) => {
        resolveDelete = res
      }),
    )
    const wrapper = mountWithProvide({ block: makeBlock(), date: "2026-04-10" })
    await wrapper.find(".delete-btn").trigger("click")
    await wrapper.find(".confirm-delete").trigger("click")
    await wrapper.setProps({ date: "2026-04-11" })
    resolveDelete({ ok: true })
    await flushPromises()
    expect(mockPushUndo).not.toHaveBeenCalled()
  })
})
