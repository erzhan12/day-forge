<script setup lang="ts">
// Block row of the Dark 4a phone list (feature 0113, SPEC 11.3): always
// 52 px, one line, category stripe, no end time. The functional block is
// reused with `mobile`, so completion, inline title edit, delete and the
// long-press tooltip keep one implementation.
import { ref, watch } from "vue"
import type { TimeBlock, UserCategory } from "../types"
import TimeBlockClassic from "./TimeBlock.vue"
import EditBlockSheet from "./EditBlockSheet.vue"
import { getCategoryColor } from "../utils/categoryColors"

const props = defineProps<{
  block: TimeBlock
  date: string
  categories?: UserCategory[]
}>()

// A tap on the row outside its controls opens the title-only edit sheet.
const editing = ref(false)
// The sheet is teleported to <body>, but a stubbed or inline sheet must not reopen itself.
const CONTROLS = ".check-hit, .delete-btn, .drag-handle, [data-testid=\"sheet-backdrop\"]"

function onRowClick(event: MouseEvent): void {
  const target = event.target
  if (target instanceof Element && target.closest(CONTROLS)) return
  editing.value = true
}

// The sheet belongs to the block and day it was opened for.
watch([() => props.block.id, () => props.date], () => { editing.value = false })
</script>

<template>
  <div
    class="mobile-block-row"
    :style="{ '--category-color': getCategoryColor(block.category, undefined, props.categories) }"
    data-testid="mobile-block-row"
    @click="onRowClick"
  >
    <TimeBlockClassic
      :block="props.block"
      :date="props.date"
      :categories="props.categories"
      tooltip
      mobile
    />
    <EditBlockSheet
      v-if="editing"
      :block="props.block"
      :date="props.date"
      @close="editing = false"
    />
  </div>
</template>

<style scoped>
@media (max-width: 640px) {
  html[data-theme="dark_4a"] .mobile-block-row {
    box-sizing: border-box;
    height: 52px;
    border-left: 3px solid var(--category-color);
    border-radius: 8px;
    overflow: hidden;
  }

  html[data-theme="dark_4a"] .mobile-block-row :deep(.time-block) {
    height: 52px;
    padding: 0 4px 0 32px;
    background: #232428;
    border: 1px solid #34363b;
    border-left: 0;
    border-radius: 0 8px 8px 0;
    box-shadow: none;
    opacity: 1;
  }

  html[data-theme="dark_4a"] .mobile-block-row :deep(.block-row) {
    gap: 6px;
  }

  /* The grip is visual only until touch drag lands; it must not trap scroll. */
  html[data-theme="dark_4a"] .mobile-block-row :deep(.drag-handle) {
    left: 8px;
    width: 20px;
    color: #6b7280;
    font-size: 16px;
    cursor: default;
    touch-action: auto;
  }

  /* 20 px checkbox with a 44 px hit area that overlaps its neighbours. */
  html[data-theme="dark_4a"] .mobile-block-row :deep(.check-hit) {
    position: relative;
    z-index: 1;
    display: inline-flex;
    flex-shrink: 0;
    align-items: center;
    justify-content: center;
    width: 44px;
    height: 44px;
    margin: 0 -12px;
    cursor: pointer;
  }

  html[data-theme="dark_4a"] .mobile-block-row :deep(.df-checkbox) {
    width: 20px;
    height: 20px;
    background-size: 14px 14px;
    border: 1.5px solid #6a6e75;
  }

  html[data-theme="dark_4a"] .mobile-block-row :deep(.df-checkbox:checked) {
    border-color: var(--checkbox-color, var(--accent));
  }

  html[data-theme="dark_4a"] .mobile-block-row :deep(.time-badge),
  html[data-theme="dark_4a"] .mobile-block-row :deep(.duration) {
    display: inline-block;
    flex-shrink: 0;
    font-size: 13px;
    font-weight: 500;
    color: #9ca3af;
    font-variant-numeric: tabular-nums;
  }

  html[data-theme="dark_4a"] .mobile-block-row :deep(.time-badge) {
    width: 38px;
  }

  html[data-theme="dark_4a"] .mobile-block-row :deep(.duration) {
    width: 36px;
  }

  html[data-theme="dark_4a"] .mobile-block-row :deep(.title),
  html[data-theme="dark_4a"] .mobile-block-row :deep(.title-input) {
    font-size: 16px;
    font-weight: 600;
    color: #e5e7eb;
  }

  html[data-theme="dark_4a"] .mobile-block-row :deep(.title-input) {
    box-sizing: border-box;
    height: 36px;
    background: #1f2023;
    border: 1px solid #6a6e75;
    border-radius: 8px;
  }

  html[data-theme="dark_4a"] .mobile-block-row :deep(.title-completed) {
    color: #9ca3af;
    text-decoration: line-through;
  }

  html[data-theme="dark_4a"] .mobile-block-row :deep(.delete-btn) {
    width: 44px;
    height: 44px;
    border-radius: 8px;
    font-size: 20px;
    color: #9ca3af;
  }
}
</style>
