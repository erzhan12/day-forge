<script setup lang="ts">
import DesktopNotificationToggle from "../DesktopNotificationToggle.vue"
import SoundNotificationToggle from "../SoundNotificationToggle.vue"
</script>

<template>
  <section class="settings-panel">
    <h2 id="settings-topic-notifications" class="settings-topic-heading" tabindex="-1">Notifications</h2>
    <SoundNotificationToggle />
    <DesktopNotificationToggle />
  </section>
</template>

<style scoped>
.settings-panel { display: flex; flex-direction: column; gap: 24px; }
h2 { margin: 0; color: var(--text-primary); }
h2:focus-visible { outline: 2px solid var(--accent); outline-offset: 4px; }
</style>
