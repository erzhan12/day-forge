<script setup lang="ts">
import { ref, onMounted } from "vue"

defineProps<{ label: string }>()
const lineRef = ref<HTMLElement | null>(null)

onMounted(() => {
  lineRef.value?.scrollIntoView({ behavior: "smooth", block: "center" })
})
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
