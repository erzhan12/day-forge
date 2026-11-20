import { afterEach, describe, expect, it } from "vitest"
import { nextTick } from "vue"
import { mount, VueWrapper } from "@vue/test-utils"

import ExternalRail4a from "../src/components/ExternalRail4a.vue"
import type { TodoistTask } from "../src/types/todoist"
import type { NormalizedEvent } from "../src/types/calendar"
import { EXTERNAL_RAIL_COLLAPSED_KEY } from "../src/utils/externalRailSectionsStorage"
import { clearLocalStorage } from "./helpers/storage"

let wrapper: VueWrapper | null = null

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  clearLocalStorage()
})

const TASK_A: TodoistTask = {
  id: "todo-1",
  title: "A task",
  priority: 1,
  ui_priority: "P4",
  due_date: null,
}
const TASK_B: TodoistTask = {
  id: "todo-2",
  title: "B task",
  priority: 1,
  ui_priority: "P4",
  due_date: null,
}
const TASK_C: TodoistTask = {
  id: "todo-3",
  title: "C task",
  priority: 1,
  ui_priority: "P4",
  due_date: null,
}

function baseProps() {
  return {
    activeDate: "2026-08-22",
    open: true,
    "onUpdate:open": (v: boolean) => {
      wrapper?.setProps({ open: v })
    },
    todoistTasks: [] as TodoistTask[],
    todoistLoading: false,
    todoistError: null as string | null,
    showTodoist: true,
    habiticaTasks: [],
    habiticaLoading: false,
    habiticaError: null,
    showHabitica: false,
    showCalendars: false,
    events: [],
    eventsLoading: false,
    eventErrors: [],
    accountErrors: [],
    externalConnected: false,
    nowMinutes: null,
  }
}

function mountRail(props: Record<string, unknown> = {}) {
  wrapper = mount(ExternalRail4a, {
    props: { ...baseProps(), ...props },
    attachTo: document.body,
  })
  return wrapper
}

function progressText(): string {
  return wrapper!.get('[data-testid="todoist-session-progress"]').text()
}

async function commitTodoistLoad(tasks: TodoistTask[], error: string | null = null) {
  await wrapper!.setProps({ todoistLoading: true, todoistError: null })
  await nextTick()
  await wrapper!.setProps({ todoistLoading: false, todoistTasks: tasks, todoistError: error })
  await nextTick()
}

describe("ExternalRail4a session baseline", () => {
  it("does not lock the idle loading=false empty list as the denominator", async () => {
    mountRail({ todoistLoading: false, todoistTasks: [] })
    expect(progressText()).toBe("–")

    await commitTodoistLoad([TASK_A, TASK_B, TASK_C])
    expect(progressText()).toBe("0 / 3")
  })

  it("treats an empty successful load as baseline 0, not missing", async () => {
    mountRail()
    await commitTodoistLoad([])
    expect(progressText()).toBe("0 / 0")
  })

  it("captures a warm mount that already has rows (theme switch)", async () => {
    mountRail({ todoistLoading: false, todoistTasks: [TASK_A, TASK_B] })
    await nextTick()
    expect(progressText()).toBe("0 / 2")
  })

  it("does not capture a failed fetch; recaptures on the next success", async () => {
    mountRail()
    await commitTodoistLoad([], "Todoist service unavailable. Try again later.")
    expect(progressText()).toBe("–")

    await commitTodoistLoad([TASK_A, TASK_B])
    expect(progressText()).toBe("0 / 2")
  })

  it("resets on date change and waits for the new date's commit, not the stale list", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A, TASK_B, TASK_C])
    expect(progressText()).toBe("0 / 3")

    await wrapper!.setProps({ activeDate: "2026-08-23" })
    await nextTick()
    expect(progressText()).toBe("–")

    await commitTodoistLoad([TASK_A])
    expect(progressText()).toBe("0 / 1")
  })

  it("accepts the in-flight commit when the date changes during a load", async () => {
    mountRail({ todoistLoading: true, todoistTasks: [TASK_A, TASK_B, TASK_C] })
    expect(progressText()).toBe("–")

    await wrapper!.setProps({ activeDate: "2026-08-23" })
    await nextTick()
    expect(progressText()).toBe("–")

    await wrapper!.setProps({
      todoistLoading: false,
      todoistTasks: [TASK_A],
      todoistError: null,
    })
    await nextTick()
    expect(progressText()).toBe("0 / 1")
  })

  it("counts a row that vanishes after refresh as completed this session", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A, TASK_B, TASK_C])
    await commitTodoistLoad([TASK_A, TASK_B])
    expect(progressText()).toBe("1 / 3")
  })

  it("keeps the session denominator when the last remaining task vanishes", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A, TASK_B, TASK_C])
    await commitTodoistLoad([])
    expect(progressText()).toBe("3 / 3")
  })

  it("counts completing the last task without a loading cycle", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A, TASK_B, TASK_C])
    await wrapper!.setProps({ todoistTasks: [] })
    await nextTick()
    expect(progressText()).toBe("3 / 3")
  })

  it("does not keep an empty-day baseline when tasks later appear", async () => {
    mountRail()
    await commitTodoistLoad([])
    expect(progressText()).toBe("0 / 0")

    await commitTodoistLoad([TASK_A, TASK_B, TASK_C])
    expect(progressText()).toBe("0 / 3")

    await wrapper!.setProps({ todoistTasks: [] })
    await nextTick()
    expect(progressText()).toBe("3 / 3")
  })

  it("counts an in-app complete once the parent drops the row", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A, TASK_B])
    await wrapper!.findAll('[data-testid="todoist-complete"]')[0].trigger("change")
    await wrapper!.setProps({ todoistTasks: [TASK_B] })
    await nextTick()
    expect(progressText()).toBe("1 / 2")
    expect(wrapper!.emitted("todoistComplete")![0]).toEqual(["todo-1"])
  })

  it("still counts a baseline id that left even if a new task arrives in the same refresh", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A, TASK_B])
    await commitTodoistLoad([TASK_B, TASK_C])
    expect(progressText()).toBe("1 / 3")
  })

  it("grows the denominator when a new task appears after the session was already 1/1", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A])
    await commitTodoistLoad([])
    expect(progressText()).toBe("1 / 1")

    await commitTodoistLoad([TASK_B])
    expect(progressText()).toBe("1 / 2")
  })

  it("does not treat an in-flight refresh as wiping the remaining set", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A, TASK_B, TASK_C])
    await wrapper!.setProps({ todoistLoading: true })
    await nextTick()
    expect(progressText()).toBe("0 / 3")
  })

  it("counts a Habitica daily that disappears after refresh", async () => {
    const dailyA = { id: "hab-1", title: "Floss", type: "daily" as const, due_date: null, completed: false }
    const dailyB = { id: "hab-2", title: "Stretch", type: "daily" as const, due_date: null, completed: false }
    mountRail({ showHabitica: true, showTodoist: false })
    await wrapper!.setProps({ habiticaLoading: true, habiticaError: null })
    await nextTick()
    await wrapper!.setProps({
      habiticaLoading: false,
      habiticaTasks: [dailyA, dailyB],
      habiticaError: null,
    })
    await nextTick()
    expect(wrapper!.get('[data-testid="habitica-session-progress"]').text()).toBe(
      "0 / 2",
    )

    await wrapper!.setProps({ habiticaLoading: true })
    await nextTick()
    await wrapper!.setProps({
      habiticaLoading: false,
      habiticaTasks: [dailyB],
      habiticaError: null,
    })
    await nextTick()
    expect(wrapper!.get('[data-testid="habitica-session-progress"]').text()).toBe(
      "1 / 2",
    )
  })
})

describe("ExternalRail4a section layout", () => {
  it("keeps task sections as siblings and pins the calendar last", () => {
    mountRail({ showHabitica: true, showCalendars: true, externalConnected: true })
    const content = wrapper!.get(".rail-content")
    const sections = content.findAll(":scope > section")
    expect(sections).toHaveLength(3)
    expect(sections[0].classes()).toContain("task-section")
    expect(sections[1].classes()).toContain("task-section")
    expect(sections[2].classes()).toContain("calendar-section")
    expect(content.element.lastElementChild).toBe(sections[2].element)
  })
})

function section(id: string) {
  return wrapper!.get(`section[data-section="${id}"]`)
}

async function toggleSectionHeader(id: string) {
  await wrapper!.get(`[data-testid="rail-section-toggle-${id}"]`).trigger("click")
}

describe("ExternalRail4a section collapse", () => {
  it("collapses from the header, makes the body inert and keeps title, counter and bar", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A, TASK_B])
    const header = wrapper!.get('[data-testid="rail-section-toggle-todoist"]')
    expect(header.attributes("aria-expanded")).toBe("true")
    await toggleSectionHeader("todoist")
    expect(header.attributes("aria-expanded")).toBe("false")
    const body = section("todoist").get('[data-testid="rail-section-body"]')
    expect(body.attributes("inert")).toBeDefined()
    expect(header.text()).toContain("Todoist")
    expect(progressText()).toBe("0 / 2")
    expect(section("todoist").find(".bar").exists()).toBe(true)
  })

  it("restores each section's collapsed state from storage on mount", async () => {
    localStorage.setItem(EXTERNAL_RAIL_COLLAPSED_KEY, JSON.stringify({ todoist: true, habitica: false }))
    mountRail({ showHabitica: true })
    expect(wrapper!.get('[data-testid="rail-section-toggle-todoist"]').attributes("aria-expanded")).toBe("false")
    expect(wrapper!.get('[data-testid="rail-section-toggle-habitica"]').attributes("aria-expanded")).toBe("true")
    await toggleSectionHeader("habitica")
    expect(JSON.parse(localStorage.getItem(EXTERNAL_RAIL_COLLAPSED_KEY)!)).toEqual({ todoist: true, habitica: true, calendars: false })
  })

  it("renders the progress bar at 0 % and speaks the full counter", async () => {
    mountRail()
    expect(section("todoist").get(".rail-sr-only").text()).toBe("Not loaded yet")
    await commitTodoistLoad([TASK_A])
    expect(section("todoist").get(".bar i").attributes("style")).toContain("width: 0%")
    expect(section("todoist").get(".rail-sr-only").text()).toBe("0 of 1 completed this session")
  })

  it("shows the panel's own error as a status peek on a collapsed task section", async () => {
    mountRail()
    await commitTodoistLoad([TASK_A])
    await toggleSectionHeader("todoist")
    await wrapper!.setProps({ todoistError: "Could not complete the task." })
    const peek = section("todoist").get('[data-testid="rail-section-peek"]')
    expect(peek.get('[role="status"]').text()).toBe("Could not complete the task. · Expand")
    const describedBy = wrapper!.get('[data-testid="rail-section-toggle-todoist"]').attributes("aria-describedby")
    expect(describedBy).toBe(peek.attributes("id"))
    expect(section("todoist").classes()).toContain("has-error")
  })

  it("announces a first load on a collapsed task section", async () => {
    localStorage.setItem(EXTERNAL_RAIL_COLLAPSED_KEY, JSON.stringify({ todoist: true }))
    mountRail({ todoistLoading: true })
    const peek = section("todoist").get('[data-testid="rail-section-peek"] [aria-live="polite"]')
    expect(peek.text()).toBe("Loading…")
  })
})

const TODAY = "2026-08-22"

function event(overrides: Partial<NormalizedEvent>): NormalizedEvent {
  return {
    title: "Event",
    start: `${TODAY}T10:00:00Z`,
    end: `${TODAY}T11:00:00Z`,
    calendar_name: "Home",
    all_day: false,
    external_uid: overrides.title ?? "uid",
    account_label: "",
    ...overrides,
  }
}

function mountCalendars(props: Record<string, unknown> = {}) {
  localStorage.setItem(EXTERNAL_RAIL_COLLAPSED_KEY, JSON.stringify({ calendars: true }))
  return mountRail({ showTodoist: false, showCalendars: true, externalConnected: true, todayDate: TODAY, timeZone: "UTC", ...props })
}

function calendarCounter() {
  return wrapper!.get('[data-testid="calendar-summary-counter"]').text()
}

function calendarPeek() {
  return section("calendars").get('[data-testid="rail-section-peek"]').text()
}

describe("ExternalRail4a calendar summary", () => {
  it("reports loading, not an empty day, while the first load runs", () => {
    mountCalendars({ eventsLoading: true })
    expect(calendarCounter()).toBe("–")
    expect(calendarPeek()).toBe("Loading…")
  })

  it("reports unavailable, not an empty day, when every source failed", () => {
    mountCalendars({ eventErrors: [{ provider: "apple", message: "Apple Calendar service unavailable." }] })
    expect(calendarCounter()).toBe("–")
    expect(calendarPeek()).toBe("Calendars unavailable · Expand")
    expect(section("calendars").classes()).toContain("has-error")
  })

  it("says nothing is upcoming after a successful empty load", () => {
    mountCalendars()
    expect(calendarCounter()).toBe("0 upcoming")
    expect(calendarPeek()).toBe("Nothing upcoming")
  })

  it("names the next timed event and counts only events not yet past", () => {
    mountCalendars({
      nowMinutes: 12 * 60,
      events: [
        event({ title: "Standup", start: `${TODAY}T09:00:00Z`, end: `${TODAY}T09:15:00Z` }),
        event({ title: "Gym", start: `${TODAY}T16:30:00Z`, end: `${TODAY}T17:30:00Z` }),
      ],
    })
    expect(calendarCounter()).toBe("1 upcoming")
    expect(calendarPeek()).toBe("Next · 16:30 Gym")
  })

  it("says Now for an in-progress event, including an overnight one that began yesterday", () => {
    mountCalendars({
      nowMinutes: 30,
      events: [event({ title: "Night shift", start: "2026-08-21T23:00:00Z", end: `${TODAY}T02:00:00Z` })],
    })
    expect(calendarPeek()).toBe("Now · Night shift")
  })

  it("never says Now while the clock is unknown", () => {
    mountCalendars({
      nowMinutes: null,
      events: [event({ title: "Night shift", start: "2026-08-21T23:00:00Z", end: `${TODAY}T02:00:00Z` })],
    })
    expect(calendarPeek()).toBe("Next · 23:00 Night shift")
  })

  it("falls back to an all-day event and treats another date as all upcoming", () => {
    mountCalendars({
      activeDate: "2026-08-25",
      events: [event({ title: "Holiday", all_day: true, start: "2026-08-25T00:00:00Z", end: "2026-08-26T00:00:00Z" })],
    })
    expect(calendarCounter()).toBe("1 upcoming")
    expect(calendarPeek()).toBe("All day · Holiday")
  })

  it("treats timed events on a past day as past and on a future day as upcoming, whatever the clock", async () => {
    const timed = [event({ title: "Standup", start: "2026-08-25T09:00:00Z", end: "2026-08-25T09:15:00Z" })]
    mountCalendars({ activeDate: "2026-08-25", nowMinutes: 23 * 60, events: timed })
    expect(calendarCounter()).toBe("1 upcoming")
    expect(calendarPeek()).toBe("Next · 09:00 Standup")
    await wrapper!.setProps({
      activeDate: "2026-08-20",
      nowMinutes: 0,
      events: [event({ title: "Retro", start: "2026-08-20T15:00:00Z", end: "2026-08-20T16:00:00Z" })],
    })
    expect(calendarCounter()).toBe("0 upcoming")
    expect(calendarPeek()).toBe("Nothing upcoming")
  })

  it("reads Now and Next in the saved time zone, not UTC", () => {
    // 19:30Z on the 21st is 00:30 on the 22nd in Asia/Almaty (UTC+5).
    mountCalendars({
      timeZone: "Asia/Almaty",
      nowMinutes: 60,
      events: [
        event({ title: "Late call", start: "2026-08-21T19:30:00Z", end: "2026-08-21T21:00:00Z" }),
        event({ title: "Breakfast", start: "2026-08-22T03:00:00Z", end: "2026-08-22T04:00:00Z" }),
      ],
    })
    expect(calendarPeek()).toBe("Now · Late call")
    expect(calendarCounter()).toBe("2 upcoming")
  })

  it("names the next event in the saved time zone", () => {
    mountCalendars({
      timeZone: "Asia/Almaty",
      nowMinutes: 3 * 60,
      events: [event({ title: "Breakfast", start: "2026-08-22T03:00:00Z", end: "2026-08-22T04:00:00Z" })],
    })
    expect(calendarPeek()).toBe("Next · 08:00 Breakfast")
  })

  it("lets an unavailable source win over a still-loading one", () => {
    mountCalendars({
      nowMinutes: 0,
      eventsLoading: true,
      events: [event({ title: "Dentist" })],
      eventErrors: [{ provider: "apple", message: "Apple Calendar service unavailable." }],
    })
    expect(calendarPeek()).toBe("Next · 10:00 Dentist · 1 unavailable")
  })

  it("counts a Google all-account failure beside Apple rows once", () => {
    mountCalendars({
      nowMinutes: 0,
      events: [event({ title: "Dentist" })],
      eventErrors: [{ provider: "google", message: "Google Calendar service unavailable. Try again later." }],
      accountErrors: [{ account_id: 1, email: "a@example.com", error: "unavailable" }],
    })
    expect(calendarPeek()).toBe("Next · 10:00 Dentist · 1 unavailable")
    expect(section("calendars").classes()).toContain("has-error")
  })

  it("flags a partial account failure beside healthy events", () => {
    mountCalendars({
      nowMinutes: 0,
      events: [event({ title: "Dentist" })],
      accountErrors: [{ account_id: 2, email: "b@example.com", error: "reconnect_required" }],
    })
    expect(calendarPeek()).toBe("Next · 10:00 Dentist · 1 unavailable")
  })

  it("keeps saying loading while a slower provider is still loading beside present rows", () => {
    mountCalendars({ nowMinutes: 0, eventsLoading: true, events: [event({ title: "Dentist" })] })
    expect(calendarPeek()).toBe("Next · 10:00 Dentist · Loading…")
  })
})

describe("ExternalRail4a header", () => {
  it("titles today's rail Today and another day by its civil date", async () => {
    mountRail({ todayDate: "2026-08-22" })
    expect(wrapper!.get(".rail-heading strong").text()).toBe("Today")
    await wrapper!.setProps({ activeDate: "2026-08-20" })
    expect(wrapper!.get(".rail-heading strong").text()).toBe("Thu 20 Aug")
  })
})
