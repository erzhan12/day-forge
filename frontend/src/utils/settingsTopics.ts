export type SettingsTopicId =
  | "appearance"
  | "categories"
  | "schedule"
  | "ai-assistant"
  | "notifications"
  | "integrations"
  | "templates-rules"

export interface SettingsTopic {
  id: SettingsTopicId
  label: string
  hash: string
}

export const SETTINGS_TOPICS: readonly SettingsTopic[] = [
  { id: "appearance", label: "Appearance", hash: "appearance" },
  { id: "categories", label: "Categories", hash: "categories" },
  { id: "schedule", label: "Schedule", hash: "schedule" },
  { id: "ai-assistant", label: "AI Assistant", hash: "ai-assistant" },
  { id: "notifications", label: "Notifications", hash: "notifications" },
  { id: "integrations", label: "Integrations", hash: "integrations" },
  {
    id: "templates-rules",
    label: "Templates & Rules",
    hash: "templates-rules",
  },
]

export const DEFAULT_SETTINGS_TOPIC: SettingsTopicId = "appearance"

export function resolveSettingsTopicFromHash(rawHash: string): SettingsTopicId {
  const slug = rawHash.replace(/^#/, "").trim().toLowerCase()
  return (
    SETTINGS_TOPICS.find((topic) => topic.hash === slug)?.id ??
    DEFAULT_SETTINGS_TOPIC
  )
}
