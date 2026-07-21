// AddToScheduleDialog — Confirm gating, rule prefill, and undo parity.
//
// The plan locks several behaviours that are only reachable through this
// component: every add goes through a confirm step, the dialog prefills EVERY
// field from a matched rule, and two states must block Confirm outright
// (an event that maps entirely outside the viewed local day, and a
// zero-length range). Those gates previously had only indirect coverage via
// the travelRules util tests, which do not exercise the disabled state.

import { describe, expect, it, vi, beforeEach } from "vitest"
import { mount } from "@vue/test-utils"
import { ref } from "vue"

const createBlockFromEvent = vi.fn().mockResolvedValue({ ok: true })

vi.mock("../src/composables/useSchedule", () => ({
  useSchedule: () => ({ createBlockFromEvent }),
}))

import AddToScheduleDialog from "../src/components/AddToScheduleDialog.vue"
import type { TravelRule } from "../src/types"

const DATE = "2026-05-07"

// 14:07–14:33 local on the viewed day — deliberately off-grid, since that is
// the whole reason the from-event endpoint exists.
function localEvent(startHM: string, endHM: string) {
  const [sh, sm] = startHM.split(":").map(Number)
  const [eh, em] = endHM.split(":").map(Number)
  const [y, m, d] = DATE.split("-").map(Number)
  return {
    title: "Dentist",
    start: new Date(y, m - 1, d, sh, sm).toISOString(),
    end: new Date(y, m - 1, d, eh, em).toISOString(),
    calendar_name: "Personal",
    all_day: false,
    external_uid: "uid-1",
    account_label: "",
  }
}

const GYM_RULE: TravelRule = {
  id: 1,
  keyword: "dentist",
  travel_there_minutes: 30,
  travel_back_minutes: 15,
  category: "health",
  order: 0,
}

function mountDialog(overrides: Record<string, unknown> = {}) {
  return mount(AddToScheduleDialog, {
    props: {
      event: localEvent("14:07", "14:33"),
      matchedRule: null,
      date: DATE,
      ...overrides,
    },
  })
}

function confirmBtn(wrapper: ReturnType<typeof mountDialog>) {
  return wrapper.find("button.ats-confirm")
}

describe("AddToScheduleDialog", () => {
  beforeEach(() => {
    createBlockFromEvent.mockClear()
    createBlockFromEvent.mockResolvedValue({ ok: true })
  })

  it("enables Confirm for a normal timed event", () => {
    expect(confirmBtn(mountDialog()).attributes("disabled")).toBeUndefined()
  })

  it("posts the exact off-grid times to the from-event endpoint", async () => {
    const wrapper = mountDialog()
    await confirmBtn(wrapper).trigger("click")

    expect(createBlockFromEvent).toHaveBeenCalledOnce()
    expect(createBlockFromEvent.mock.calls[0][0]).toMatchObject({
      title: "Dentist",
      start_time: "14:07",
      end_time: "14:33",
      category: "other",
    })
  })

  it("prefills every field from a matched rule and applies the padding", async () => {
    const wrapper = mountDialog({ matchedRule: GYM_RULE })
    await confirmBtn(wrapper).trigger("click")

    // 30 before / 15 after, and the rule's category — not the "other" default.
    expect(createBlockFromEvent.mock.calls[0][0]).toMatchObject({
      start_time: "13:37",
      end_time: "14:48",
      category: "health",
    })
  })

  it("blocks Confirm for a zero-length event with no travel padding", async () => {
    const wrapper = mountDialog({ event: localEvent("14:07", "14:07") })
    expect(confirmBtn(wrapper).attributes("disabled")).toBeDefined()
    // End-to-end check that a gated dialog cannot submit. Note this does NOT
    // exercise handleConfirm's internal confirmDisabled guard: VTU's trigger()
    // no-ops on a disabled element (as does jsdom), so that guard is redundant
    // defence behind the attribute and is unreachable from the DOM. The
    // attribute itself is the real protection and is mutation-verified —
    // dropping either gate from confirmDisabled fails these tests.
    await confirmBtn(wrapper).trigger("click")
    expect(createBlockFromEvent).not.toHaveBeenCalled()
  })

  it("re-enables Confirm once travel padding stretches a zero-length event", async () => {
    const wrapper = mountDialog({
      event: localEvent("14:07", "14:07"),
      matchedRule: GYM_RULE,
    })
    expect(confirmBtn(wrapper).attributes("disabled")).toBeUndefined()
    await confirmBtn(wrapper).trigger("click")
    expect(createBlockFromEvent.mock.calls[0][0]).toMatchObject({
      start_time: "13:37",
      end_time: "14:22",
    })
  })

  it("blocks Confirm when the event lies outside the viewed local day", async () => {
    // Same wall-clock times, but the dialog is viewing a different date.
    const wrapper = mountDialog({ date: "2026-05-09" })
    expect(confirmBtn(wrapper).attributes("disabled")).toBeDefined()
    await confirmBtn(wrapper).trigger("click")
    expect(createBlockFromEvent).not.toHaveBeenCalled()
  })

  it("does not submit while scheduleDisabled is injected true", async () => {
    const wrapper = mount(AddToScheduleDialog, {
      props: { event: localEvent("14:07", "14:33"), matchedRule: null, date: DATE },
      global: { provide: { scheduleDisabled: ref(true) } },
    })
    expect(confirmBtn(wrapper).attributes("disabled")).toBeDefined()
    await confirmBtn(wrapper).trigger("click")
    expect(createBlockFromEvent).not.toHaveBeenCalled()
  })

  it("pushes an undo entry snapshotted BEFORE the create", async () => {
    const pushUndo = vi.fn()
    const snapshotBlocks = vi.fn().mockReturnValue([{ id: 1 }])
    const wrapper = mount(AddToScheduleDialog, {
      props: { event: localEvent("14:07", "14:33"), matchedRule: null, date: DATE },
      global: { provide: { undo: { pushUndo, snapshotBlocks } } },
    })
    await confirmBtn(wrapper).trigger("click")
    await Promise.resolve()

    expect(snapshotBlocks).toHaveBeenCalled()
    // Order matters, not just the calls: snapshotting AFTER the create would
    // capture the post-create state and make undo a no-op. Assert the
    // snapshot strictly precedes the request (issue #21 parity).
    expect(snapshotBlocks.mock.invocationCallOrder[0]).toBeLessThan(
      createBlockFromEvent.mock.invocationCallOrder[0],
    )
    expect(pushUndo).toHaveBeenCalledWith(
      expect.objectContaining({
        type: "add",
        scheduleDate: DATE,
        previousBlocks: [{ id: 1 }],
      }),
    )
  })

  it("does not push undo when the create fails", async () => {
    createBlockFromEvent.mockResolvedValue({
      ok: false,
      errors: { time: "This block overlaps with an existing block." },
    })
    const pushUndo = vi.fn()
    const wrapper = mount(AddToScheduleDialog, {
      props: { event: localEvent("14:07", "14:33"), matchedRule: null, date: DATE },
      global: {
        provide: { undo: { pushUndo, snapshotBlocks: () => [] } },
      },
    })
    await confirmBtn(wrapper).trigger("click")
    await Promise.resolve()

    expect(pushUndo).not.toHaveBeenCalled()
    expect(wrapper.text()).toContain("overlaps")
    // Dialog stays open so the user can adjust rather than losing the form.
    expect(wrapper.emitted("close")).toBeUndefined()
  })

  it("warns when the travel rules could not be loaded", () => {
    const wrapper = mountDialog({ rulesUnavailable: true })
    expect(wrapper.find('[data-testid="rules-unavailable"]').exists()).toBe(true)
  })

  it("still allows Confirm while the rules are unavailable", async () => {
    // The warning informs; it must not lock the user out. Times are editable
    // in the dialog, so adding with manual values stays possible.
    const wrapper = mountDialog({ rulesUnavailable: true })
    expect(confirmBtn(wrapper).attributes("disabled")).toBeUndefined()
    await confirmBtn(wrapper).trigger("click")
    expect(createBlockFromEvent).toHaveBeenCalledOnce()
  })

  it("shows no warning when the rules loaded and simply did not match", () => {
    // Same null matchedRule — only the flag distinguishes the two states.
    const wrapper = mountDialog({ rulesUnavailable: false })
    expect(wrapper.find('[data-testid="rules-unavailable"]').exists()).toBe(false)
  })
})
