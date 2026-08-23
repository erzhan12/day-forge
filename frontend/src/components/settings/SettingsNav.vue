<script setup lang="ts">
import { useViewport } from "../../composables/useViewport"
import type { SettingsTopic, SettingsTopicId } from "../../utils/settingsTopics"

const props = defineProps<{
  activeTopic: SettingsTopicId
  topics: readonly SettingsTopic[]
  markKeyboardIntent: () => void
}>()

const { isWide } = useViewport()

function onClick(event: MouseEvent, topic: SettingsTopic): void {
  if (props.activeTopic === topic.id) event.preventDefault()
}

function onKeydown(event: KeyboardEvent, topic: SettingsTopic): void {
  if (event.key === "Enter" && props.activeTopic !== topic.id) {
    props.markKeyboardIntent()
  }
}
</script>

<template>
  <nav v-if="isWide" class="settings-nav" aria-label="Settings topics">
    <ul>
      <li v-for="topic in topics" :key="topic.id">
        <a
          :href="`#${topic.hash}`"
          :aria-current="activeTopic === topic.id ? 'page' : undefined"
          @click="onClick($event, topic)"
          @keydown="onKeydown($event, topic)"
        >{{ topic.label }}</a>
      </li>
    </ul>
  </nav>
</template>

<style scoped>
.settings-nav {
  position: sticky;
  top: 24px;
  width: 224px;
  align-self: start;
}

.settings-nav ul {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.settings-nav a {
  display: block;
  padding: 10px 12px;
  border-left: 3px solid transparent;
  border-radius: 0 7px 7px 0;
  color: var(--text-secondary);
  text-decoration: none;
  font-size: 14px;
}

.settings-nav a:hover {
  background: var(--bg-panel);
  color: var(--text-primary);
}

.settings-nav a[aria-current="page"] {
  border-left-color: var(--accent);
  background: var(--accent-soft, var(--bg-panel));
  color: var(--text-primary);
  font-weight: 600;
}

.settings-nav a:focus-visible {
  outline: 2px solid var(--accent);
  outline-offset: 2px;
}
</style>
