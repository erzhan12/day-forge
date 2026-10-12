import type { UserCategory } from "../types"

const colorIds = new Set(["blue", "violet", "emerald", "gray", "amber", "rose", "cyan", "indigo"])

// Authenticated page responses always include a seeded catalog. A missing or
// malformed prop is a response error, not permission to invent category IDs.
export function hasValidCategoryCatalog(value: unknown): value is UserCategory[] {
  if (!Array.isArray(value) || value.length === 0 || value.length > 8) return false
  const ids = new Set<number>()
  const slugs = new Set<string>()
  let sinks = 0
  let defaults = 0
  for (const row of value) {
    if (!row || typeof row !== "object"
      || !Number.isInteger(row.id) || row.id <= 0
      || typeof row.slug !== "string" || !row.slug.trim()
      || typeof row.label !== "string" || !row.label.trim()
      || !colorIds.has(row.color_id)
      || !Number.isInteger(row.sort_order)
      || typeof row.is_sink !== "boolean"
      || typeof row.is_new_block_default !== "boolean"
      || ids.has(row.id) || slugs.has(row.slug)) return false
    ids.add(row.id)
    slugs.add(row.slug)
    if (row.is_sink) sinks++
    if (row.is_new_block_default) defaults++
  }
  return sinks === 1 && defaults === 1
}

export const orderedCategories = (categories?: UserCategory[]) => [...(categories ?? [])].sort((a, b) => a.sort_order - b.sort_order || a.id - b.id)
export const sinkCategory = (categories?: UserCategory[]) => {
  const ordered = orderedCategories(categories)
  const sink = ordered.find((item) => item.is_sink)
  if (sink) return sink
  return undefined
}
export const defaultCategory = (categories?: UserCategory[]) => orderedCategories(categories).find((item) => item.is_new_block_default) ?? sinkCategory(categories)
export function effectiveCategory(slug: string, categories?: UserCategory[]): UserCategory | undefined {
  return (categories?.find((item) => item.slug === slug)) ?? sinkCategory(categories)
}
