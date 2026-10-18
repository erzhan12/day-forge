<script setup lang="ts">
import FrontendReleaseNotice from "./FrontendReleaseNotice.vue"
import { provideFocusIndicatorController } from "../composables/useFocusIndicatorController"
import { provideScheduleWriteCoordinator } from "../composables/scheduleWriteCoordinator"

provideScheduleWriteCoordinator()
provideFocusIndicatorController()
</script>

<template><FrontendReleaseNotice /><slot /></template>
