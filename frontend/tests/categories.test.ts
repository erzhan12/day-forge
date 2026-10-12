import { describe, expect, it } from "vitest"
import { makeCategories } from "./helpers/schedule"
import { defaultCategory, hasValidCategoryCatalog, orderedCategories, sinkCategory } from "../src/utils/categories"

describe("category catalog contract", () => {
  it("does not create legacy rows when the server catalog is absent", () => {
    expect(orderedCategories()).toEqual([])
    expect(orderedCategories([])).toEqual([])
    expect(defaultCategory([])).toBeUndefined()
    expect(sinkCategory([])).toBeUndefined()
  })

  it("accepts the seeded catalog and rejects missing markers or duplicate slugs", () => {
    const seeded = makeCategories()
    expect(hasValidCategoryCatalog(seeded)).toBe(true)
    expect(hasValidCategoryCatalog([])).toBe(false)
    expect(hasValidCategoryCatalog(seeded.map((category) => ({ ...category, is_sink: false })))).toBe(false)
    expect(hasValidCategoryCatalog([seeded[0], { ...seeded[1], slug: seeded[0].slug }, ...seeded.slice(2)])).toBe(false)
    expect(hasValidCategoryCatalog([...seeded, ...Array.from({ length: 5 }, (_, index) => ({
      ...seeded[1], id: index + 5, slug: `extra-${index}`, label: `Extra ${index}`,
    }))])).toBe(false)
    expect(hasValidCategoryCatalog([{ ...seeded[0], slug: "  " }, ...seeded.slice(1)])).toBe(false)
    expect(hasValidCategoryCatalog([{ ...seeded[0], label: "  " }, ...seeded.slice(1)])).toBe(false)
  })
})
