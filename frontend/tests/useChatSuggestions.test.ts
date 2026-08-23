import { beforeEach, describe, expect, it, vi } from "vitest"

// Controllable usePage() stand-in: each test sets `pageState.props` to the
// shape it wants to exercise. Pins the runtime optional-chaining guard in
// useChatSuggestions that keeps prop-less mounts from throwing.
const pageState: { props: unknown } = { props: undefined }
vi.mock("@inertiajs/vue3", () => ({
  usePage: () => pageState,
}))

import { useChatSuggestions } from "../src/composables/useChatSuggestions"
import { DEFAULT_CHAT_SUGGESTIONS } from "../src/utils/chatSuggestions"

describe("useChatSuggestions", () => {
  beforeEach(() => {
    pageState.props = undefined
  })

  it("falls back to defaults when page props are absent", () => {
    pageState.props = undefined
    expect(useChatSuggestions().value).toEqual(DEFAULT_CHAT_SUGGESTIONS)
  })

  it("falls back to defaults when ui_preferences is undefined", () => {
    pageState.props = { ui_preferences: undefined }
    expect(useChatSuggestions().value).toEqual(DEFAULT_CHAT_SUGGESTIONS)
  })

  it("resolves saved suggestions in order", () => {
    pageState.props = { ui_preferences: { chat_suggestions: ["x", "y"] } }
    expect(useChatSuggestions().value).toEqual(["x", "y"])
  })
})
