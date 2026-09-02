import { afterEach, describe, expect, it, vi } from "vitest"
import {
  clearFocusIndicatorShouldBeOpen,
  readFocusIndicatorShouldBeOpen,
  writeFocusIndicatorShouldBeOpen,
} from "../src/utils/focusIndicatorStorage"

describe("focus indicator restore storage", () => {
  afterEach(() => {
    vi.restoreAllMocks()
    localStorage.clear()
  })

  it("accepts only literal JSON true and safely clears intent", () => {
    expect(readFocusIndicatorShouldBeOpen()).toBe(false)
    for (const value of ["false", "1", "\"true\"", "{}", "null"]) {
      localStorage.setItem("day-forge:focus-indicator:should-be-open", value)
      expect(readFocusIndicatorShouldBeOpen()).toBe(false)
    }
    localStorage.setItem("day-forge:focus-indicator:should-be-open", "true")
    expect(readFocusIndicatorShouldBeOpen()).toBe(true)
    clearFocusIndicatorShouldBeOpen()
    expect(readFocusIndicatorShouldBeOpen()).toBe(false)
  })

  it("swallows storage failures with memory fallback", () => {
    vi.spyOn(Storage.prototype, "setItem").mockImplementation(() => { throw new Error("blocked") })
    writeFocusIndicatorShouldBeOpen(true)
    expect(readFocusIndicatorShouldBeOpen()).toBe(true)
  })

  it("reads strict false for a present-but-malformed payload, ignoring in-memory intent", () => {
    writeFocusIndicatorShouldBeOpen(true)
    localStorage.setItem("day-forge:focus-indicator:should-be-open", "{not json")
    expect(readFocusIndicatorShouldBeOpen()).toBe(false)
  })

  it("overwrites with false when removeItem fails, so a stale true is never read back", () => {
    localStorage.setItem("day-forge:focus-indicator:should-be-open", "true")
    vi.spyOn(Storage.prototype, "removeItem").mockImplementation(() => { throw new Error("blocked") })
    clearFocusIndicatorShouldBeOpen()
    expect(readFocusIndicatorShouldBeOpen()).toBe(false)
  })
})
