<template>
  <section class="settings-panel">
    <h2 id="settings-topic-ai-assistant" class="settings-topic-heading" tabindex="-1">AI Assistant</h2>
    <p>AI quick-input preferences will appear here.</p>
  </section>
</template>

<style scoped>
.settings-panel { display: flex; flex-direction: column; gap: 8px; }
h2, p { margin: 0; }
h2 { color: var(--text-primary); }
p { color: var(--text-muted); font-size: 13px; }
h2:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
</style>
