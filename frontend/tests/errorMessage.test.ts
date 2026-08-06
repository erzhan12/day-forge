import { describe, it, expect } from "vitest"
import { extractErrorMessage } from "../src/utils/errorMessage"

describe("extractErrorMessage", () => {
  it("returns the fallback when errors is undefined", () => {
    expect(extractErrorMessage(undefined, "fallback")).toBe("fallback")
  })

  it("returns errors.detail when it is a string, ignoring the fallback", () => {
    expect(extractErrorMessage({ detail: "boom" }, "fallback")).toBe("boom")
  })

  it("detail wins over other keys", () => {
    expect(
      extractErrorMessage({ detail: "boom", field: ["other"] }, "fallback"),
    ).toBe("boom")
  })

  it("returns the first flattened non-empty string when detail is absent", () => {
    expect(extractErrorMessage({ field: ["boom"] }, "fallback")).toBe("boom")
  })

  it("handles a bare non-array string value (flat() leaves scalars)", () => {
    // The declared input type allows `string` values, not just `string[]`.
    expect(extractErrorMessage({ field: "boom" }, "fallback")).toBe("boom")
  })

  it("returns the fallback when errors is an empty object", () => {
    expect(extractErrorMessage({}, "fallback")).toBe("fallback")
  })

  it("returns the fallback when the only value is an empty array", () => {
    expect(extractErrorMessage({ field: [] }, "fallback")).toBe("fallback")
  })

  it("falls through to the fallback when the first value is an empty string", () => {
    expect(extractErrorMessage({ field: [""] }, "fallback")).toBe("fallback")
  })

  it("returns empty-string detail verbatim, NOT the fallback and NOT a later key", () => {
    // Empty-`detail` asymmetry: branch 2 (`typeof errors.detail === "string"`)
    // is true for "" and returns it immediately, short-circuiting the
    // `.flat()` scan. Pin this preserved behavior.
    expect(
      extractErrorMessage({ detail: "", field: ["boom"] }, "fallback"),
    ).toBe("")
  })
})
