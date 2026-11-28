<script setup lang="ts">
// "Calendars" opened from the mobile gear menu (feature 0113, SPEC 11.8 item
// 2): the calendar panel in a bottom sheet. The owner passes the panel as the
// default slot so its props and Add to schedule wiring stay in Schedule.vue.
import BottomSheet from "./BottomSheet.vue"

defineProps<{ fallbackFocus?: () => HTMLElement | null }>()
const emit = defineEmits<{ close: [] }>()
</script>

<template>
  <BottomSheet title="Calendars" :fallback-focus="fallbackFocus" @close="emit('close')">
    <slot />
  </BottomSheet>
</template>
