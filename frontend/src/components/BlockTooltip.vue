<script setup lang="ts">
// A floating panel below a timeline row (feature 0106). Both block wrappers
// clip overflow, so the panel is teleported to <body> and positioned from the
// anchor's rectangle when it opens. Used for the compact-block tooltip and
// for mutation errors that a one-line compact card cannot show.
import { onMounted, ref } from "vue"

const props = withDefaults(
  defineProps<{
    anchor: HTMLElement | null
    id: string
    role?: "tooltip" | "alert"
  }>(),
  { role: "tooltip" },
)

const style = ref<Record<string, string>>({})

function place() {
  const rect = props.anchor?.getBoundingClientRect()
  if (!rect) return
  style.value = {
    top: `${Math.round(rect.bottom + 4)}px`,
    left: `${Math.round(rect.left)}px`,
    maxWidth: `${Math.max(160, Math.round(rect.width))}px`,
  }
}

onMounted(place)
defineExpose({ place })
</script>

<template>
  <Teleport to="body">
    <div
      :id="id"
      class="block-tooltip"
      :class="`is-${role}`"
      :role="role"
      :style="style"
      :data-testid="`block-${role}`"
    >
      <slot />
    </div>
  </Teleport>
</template>

<style scoped>
.block-tooltip {
  position: fixed;
  z-index: 60;
  box-sizing: border-box;
  padding: 6px 10px;
  border: 1px solid var(--border-control, var(--border-strong));
  border-radius: 6px;
  background: var(--bg-elevated);
  color: var(--text-primary);
  box-shadow: var(--shadow-panel);
  font-family: var(--font-family-body);
  font-size: 13px;
  line-height: 18px;
  overflow-wrap: anywhere;
  pointer-events: none;
}

.block-tooltip.is-alert {
  border-color: var(--danger-border);
  background: var(--danger-surface);
  color: var(--danger-text);
}
</style>
