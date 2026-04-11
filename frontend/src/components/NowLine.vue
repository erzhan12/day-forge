<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue"

const nowTime = ref(formatCurrentTime())
const lineRef = ref<HTMLElement | null>(null)
let interval: ReturnType<typeof setInterval> | null = null

function formatCurrentTime(): string {
  const now = new Date()
  const h = String(now.getHours()).padStart(2, "0")
  const m = String(now.getMinutes()).padStart(2, "0")
  return `${h}:${m}`
}

onMounted(() => {
  interval = setInterval(() => {
    nowTime.value = formatCurrentTime()
  }, 60_000)

  lineRef.value?.scrollIntoView({ behavior: "smooth", block: "center" })
})

onUnmounted(() => {
  if (interval) clearInterval(interval)
})
</script>

<template>
  <div ref="lineRef" class="now-line">
    <span class="now-label">{{ nowTime }}</span>
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
