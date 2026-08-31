import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"

let storage: typeof import("../src/utils/timeZoneMismatchStorage")

beforeEach(async () => {
  localStorage.clear()
  vi.resetModules()
  storage = await import("../src/utils/timeZoneMismatchStorage")
})

afterEach(() => vi.unstubAllGlobals())

describe("time zone mismatch storage", () => {
  it("records exact IANA values independently", () => {
    storage.markTimeZoneHandled("Asia/Calcutta")
    expect(storage.isTimeZoneHandled("Asia/Calcutta")).toBe(true)
    expect(storage.isTimeZoneHandled("Asia/Kolkata")).toBe(false)
  })

  it("swallows malformed stored JSON as not handled", () => {
    localStorage.setItem(storage.TIME_ZONE_MISMATCH_STORAGE_KEY, "{")
    expect(storage.isTimeZoneHandled("Asia/Almaty")).toBe(false)
  })

  it("swallows localStorage getItem and setItem failures", () => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => { throw new Error("read blocked") }),
      setItem: vi.fn(() => { throw new Error("write blocked") }),
    })
    expect(() => storage.markTimeZoneHandled("Asia/Almaty")).not.toThrow()
    expect(storage.isTimeZoneHandled("Europe/Berlin")).toBe(false)
  })

  it("retains dismissals in memory when localStorage fails", () => {
    vi.stubGlobal("localStorage", {
      getItem: vi.fn(() => { throw new Error("read blocked") }),
      setItem: vi.fn(() => { throw new Error("write blocked") }),
    })
    storage.markTimeZoneHandled("Asia/Almaty")
    expect(storage.isTimeZoneHandled("Asia/Almaty")).toBe(true)
  })
})
