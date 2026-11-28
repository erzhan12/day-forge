<script setup lang="ts">
// Switch between a modal sheet (Dark 4a phone) and the content in place
// (everything else), so a component keeps one copy of its markup (feature
// 0113). In place, the slot renders exactly as if this wrapper were absent.
import BottomSheetFrame from "./BottomSheetFrame.vue"

defineProps<{
  title: string
  /** Render the slot in place instead of in a sheet. */
  inline?: boolean
  fallbackFocus?: () => HTMLElement | null
}>()
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <slot v-if="inline" />
  <Teleport v-else to="body">
    <BottomSheetFrame :title="title" :fallback-focus="fallbackFocus" @close="emit('close')">
      <slot />
    </BottomSheetFrame>
  </Teleport>
</template>
