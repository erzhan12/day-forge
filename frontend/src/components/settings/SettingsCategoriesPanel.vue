<script setup lang="ts">
import { ref } from "vue"
import type { UserCategory } from "../../types"
import { categoryPalette } from "../../utils/categoryPalette"
import { orderedCategories } from "../../utils/categories"
import { useCategories } from "../../composables/useCategories"

const props = withDefaults(defineProps<{ categories?: UserCategory[] }>(), {
  categories: () => [],
})

const api = useCategories()
const label = ref("")
const newColor = ref("blue")
const error = ref("")

function catError(v: string | string[] | undefined, fallback: string): string {
  const raw = Array.isArray(v) ? v[0] : v
  return raw ?? fallback
}

async function add() {
  const result = await api.create(label.value, newColor.value)
  if (result.ok) {
    error.value = ""
    label.value = ""
    newColor.value = "blue"
    api.refresh()
  } else {
    error.value = catError(result.errors?.category, "Could not add category")
  }
}

async function update(id: number, data: Record<string, unknown>) {
  const result = await api.update(id, data)
  if (result.ok) {
    error.value = ""
    api.refresh()
  } else {
    error.value = catError(result.errors?.category, "Could not save category")
  }
}

async function remove(category: UserCategory) {
  if (category.is_sink || !confirm(`Delete ${category.label}?`)) return
  const result = await api.remove(category.id)
  if (result.ok) {
    error.value = ""
    api.refresh(true)
  } else {
    error.value = catError(result.errors?.category, "Could not delete")
  }
}

async function reorder(id: number, otherId: number) {
  const result = await api.swap(id, otherId)
  if (result.ok) {
    error.value = ""
    api.refresh()
  } else {
    error.value = catError(result.errors?.category, "Could not reorder")
  }
}
</script>

<template>
  <section class="settings-panel">
    <h2 id="settings-topic-categories" class="settings-topic-heading" tabindex="-1">
      Categories
    </h2>
    <p v-if="error" class="error-text">{{ error }}</p>

    <div
      v-for="(category, index) in orderedCategories(props.categories)"
      :key="category.id"
      class="category-row"
    >
      <span class="swatch" :style="{ background: categoryPalette[category.color_id] }" />
      <input
        :value="category.label"
        @change="update(category.id, { label: ($event.target as HTMLInputElement).value })"
      />
      <select
        :value="category.color_id"
        @change="update(category.id, { color_id: ($event.target as HTMLSelectElement).value })"
      >
        <option v-for="(_, id) in categoryPalette" :key="id" :value="id">{{ id }}</option>
      </select>
      <button @click="update(category.id, { is_new_block_default: true })">
        {{ category.is_new_block_default ? "Default" : "Set default" }}
      </button>
      <button
        :disabled="index === 0"
        @click="reorder(category.id, orderedCategories(props.categories)[index - 1].id)"
      >
        ↑
      </button>
      <button
        :disabled="index === props.categories.length - 1"
        @click="reorder(category.id, orderedCategories(props.categories)[index + 1].id)"
      >
        ↓
      </button>
      <button v-if="!category.is_sink" @click="remove(category)">Delete</button>
      <span v-else>Sink</span>
    </div>

    <form @submit.prevent="add">
      <input v-model="label" placeholder="New category" />
      <select v-model="newColor" aria-label="New category color">
        <option v-for="(_, id) in categoryPalette" :key="id" :value="id">{{ id }}</option>
      </select>
      <button :disabled="props.categories.length >= 8">Add</button>
    </form>
  </section>
</template>

<style scoped>
.category-row {
  display: flex;
  gap: 8px;
  align-items: center;
  margin: 8px 0;
}
.swatch {
  width: 18px;
  height: 18px;
  border-radius: 4px;
}
.error-text {
  color: var(--danger, #b91c1c);
}
</style>
