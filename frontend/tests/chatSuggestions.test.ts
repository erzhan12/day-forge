import { describe, expect, it } from "vitest"

import {
  DEFAULT_CHAT_SUGGESTIONS,
  MAX_CHAT_SUGGESTIONS,
  MAX_CHAT_SUGGESTION_CHARS,
  resolveChatSuggestions,
} from "../src/utils/chatSuggestions"

describe("chat suggestion contract", () => {
  it("pins the frontend defaults to the backend defaults", () => {
    expect(DEFAULT_CHAT_SUGGESTIONS).toEqual([
      "Plan my remaining day",
      "Add a focused work block",
      "Make room for a break",
    ])
    expect(MAX_CHAT_SUGGESTIONS).toBe(8)
    expect(MAX_CHAT_SUGGESTION_CHARS).toBe(120)
  })

  it.each([undefined, null, "not-an-array", ["valid", 2]])(
    "falls back for absent or malformed values",
    (value) => {
      expect(resolveChatSuggestions(value)).toEqual(DEFAULT_CHAT_SUGGESTIONS)
      expect(resolveChatSuggestions(value)).not.toBe(DEFAULT_CHAT_SUGGESTIONS)
    },
  )

  it("preserves custom order and returns a copy", () => {
    const saved = ["Third", "First", "Second"]
    const resolved = resolveChatSuggestions(saved)
    expect(resolved).toEqual(saved)
    expect(resolved).not.toBe(saved)
  })

  it("preserves an intentional empty list", () => {
    expect(resolveChatSuggestions([])).toEqual([])
  })
})
