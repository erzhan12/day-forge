<script setup lang="ts">
import { nextTick } from "vue"
import { useViewport } from "../../composables/useViewport"
import {
  resolveSettingsTopicFromHash,
  type SettingsTopic,
  type SettingsTopicId,
} from "../../utils/settingsTopics"

const props = defineProps<{
  activeTopic: SettingsTopicId
  topics: readonly SettingsTopic[]
  setTopic: (id: SettingsTopicId) => void
}>()

const { isWide } = useViewport()

function onTopicChange(event: Event): void {
  const id = resolveSettingsTopicFromHash(
    (event.target as HTMLSelectElement).value,
  )
  if (id === props.activeTopic) return
  props.setTopic(id)
  void nextTick(() => {
    document.getElementById(`settings-topic-${id}`)?.focus()
  })
}
</script>

<template>
  <div v-if="!isWide" class="settings-topic-select">
    <label for="settings-topic-select">Topic</label>
    <select
      id="settings-topic-select"
      :value="activeTopic"
      @change="onTopicChange"
    >
      <option v-for="topic in topics" :key="topic.id" :value="topic.id">
        {{ topic.label }}
      </option>
    </select>
  </div>
</template>

<style scoped>
.settings-topic-select {
  position: sticky;
  top: 0;
  z-index: 5;
  display: flex;
  flex-direction: column;
  gap: 5px;
  padding: 8px 0;
  background: var(--bg-page);
}

.settings-topic-select label {
  font-size: 12px;
  font-weight: 600;
  color: var(--text-secondary);
}

.settings-topic-select select {
  width: 100%;
  padding: 9px 10px;
  border: 1px solid var(--border-strong);
  border-radius: 7px;
  background: var(--bg-panel);
  color: var(--text-primary);
  font: inherit;
}
</style>
