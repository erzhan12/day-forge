<script setup lang="ts">
import ChatSuggestionsEditor from "./ChatSuggestionsEditor.vue"
</script>

<template>
  <section class="settings-panel">
    <h2 id="settings-topic-ai-assistant" class="settings-topic-heading" tabindex="-1">AI Assistant</h2>
    <ChatSuggestionsEditor />
  </section>
</template>

<style scoped>
.settings-panel { display: flex; flex-direction: column; gap: 16px; }
h2 { margin: 0; }
h2 { color: var(--text-primary); }
h2:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
</style>
