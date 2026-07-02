import { afterEach, describe, expect, it } from "vitest"
import {
  EXTERNAL_CALENDAR_PLACEMENT_KEY,
  readExternalCalendarPlacement,
  writeExternalCalendarPlacement,
} from "../src/utils/externalCalendarPlacementStorage"
import { clearLocalStorage } from "./helpers/storage"

afterEach(() => {
  clearLocalStorage()
})

describe("externalCalendarPlacementStorage", () => {
  it("defaults to sidebar when key is missing", () => {
    expect(readExternalCalendarPlacement()).toBe("sidebar")
  })

  it("persists center", () => {
    writeExternalCalendarPlacement("center")
    expect(localStorage.getItem(EXTERNAL_CALENDAR_PLACEMENT_KEY)).toBe(
      '"center"',
    )
    expect(readExternalCalendarPlacement()).toBe("center")
  })

  it("persists sidebar", () => {
    writeExternalCalendarPlacement("sidebar")
    expect(readExternalCalendarPlacement()).toBe("sidebar")
  })

  it("treats malformed JSON as sidebar", () => {
    localStorage.setItem(EXTERNAL_CALENDAR_PLACEMENT_KEY, "not-json")
    expect(readExternalCalendarPlacement()).toBe("sidebar")
  })

  it("treats unknown values as sidebar", () => {
    localStorage.setItem(EXTERNAL_CALENDAR_PLACEMENT_KEY, '"top"')
    expect(readExternalCalendarPlacement()).toBe("sidebar")
  })
})
