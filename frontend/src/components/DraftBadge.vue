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
  color: #92400e;
  background: #fef3c7;
  border: 1px solid #fcd34d;
  border-radius: 999px;
  padding: 2px 10px;
  margin-top: 4px;
}
</style>
