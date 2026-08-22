<script setup lang="ts">
import { ref, onMounted, onUnmounted } from "vue"

const lineRef = ref<HTMLElement | null>(null)
const label = ref(currentTime())
let timer: ReturnType<typeof setInterval> | null = null

function currentTime(): string {
  const now = new Date()
  return `${String(now.getHours()).padStart(2, "0")}:${String(now.getMinutes()).padStart(2, "0")}`
}

onMounted(() => {
  timer = setInterval(() => (label.value = currentTime()), 60_000)
  lineRef.value?.scrollIntoView({ behavior: "smooth", block: "center" })
})
onUnmounted(() => { if (timer) clearInterval(timer) })
</script>

<template>
  <div ref="lineRef" class="now-line-4a" data-testid="now-line-4a">
    <span>{{ label }}</span><i />
  </div>
</template>

<style scoped>
.now-line-4a { display:flex; align-items:center; gap:8px; color:oklch(0.72 0.17 30); font-size:11px; font-weight:600; pointer-events:none; }
.now-line-4a i { height:2px; flex:1; background:oklch(0.72 0.17 30); border-radius:2px; }
</style>
