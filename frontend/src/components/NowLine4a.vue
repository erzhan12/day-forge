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
.now-line-4a { display:flex; align-items:center; gap:8px; color:var(--accent); font-size:13px; line-height:16px; font-weight:600; font-variant-numeric:tabular-nums; pointer-events:none; }
.now-line-4a span { width:calc(var(--timeline-4a-axis-gutter, 42px) - 8px); flex-shrink:0; text-align:right; }
.now-line-4a i { height:2px; flex:1; background:var(--accent); border-radius:2px; }
</style>
