import { afterEach, describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"
import { defineComponent, h, inject, nextTick, ref } from "vue"
import type { Schedule, TimeBlock } from "../src/types"
import { ScheduleDisabledKey, ScheduleUndoKey } from "../src/composables/scheduleContext"
import { useSchedulePageController } from "../src/composables/useSchedulePageController"
import { useChat } from "../src/composables/useChat"
import { useDraft } from "../src/composables/useDraft"

const { requestJsonMock } = vi.hoisted(() => ({ requestJsonMock: vi.fn() }))
vi.mock("../src/composables/useHttp", () => ({ requestJson: requestJsonMock }))

interface Fixture {
  date: ReturnType<typeof ref<string>>
  schedule: ReturnType<typeof ref<Schedule>>
  blocks: ReturnType<typeof ref<TimeBlock[]>>
  timeZone: ReturnType<typeof ref<string>>
  autoDraftPending: ReturnType<typeof ref<boolean>>
  mutationsDisabled: ReturnType<typeof ref<boolean>>
}

function mountController() {
  const fixture: Fixture = {
    date: ref("2026-05-07"),
    schedule: ref<Schedule>({ id: 1, date: "2026-05-07", status: "active", revision: 0 }),
    blocks: ref<TimeBlock[]>([]),
    timeZone: ref("UTC"),
    autoDraftPending: ref(false),
    mutationsDisabled: ref(false),
  }
  let controller!: ReturnType<typeof useSchedulePageController>
  let injectedDisabled: ReturnType<typeof inject<typeof ScheduleDisabledKey>>
  let injectedUndo: ReturnType<typeof inject<typeof ScheduleUndoKey>>
  const Child = defineComponent({
    setup() {
      injectedDisabled = inject(ScheduleDisabledKey)
      injectedUndo = inject(ScheduleUndoKey)
      return () => h("span")
    },
  })
  const Host = defineComponent({
    setup() {
      controller = useSchedulePageController({
        getDate: () => fixture.date.value,
        getSchedule: () => fixture.schedule.value,
        getBlocks: () => fixture.blocks.value,
        getUserId: () => 7,
        getTimeZone: () => fixture.timeZone.value,
        getAutoDraftPending: () => fixture.autoDraftPending.value,
        getMutationsDisabled: () => fixture.mutationsDisabled.value,
      })
      return () => h(Child)
    },
  })
  const wrapper = mount(Host)
  return { fixture, controller, wrapper, getInjected: () => ({ disabled: injectedDisabled, undo: injectedUndo }) }
}

afterEach(() => { requestJsonMock.mockReset() })

describe("useSchedulePageController", () => {
  it("blocks keyboard Undo after a valid page becomes mutation-disabled", async () => {
    const { fixture, controller, wrapper } = mountController()
    controller.pushUndo({
      description: "Added block", type: "add", previousBlocks: [],
      scheduleDate: fixture.date.value, expected_revision: 0, previous_revision: 0,
    })
    expect(controller.canUndo.value).toBe(true)
    fixture.mutationsDisabled.value = true
    await nextTick()
    expect(controller.scheduleDisabled.value).toBe(true)

    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "z", ctrlKey: true, bubbles: true }))
    await nextTick()
    expect(requestJsonMock).not.toHaveBeenCalled()

    fixture.mutationsDisabled.value = false
    await nextTick()
    requestJsonMock.mockResolvedValue({ ok: true, data: {
      blocks: [], revision: 1,
      schedule: { ...fixture.schedule.value, revision: 1 },
    } })
    document.body.dispatchEvent(new KeyboardEvent("keydown", { key: "z", ctrlKey: true, bubbles: true }))
    await vi.waitFor(() => expect(requestJsonMock).toHaveBeenCalledTimes(1))
    expect(requestJsonMock.mock.calls[0][0]).toContain("restore")
    wrapper.unmount()
  })

  it("provides mutation context and clears page-scoped AI state on navigation and logout", async () => {
    const { fixture, controller, wrapper, getInjected } = mountController()
    const { disabled, undo } = getInjected()
    expect(disabled).toBe(controller.scheduleDisabled)
    expect(undo?.pushUndo).toBe(controller.pushUndo)
    expect(controller.canonicalSchedule.value?.date).toBe("2026-05-07")

    const chat = useChat(controller.scheduleRevision)
    const draft = useDraft(controller.scheduleRevision)
    chat.draftInput.value = "Private prompt"
    chat.messages.value = [{ role: "user", content: "Hello", ask: null, explanation: null, ts: 1 }]
    draft.lastDraftError.value = "Old error"
    fixture.schedule.value = { id: 2, date: "2026-05-08", status: "active", revision: 0 }
    fixture.date.value = "2026-05-08"
    await nextTick()
    expect(chat.messages.value).toEqual([])
    expect(chat.activeDate.value).toBe("2026-05-08")
    expect(draft.lastDraftError.value).toBeNull()

    controller.resetSession()
    expect(chat.draftInput.value).toBe("")
    expect(controller.canonicalSchedule.value).toBeNull()
    wrapper.unmount()
  })

  it("attempts automatic draft once for each server-pending date", async () => {
    const { fixture, controller, wrapper } = mountController()
    requestJsonMock.mockImplementation(async (_url: string, _method: string, body: { expected_revision: number }) => ({
      ok: true,
      data: {
        blocks: [], revision: body.expected_revision + 1,
        schedule: { ...fixture.schedule.value, revision: body.expected_revision + 1 },
      },
    }))
    fixture.autoDraftPending.value = true
    await nextTick()
    await vi.waitFor(() => expect(requestJsonMock).toHaveBeenCalledTimes(1))
    expect(requestJsonMock.mock.calls[0][0]).toBe("/api/ai/schedules/2026-05-07/generate-draft/")
    expect(controller.canonicalSchedule.value?.revision).toBe(1)

    fixture.autoDraftPending.value = false
    await nextTick()
    fixture.autoDraftPending.value = true
    await nextTick()
    expect(requestJsonMock).toHaveBeenCalledTimes(1)
    wrapper.unmount()
  })
})
