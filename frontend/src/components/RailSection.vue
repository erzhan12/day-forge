<script setup lang="ts">
// Collapsible section of the Dark 4a sources rail (feature 0105). The whole
// header row is one button. Collapsed, the section becomes a framed card that
// keeps the title, counter and (for task sections) the progress bar, plus an
// optional one-line peek; the body is `inert` so its controls leave the Tab
// order and the accessibility tree. Expanded sections are flat.
import { computed, useSlots } from "vue"

const props = withDefaults(
  defineProps<{
    sectionId: string
    title: string
    counter: string
    // Spoken instead of the terse visual counter ("2 / 4").
    counterLabel?: string
    counterTestId?: string
    // `null` renders no bar (calendars).
    percent?: number | null
    color?: string
    hasError?: boolean
  }>(),
  { counterLabel: undefined, counterTestId: undefined, percent: null, color: "var(--accent)", hasError: false },
)

const collapsed = defineModel<boolean>("collapsed", { required: true })
const slots = useSlots()

const bodyId = computed(() => `rail-section-body-${props.sectionId}`)
const peekId = computed(() => `rail-section-peek-${props.sectionId}`)
// Not a computed: slot presence is not reactive, so check on every render.
function showPeek(): boolean {
  return collapsed.value && Boolean(slots.peek)
}
const barWidth = computed(() => `${Math.min(100, Math.max(0, props.percent ?? 0))}%`)

function toggle() {
  collapsed.value = !collapsed.value
}
</script>

<template>
  <section
    class="rail-section"
    :class="{ collapsed, 'has-error': hasError }"
    :data-section="sectionId"
    :style="{ '--section-color': color }"
  >
    <button
      type="button"
      class="rail-section-header"
      :aria-expanded="!collapsed"
      :aria-controls="bodyId"
      :aria-describedby="showPeek() ? peekId : undefined"
      :data-testid="`rail-section-toggle-${sectionId}`"
      @click="toggle"
    >
      <svg class="chevron" viewBox="0 0 16 16" aria-hidden="true">
        <path d="M4 6l4 4 4-4" fill="none" stroke="currentColor" stroke-width="1.6" stroke-linecap="round" stroke-linejoin="round" />
      </svg>
      <span class="marker" aria-hidden="true"><slot name="marker"><span class="dot" /></slot></span>
      <span class="title">{{ title }}</span>
      <span class="counter" :data-testid="counterTestId" :aria-hidden="counterLabel ? 'true' : undefined">{{ counter }}</span>
      <span v-if="counterLabel" class="rail-sr-only">{{ counterLabel }}</span>
    </button>
    <div v-if="percent !== null" class="bar" aria-hidden="true"><i :style="{ width: barWidth }" /></div>
    <div v-if="showPeek()" :id="peekId" class="peek" data-testid="rail-section-peek"><slot name="peek" /></div>
    <!-- `|| undefined` removes the attribute when expanded: where `inert` is not
         a DOM property Vue would otherwise write inert="false", which is still inert. -->
    <div :id="bodyId" class="body" :inert="collapsed || undefined" data-testid="rail-section-body">
      <div class="body-inner"><slot /></div>
    </div>
  </section>
</template>

<style scoped>
.rail-section {
  flex: 0 0 auto;
  margin: 0 8px;
  border: 1px solid transparent;
  border-radius: 10px;
  transition: background-color 160ms ease, border-color 160ms ease;
}

.rail-section + .rail-section {
  margin-top: 4px;
}

/* Adjacent expanded sections share one hairline; collapsed ones are cards. */
.rail-section:not(.collapsed) + .rail-section:not(.collapsed) {
  border-top-color: var(--border);
  border-radius: 0;
}

.rail-section.collapsed {
  background: var(--bg-elevated);
  border-color: var(--border-strong);
}

.rail-section-header {
  display: flex;
  align-items: center;
  gap: 8px;
  width: 100%;
  min-height: 36px;
  padding: 10px 6px 8px;
  border: 0;
  border-radius: 8px;
  background: transparent;
  color: var(--text-primary);
  font: inherit;
  font-size: 13px;
  text-align: left;
  cursor: pointer;
}

.rail-section-header:focus {
  outline: none;
}

.rail-section-header:focus-visible {
  box-shadow: 0 0 0 2px var(--focus-ring);
}

.chevron {
  width: 14px;
  height: 14px;
  flex-shrink: 0;
  color: var(--text-secondary);
  transition: transform 160ms ease;
}

.rail-section-header:hover .chevron {
  color: var(--text-primary);
}

.collapsed .chevron {
  transform: rotate(-90deg);
}

.marker {
  display: inline-flex;
  align-items: center;
  flex-shrink: 0;
  color: var(--text-secondary);
}

.dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  background: var(--section-color);
}

.title {
  font-weight: 600;
  min-width: 0;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.counter {
  margin-left: auto;
  flex-shrink: 0;
  font-size: 13px;
  color: var(--text-secondary);
  font-variant-numeric: tabular-nums;
}

.has-error .counter {
  color: var(--danger-text);
}

.bar {
  height: 3px;
  margin: 0 6px 8px;
  border-radius: 2px;
  background: color-mix(in oklab, var(--border-strong) 80%, transparent);
  overflow: hidden;
}

.bar i {
  display: block;
  height: 100%;
  background: var(--section-color);
  transition: width 200ms ease;
}

.peek {
  padding: 0 6px 10px 28px;
  font-size: 13px;
  color: var(--text-secondary);
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.has-error .peek {
  color: var(--danger-text);
}

.body {
  display: grid;
  grid-template-rows: 1fr;
  transition: grid-template-rows 180ms ease;
}

.collapsed .body {
  grid-template-rows: 0fr;
}

.body-inner {
  min-height: 0;
  overflow: hidden;
}

.rail-sr-only {
  position: absolute;
  width: 1px;
  height: 1px;
  padding: 0;
  margin: -1px;
  overflow: hidden;
  clip: rect(0, 0, 0, 0);
  white-space: nowrap;
  border: 0;
}

@media (forced-colors: active) {
  .rail-section-header:focus-visible {
    outline: 2px solid CanvasText;
    outline-offset: -2px;
  }
}

@media (prefers-reduced-motion: reduce) {
  .rail-section,
  .chevron,
  .bar i,
  .body {
    transition: none;
  }
}
</style>
