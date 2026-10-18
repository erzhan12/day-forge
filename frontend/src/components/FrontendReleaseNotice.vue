<script setup lang="ts">
import { useFrontendRelease } from "../composables/useFrontendRelease"
const { outdated, reload } = useFrontendRelease()
</script>

<template>
  <aside v-if="outdated" role="alert" class="release-notice" data-testid="frontend-release-notice">
    <span>The app has been updated. Reload to continue. Unsent text on this page will be lost.</span>
    <button type="button" @click="reload">Reload</button>
  </aside>
</template>

<style scoped>
.release-notice { position:sticky; top:0; z-index:100; display:flex; flex-wrap:wrap; align-items:center; justify-content:center; gap:12px; padding:12px 16px; background:#fff3cd; color:#352900; }
.release-notice button { padding:6px 14px; border:1px solid currentColor; border-radius:6px; background:transparent; color:inherit; cursor:pointer; }
</style>
