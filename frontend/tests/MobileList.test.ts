import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { enableAutoUnmount, flushPromises, mount } from "@vue/test-utils"
import { ref } from "vue"
import { ScheduleContainerKey, ScheduleDragKey, ScheduleUndoKey } from "../src/composables/scheduleContext"
import { acceptedMutation } from "./helpers/mutation"
import { makeCategories } from "./helpers/schedule"

const mockUpdateBlock = vi.fn()
const mockDeleteBlock = vi.fn()
vi.mock("../src/composables/useSchedule", () => ({
  useSchedule: () => ({ updateBlock: mockUpdateBlock, deleteBlock: mockDeleteBlock }),
}))
vi.mock("@inertiajs/vue3", () => ({
  usePage: () => ({ props: { ui_preferences: { theme: "dark_4a" } } }),
}))

import TimelineMobile from "../src/components/TimelineMobile.vue"
import { buildMobileRows } from "../src/utils/mobileRows"
import { DEFAULT_SCHEDULE_WINDOW, timeToMinutes, type ScheduleWindowBounds } from "../src/utils/scheduleTime"
import type { TimeBlock } from "../src/types"

enableAutoUnmount(afterEach)

const DATE = "2026-11-27"
const WINDOW: ScheduleWindowBounds = {
  start: "05:00", end: "22:00", startMinutes: timeToMinutes("05:00"), endMinutes: timeToMinutes("22:00"),
}

function block(id: number, title: string, start: string, end: string, extra: Partial<TimeBlock> = {}): TimeBlock {
  return { id, title, start_time: start, end_time: end, category: "work", is_completed: false, sort_order: id, ...extra }
}

// The agreed mockup day (Fri, Nov 27 2026).
const SKETCH_DAY: TimeBlock[] = [
  block(1, "Lunch", "13:25", "13:50", { is_completed: true }),
  block(2, "Kick-off", "13:55", "14:20", { is_completed: true }),
  block(3, "Lunch Walk", "16:05", "17:05"),
  block(4, "English", "17:05", "17:50"),
  block(5, "My VC Course", "18:00", "19:00"),
]

const pushUndo = vi.fn()
const startDrag = vi.fn()

function mountList(blocks: TimeBlock[], extra: { disabled?: boolean } = {}) {
  return mount(TimelineMobile, {
    props: { date: DATE, blocks, window: WINDOW, disabled: extra.disabled ?? false, categories: makeCategories() },
    global: {
      stubs: { teleport: true },
      provide: {
        [ScheduleUndoKey]: { pushUndo },
        [ScheduleDragKey]: {
          startDrag, isDragging: ref(false), dragBlockId: ref(null), shiftedBlockIds: ref(new Set()),
        },
        [ScheduleContainerKey]: ref(null),
      },
    },
  })
}

beforeEach(() => {
  vi.clearAllMocks()
  mockUpdateBlock.mockReset()
  mockDeleteBlock.mockReset()
})

describe("buildMobileRows (feature 0113)", () => {
  it("returns one whole free row for an empty day", () => {
    expect(buildMobileRows([], WINDOW)).toEqual([
      expect.objectContaining({ kind: "gap", start_time: "05:00", end_time: "22:00", duration_minutes: 1020 }),
    ])
  })

  it("lists edge and inner gaps in time order and none between touching blocks", () => {
    const rows = buildMobileRows(SKETCH_DAY, WINDOW).map((row) =>
      row.kind === "block" ? row.block.title : `${row.start_time}-${row.end_time}`)
    expect(rows).toEqual([
      "05:00-13:25", "Lunch", "13:50-13:55", "Kick-off", "14:20-16:05",
      "Lunch Walk", "English", "17:50-18:00", "My VC Course", "19:00-22:00",
    ])
  })

  it("never splits the trailing gap at the clock and drops inert spacers", () => {
    const rows = buildMobileRows([block(1, "Late", "23:00", "23:30")], DEFAULT_SCHEDULE_WINDOW)
    const gaps = rows.filter((row) => row.kind === "gap")
    expect(new Set(gaps.map((g) => g.key)).size).toBe(gaps.length)
    expect(rows.every((row) => row.kind === "block" || row.duration_minutes > 0)).toBe(true)
  })
})

describe("TimelineMobile (feature 0113)", () => {
  it("renders a block row per block and a free row per gap, with no axis or now line", () => {
    const w = mountList(SKETCH_DAY)
    expect(w.findAll('[data-testid="mobile-block-row"]')).toHaveLength(5)
    expect(w.findAll('[data-testid="mobile-gap-row"]')).toHaveLength(5)
    expect(w.find('[data-testid="hour-tick"]').exists()).toBe(false)
    expect(w.find('[data-testid="now-line-4a"]').exists()).toBe(false)
    expect(w.find('[data-testid="timeline-4a"]').exists()).toBe(false)
  })

  it("shows start time, duration and ×, and no end time, for a 5-minute block", () => {
    const w = mountList([block(9, "Short call", "11:40", "11:45")])
    const row = w.get('[data-testid="mobile-block-row"]')
    expect(row.get(".time-badge").text()).toBe("11:40")
    expect(row.find(".time-end").exists()).toBe(false)
    expect(row.get(".duration").text()).toBe("5m")
    expect(row.get(".delete-btn").exists()).toBe(true)
    expect(row.find(".density-compact").exists()).toBe(false)
  })

  it("labels free rows with duration and range", () => {
    const w = mountList(SKETCH_DAY)
    const first = w.findAll('[data-testid="mobile-gap-row"]')[0]
    expect(first.text()).toContain("Free · 8h 25m")
    expect(first.text()).toContain("05:00–13:25")
  })

  it("emits the grid-snapped range when a free row is tapped, and ignores tiny or disabled gaps", async () => {
    const w = mountList(SKETCH_DAY)
    const rows = w.findAll('[data-testid="mobile-gap-row"]')
    await rows[2].trigger("click")
    expect(w.emitted("add-here-4a")).toEqual([[{ start_time: "14:20", end_time: "16:05" }]])
    // 17:50–18:00 snaps to 17:50–18:00; the 5-minute 13:50–13:55 also fits.
    await rows[1].trigger("click")
    expect(w.emitted("add-here-4a")?.[1]).toEqual([{ start_time: "13:50", end_time: "13:55" }])
    const off = mountList(SKETCH_DAY, { disabled: true })
    await off.findAll('[data-testid="mobile-gap-row"]')[0].trigger("click")
    expect(off.emitted("add-here-4a")).toBeUndefined()
    const tiny = mountList([block(1, "A", "09:00", "09:30"), block(2, "B", "09:33", "10:00")])
    const tinyGap = tiny.findAll('[data-testid="mobile-gap-row"]')[1]
    expect(tinyGap.text()).toContain("Free · 3m")
    await tinyGap.trigger("click")
    expect(tiny.emitted("add-here-4a")).toBeUndefined()
  })

  it("deletes on the × tap without a confirmation dialog and registers Undo", async () => {
    mockDeleteBlock.mockResolvedValue(acceptedMutation([], DATE, 2))
    const w = mountList([block(7, "Gym", "10:00", "11:00")])
    await w.get(".delete-btn").trigger("click")
    await flushPromises()
    expect(w.find("dialog").exists()).toBe(false)
    expect(mockDeleteBlock).toHaveBeenCalledWith(7)
    expect(pushUndo).toHaveBeenCalledWith(expect.objectContaining({ type: "delete", silent: true }))
  })

  it("floats a delete failure instead of growing the 52 px row", async () => {
    mockDeleteBlock.mockResolvedValue({ ok: false })
    const w = mountList([block(7, "Gym", "10:00", "11:00")])
    await w.get(".delete-btn").trigger("click")
    await flushPromises()
    expect(w.find(".block-error").exists()).toBe(false)
    expect(w.get('[role="alert"]').text()).toBe("Failed to delete")
  })

  it("completes through the shared completion queue", async () => {
    mockUpdateBlock.mockResolvedValue(acceptedMutation([block(7, "Gym", "10:00", "11:00", { is_completed: true })], DATE, 2))
    const w = mountList([block(7, "Gym", "10:00", "11:00")])
    const box = w.get('input[type="checkbox"]')
    expect(box.classes()).toContain("df-checkbox")
    await box.setValue(true)
    await flushPromises()
    expect(mockUpdateBlock).toHaveBeenCalledWith(7, { is_completed: true }, expect.anything())
  })

  it("keeps the grip inert: no drag starts from it", async () => {
    const w = mountList([block(7, "Gym", "10:00", "11:00")])
    await w.get(".drag-handle").trigger("pointerdown")
    expect(startDrag).not.toHaveBeenCalled()
  })

  it("keeps the inline title edit on a tap of the title", async () => {
    const w = mountList([block(7, "Gym", "10:00", "11:00")])
    await w.get(".title").trigger("click")
    expect(w.find(".title-input").exists()).toBe(true)
  })
})
