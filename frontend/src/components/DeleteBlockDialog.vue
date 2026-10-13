<script setup lang="ts">
import { onBeforeUnmount, onMounted, ref, useId } from "vue"

defineProps<{ title: string }>()
const emit = defineEmits<{ confirm: []; cancel: [] }>()
const dialog = ref<HTMLDialogElement | null>(null)
const headingId = useId()
const descriptionId = useId()

// A DOM dialog keeps confirmation accessible to keyboard users and browser
// automation. showModal provides focus containment and makes the page inert.
onMounted(() => dialog.value?.showModal())
onBeforeUnmount(() => dialog.value?.close())
</script>

<template>
  <Teleport to="body">
    <dialog
      ref="dialog"
      class="delete-block-dialog"
      :aria-labelledby="headingId"
      :aria-describedby="descriptionId"
      @cancel.prevent="emit('cancel')"
      @keydown.stop
    >
      <h3 :id="headingId">Delete block?</h3>
      <p :id="descriptionId">Delete “{{ title }}”? You can restore it with Undo.</p>
      <div class="dialog-actions">
        <button type="button" class="cancel-delete" autofocus @click="emit('cancel')">Cancel</button>
        <button type="button" class="confirm-delete" @click="emit('confirm')">Delete</button>
      </div>
    </dialog>
  </Teleport>
</template>

<style scoped>
.delete-block-dialog {
  box-sizing: border-box;
  width: min(420px, calc(100vw - 32px));
  max-height: calc(100dvh - 32px);
  margin: auto;
  padding: 20px;
  border: 1px solid var(--border-strong);
  border-radius: 10px;
  background: var(--bg-panel);
  color: var(--text-primary);
  box-shadow: 0 8px 30px rgba(0, 0, 0, 0.25);
  overflow-wrap: anywhere;
}

.delete-block-dialog::backdrop {
  background: rgba(0, 0, 0, 0.4);
}

h3 { margin: 0 0 12px; }
p { margin: 0 0 20px; line-height: 1.5; }
.dialog-actions { display: flex; justify-content: flex-end; gap: 8px; }
button {
  min-height: 40px;
  padding: 8px 16px;
  border: 1px solid var(--border-strong);
  border-radius: 6px;
  font: inherit;
  cursor: pointer;
}
.cancel-delete { background: var(--bg-panel); color: var(--text-primary); }
.confirm-delete { background: #dc2626; color: #fff; border-color: #dc2626; }
.confirm-delete:hover { background: #b91c1c; }
</style>
