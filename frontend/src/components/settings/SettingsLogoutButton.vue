<script setup lang="ts">
// Log out lives in Settings in Dark 4a only (feature 0106, owner decision 1);
// the other themes keep the Schedule footer. No schedule-scope reset runs
// here: the Schedule owner is already disposed on this page, and the root
// Login boundary clears chat recovery and the focus indicator.
import { computed } from "vue"
import { router } from "@inertiajs/vue3"
import { useActiveTheme } from "../../composables/useActiveTheme"
import { useViewport } from "../../composables/useViewport"

const props = defineProps<{
  /** Settings.vue's copy after the content: shown only below 1024 px, where
   *  SettingsNav (which holds the wide copy) is not mounted. */
  narrowOnly?: boolean
}>()

const activeTheme = useActiveTheme()
const { isWide } = useViewport()
const visible = computed(() =>
  activeTheme.value === "dark_4a" && !(props.narrowOnly && isWide.value),
)

function logout(): void {
  router.post("/accounts/logout/")
}
</script>

<template>
  <div v-if="visible" class="settings-logout">
    <button
      type="button"
      class="df-btn df-btn--secondary"
      data-testid="settings-logout"
      @click="logout"
    >
      Log out
    </button>
  </div>
</template>

<style scoped>
.settings-logout {
  margin-top: 16px;
  padding-top: 16px;
  border-top: 1px solid var(--border);
}
</style>
