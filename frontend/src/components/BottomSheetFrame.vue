<script setup lang="ts">
// Modal bottom sheet frame of the Dark 4a phone layout (feature 0113): a
// backdrop, a titled panel with a Close button, focus in and back, Tab wrap,
// Escape, page scroll lock, and a lift above the on-screen keyboard.
import { ref, useId } from "vue"
import { useMobileDialog } from "../composables/useMobileDialog"
import { useBodyScrollLock } from "../composables/useBodyScrollLock"
import { useVisualViewportInset } from "../composables/useVisualViewportInset"

const props = defineProps<{
  title: string
  /** Where focus goes when the opener is gone from the DOM. */
  fallbackFocus?: () => HTMLElement | null
}>()
const emit = defineEmits<{ close: [] }>()

const sheet = ref<HTMLElement | null>(null)
const titleId = `sheet-title-${useId()}`
const inset = useVisualViewportInset()
useBodyScrollLock()
useMobileDialog(sheet, { onClose: () => emit("close"), fallbackFocus: props.fallbackFocus })
</script>

<template>
  <div
    class="sheet-backdrop"
    :style="{ bottom: `${inset}px` }"
    data-testid="sheet-backdrop"
    @click.self="emit('close')"
  >
    <section
      ref="sheet"
      class="sheet"
      role="dialog"
      aria-modal="true"
      :aria-labelledby="titleId"
      data-testid="bottom-sheet"
    >
      <header class="sheet-head">
        <h2 :id="titleId">{{ title }}</h2>
        <button type="button" class="df-btn df-btn--secondary" data-testid="sheet-close" @click="emit('close')">Close</button>
      </header>
      <div class="sheet-body"><slot /></div>
    </section>
  </div>
</template>

<style scoped>
@media (max-width: 640px) {
  html[data-theme="dark_4a"] .sheet-backdrop {
    position: fixed;
    top: 0;
    left: 0;
    right: 0;
    z-index: 60;
    display: flex;
    align-items: flex-end;
    background: rgba(0, 0, 0, 0.55);
  }

  html[data-theme="dark_4a"] .sheet {
    box-sizing: border-box;
    display: flex;
    flex-direction: column;
    width: 100%;
    max-height: 85dvh;
    padding-bottom: var(--safe-bottom);
    background: #1f2023;
    border-top: 1px solid #6a6e75;
    border-radius: 16px 16px 0 0;
  }

  html[data-theme="dark_4a"] .sheet-head {
    display: flex;
    align-items: center;
    justify-content: space-between;
    padding: 12px 16px;
    border-bottom: 1px solid #34363b;
  }

  html[data-theme="dark_4a"] .sheet-head h2 {
    margin: 0;
    font-size: 17px;
    font-weight: 600;
    color: #e5e7eb;
  }

  html[data-theme="dark_4a"] .sheet-body {
    overflow-y: auto;
    padding: 12px 16px 16px;
  }
}
</style>
