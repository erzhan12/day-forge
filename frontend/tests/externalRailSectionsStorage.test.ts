import { afterEach, describe, expect, it, vi } from "vitest"
import {
  EXTERNAL_RAIL_COLLAPSED_KEY,
  readExternalRailCollapsed,
  writeExternalRailCollapsed,
} from "../src/utils/externalRailSectionsStorage"
import { clearLocalStorage } from "./helpers/storage"

afterEach(() => {
  vi.restoreAllMocks()
  clearLocalStorage()
})

describe("externalRailSectionsStorage", () => {
  it("defaults every section to expanded when the key is missing", () => {
    expect(readExternalRailCollapsed()).toEqual({ todoist: false, habitica: false, calendars: false })
  })

  it("round-trips the collapsed state per section", () => {
    writeExternalRailCollapsed({ todoist: true, habitica: false, calendars: true })
    expect(readExternalRailCollapsed()).toEqual({ todoist: true, habitica: false, calendars: true })
  })

  it("treats malformed JSON as all expanded", () => {
    localStorage.setItem(EXTERNAL_RAIL_COLLAPSED_KEY, "not-json")
    expect(readExternalRailCollapsed()).toEqual({ todoist: false, habitica: false, calendars: false })
  })

  it("ignores non-boolean values, arrays and unknown sections", () => {
    localStorage.setItem(EXTERNAL_RAIL_COLLAPSED_KEY, JSON.stringify({ todoist: "true", habitica: 1, calendars: true, extra: true }))
    expect(readExternalRailCollapsed()).toEqual({ todoist: false, habitica: false, calendars: true })
    localStorage.setItem(EXTERNAL_RAIL_COLLAPSED_KEY, JSON.stringify([true]))
    expect(readExternalRailCollapsed()).toEqual({ todoist: false, habitica: false, calendars: false })
  })

  it("survives a throwing localStorage on read and write", () => {
    vi.spyOn(Storage.prototype, "getItem").mockImplementation(() => { throw new Error("denied") })
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("quota") })
    expect(readExternalRailCollapsed()).toEqual({ todoist: false, habitica: false, calendars: false })
    expect(() => writeExternalRailCollapsed({ todoist: true, habitica: true, calendars: true })).not.toThrow()
  })
})
