import { beforeEach, describe, expect, it, vi } from "vitest"

const requestJson = vi.hoisted(() => vi.fn())

vi.mock("../src/composables/useHttp", () => ({
  requestJson,
}))

import { usePreferences } from "../src/composables/usePreferences"

describe("usePreferences", () => {
  beforeEach(() => {
    requestJson.mockReset()
  })

  it("PATCHes the exact ordered chat suggestions array", async () => {
    requestJson.mockResolvedValue({ ok: true })
    const ordered = ["Second", "First", "Third"]

    await usePreferences().saveChatSuggestions(ordered)

    expect(requestJson).toHaveBeenCalledWith(
      "/api/user/preferences/",
      "PATCH",
      { chat_suggestions: ordered },
    )
  })

  it("PATCHes the exact opacity value", async () => {
    requestJson.mockResolvedValue({ ok: true })
    await usePreferences().saveFocusIndicatorOpacity(0.42)
    expect(requestJson).toHaveBeenCalledWith(
      "/api/user/preferences/",
      "PATCH",
      { focus_indicator_opacity: 0.42 },
    )
  })
})
