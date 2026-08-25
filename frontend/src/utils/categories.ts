import type { UserCategory } from "../types"

const legacyCategories: UserCategory[] = [
  { id: -1, slug: "work", label: "Work", color_id: "blue", sort_order: 0, is_sink: false, is_new_block_default: true },
  { id: -2, slug: "personal", label: "Personal", color_id: "violet", sort_order: 1, is_sink: false, is_new_block_default: false },
  { id: -3, slug: "health", label: "Health", color_id: "emerald", sort_order: 2, is_sink: false, is_new_block_default: false },
  { id: -4, slug: "other", label: "Other", color_id: "gray", sort_order: 3, is_sink: true, is_new_block_default: false },
]
export const orderedCategories = (categories?: UserCategory[]) => [...(categories?.length ? categories : legacyCategories)].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
export const sinkCategory = (categories?: UserCategory[]) => {
  const ordered = orderedCategories(categories)
  const sink = ordered.find((item) => item.is_sink)
  if (sink) return sink
  // No sink row is a malformed catalog (the backend guarantees exactly one);
  // fall back to the first row but warn rather than silently returning a
  // wrong "sink" (e.g. "work").
  console.warn("sinkCategory: no is_sink row in catalog; falling back to first row")
  return ordered[0]
}
export const defaultCategory = (categories?: UserCategory[]) => orderedCategories(categories).find((item) => item.is_new_block_default) ?? sinkCategory(categories)
export function effectiveCategory(slug: string, categories?: UserCategory[]): UserCategory | undefined {
  return (categories?.find((item) => item.slug === slug)) ?? sinkCategory(categories)
}
