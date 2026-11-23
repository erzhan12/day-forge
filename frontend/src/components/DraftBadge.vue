<script setup lang="ts">
defineProps<{
  show: boolean
}>()
</script>

<template>
  <span v-if="show" class="draft-badge" title="Edit any block to keep this draft">
    Draft — edit to keep
  </span>
</template>

<style scoped>
.draft-badge {
  display: inline-flex;
  align-items: center;
  font-size: 11px;
  text-transform: uppercase;
  letter-spacing: 0.04em;
  color: var(--warning-text);
  background: var(--warning-surface);
  border: 1px solid var(--warning-border);
  border-radius: 999px;
  padding: 2px 10px;
  margin-top: 4px;
}

/* Dark 4a text floor (feature 0106): nothing below 13 px. */
html[data-theme="dark_4a"] .draft-badge {
  font-size: 13px;
}
</style>
