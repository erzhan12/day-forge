import { describe, expect, it } from "vitest"
import {
  FOCUS_INDICATOR_OPACITY_DEFAULT,
  FOCUS_INDICATOR_OPACITY_MAX,
  FOCUS_INDICATOR_OPACITY_MIN,
  normalizeFocusIndicatorOpacity,
} from "../src/utils/focusIndicatorOpacity"

describe("focus indicator opacity", () => {
  it("uses default for malformed values and clamps finite numbers inclusively", () => {
    expect(FOCUS_INDICATOR_OPACITY_DEFAULT).toBe(0.7)
    expect(normalizeFocusIndicatorOpacity(FOCUS_INDICATOR_OPACITY_MIN)).toBe(0.2)
    expect(normalizeFocusIndicatorOpacity(FOCUS_INDICATOR_OPACITY_MAX)).toBe(1)
    expect(normalizeFocusIndicatorOpacity(-2)).toBe(0.2)
    expect(normalizeFocusIndicatorOpacity(2)).toBe(1)
    for (const bad of [true, false, null, "0.7", {}, [], NaN, Infinity]) {
      expect(normalizeFocusIndicatorOpacity(bad)).toBe(0.7)
    }
  })
})
