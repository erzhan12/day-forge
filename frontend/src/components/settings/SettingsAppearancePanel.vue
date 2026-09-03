<template>
  <section class="settings-panel">
    <h2 id="settings-topic-appearance" class="settings-topic-heading" tabindex="-1">Appearance</h2>
    <DesignSelector />
  </section>
</template>

<style scoped>
.settings-panel { display: flex; flex-direction: column; gap: 16px; }
h2 { margin: 0; color: var(--text-primary); }
h2:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
</style>
