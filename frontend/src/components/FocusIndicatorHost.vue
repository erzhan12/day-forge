<script setup lang="ts">
import { provideFocusIndicatorController } from "../composables/useFocusIndicatorController"
import { provideScheduleWriteCoordinator } from "../composables/scheduleWriteCoordinator"

provideScheduleWriteCoordinator()
provideFocusIndicatorController()
</script>

<template><slot /></template>
