import { nextTick, onMounted, onUnmounted, ref, watch, type Ref } from "vue"

import {
  SETTINGS_TOPICS,
  resolveSettingsTopicFromHash,
  type SettingsTopic,
  type SettingsTopicId,
} from "../utils/settingsTopics"

interface SettingsTopicState {
  activeTopic: Ref<SettingsTopicId>
  topics: readonly SettingsTopic[]
  setTopic: (id: SettingsTopicId) => void
  markKeyboardIntent: () => void
}

export function useSettingsTopic(): SettingsTopicState {
  const activeTopic = ref<SettingsTopicId>(
    resolveSettingsTopicFromHash(window.location.hash),
  )
  let keyboardIntent = false

  function syncFromHash(): void {
    activeTopic.value = resolveSettingsTopicFromHash(window.location.hash)
  }

  function setTopic(id: SettingsTopicId): void {
    const topic = SETTINGS_TOPICS.find((candidate) => candidate.id === id)
    if (!topic) return

    activeTopic.value = topic.id
    const nextHash = `#${topic.hash}`
    if (window.location.hash !== nextHash) {
      window.location.hash = nextHash
    }
  }

  function markKeyboardIntent(): void {
    keyboardIntent = true
  }

  watch(activeTopic, (id) => {
    const shouldFocus = keyboardIntent
    keyboardIntent = false
    void nextTick(() => {
      const heading = document.getElementById(`settings-topic-${id}`)
      if (heading && typeof heading.scrollIntoView === "function") {
        // Headings use .settings-topic-heading { scroll-margin-top } so
        // block:"start" clears the sticky mobile topic <select>.
        heading.scrollIntoView({ block: "start" })
      }
      if (shouldFocus) heading?.focus()
    })
  })

  onMounted(() => {
    window.addEventListener("hashchange", syncFromHash)
  })

  onUnmounted(() => {
    window.removeEventListener("hashchange", syncFromHash)
  })

  return {
    activeTopic,
    topics: SETTINGS_TOPICS,
    setTopic,
    markKeyboardIntent,
  }
}
