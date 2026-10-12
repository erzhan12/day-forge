<script setup lang="ts">
import { ref, onMounted } from "vue"

defineProps<{ label: string }>()
const lineRef = ref<HTMLElement | null>(null)

onMounted(() => {
  lineRef.value?.scrollIntoView({ behavior: "smooth", block: "center" })
})
</script>

<template>
  <div ref="lineRef" class="now-line">
    <span class="now-label">{{ label }}</span>
    <div class="now-rule" />
  </div>
</template>

<style scoped>
.now-line {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 0 0;
  margin: 4px 0;
}

.now-label {
  font-size: 11px;
  font-weight: 600;
  color: #ef4444;
  white-space: nowrap;
}

.now-rule {
  flex: 1;
  height: 2px;
  background: #ef4444;
  border-radius: 1px;
}
</style>
