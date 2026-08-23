import { describe, expect, it } from "vitest"

import {
  DEFAULT_SETTINGS_TOPIC,
  SETTINGS_TOPICS,
  resolveSettingsTopicFromHash,
} from "../src/utils/settingsTopics"

describe("settingsTopics", () => {
  it("defines the six ordered settings topics", () => {
    expect(SETTINGS_TOPICS).toEqual([
      { id: "appearance", label: "Appearance", hash: "appearance" },
      { id: "schedule", label: "Schedule", hash: "schedule" },
      { id: "ai-assistant", label: "AI Assistant", hash: "ai-assistant" },
      { id: "notifications", label: "Notifications", hash: "notifications" },
      { id: "integrations", label: "Integrations", hash: "integrations" },
      {
        id: "templates-rules",
        label: "Templates & Rules",
        hash: "templates-rules",
      },
    ])
  })

  it("defaults to Appearance", () => {
    expect(DEFAULT_SETTINGS_TOPIC).toBe("appearance")
    expect(resolveSettingsTopicFromHash("")).toBe("appearance")
    expect(resolveSettingsTopicFromHash("#")).toBe("appearance")
  })

  it("resolves known hashes case-insensitively", () => {
    expect(resolveSettingsTopicFromHash("#integrations")).toBe("integrations")
    expect(resolveSettingsTopicFromHash("#Integrations")).toBe("integrations")
  })

  it("falls back for unknown hashes", () => {
    expect(resolveSettingsTopicFromHash("#UNKNOWN")).toBe("appearance")
  })
})
