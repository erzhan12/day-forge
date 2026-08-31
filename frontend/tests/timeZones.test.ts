import { afterEach, describe, expect, it, vi } from "vitest"
import { browserTimeZone, timeZoneOptions } from "../src/utils/timeZones"

describe("timeZones", () => {
  afterEach(() => {
    vi.restoreAllMocks()
    vi.unstubAllGlobals()
  })

  it("detects the browser timezone and safely handles failures", () => {
    expect(browserTimeZone()).toBe(Intl.DateTimeFormat().resolvedOptions().timeZone)
    vi.spyOn(Intl, "DateTimeFormat").mockImplementation(() => { throw new Error("no intl") })
    expect(browserTimeZone()).toBeNull()
  })

  it("treats an empty browser timezone as no detection", () => {
    vi.spyOn(Intl, "DateTimeFormat").mockImplementation(() => (
      { resolvedOptions: () => ({ timeZone: "" }) } as Intl.DateTimeFormat
    ))
    expect(browserTimeZone()).toBeNull()
  })

  it("provides sorted unique zones including known values", () => {
    expect(timeZoneOptions("Asia/Almaty", "Europe/Berlin")).toEqual(
      expect.arrayContaining(["UTC", "Asia/Almaty", "Europe/Berlin"]),
    )
  })

  it("falls back to sorted, deduplicated known zones without supportedValuesOf", () => {
    vi.stubGlobal("Intl", Object.assign(Object.create(Intl), { supportedValuesOf: undefined }))
    expect(timeZoneOptions("Asia/Almaty", "UTC")).toEqual(["Asia/Almaty", "UTC"])
  })
})
