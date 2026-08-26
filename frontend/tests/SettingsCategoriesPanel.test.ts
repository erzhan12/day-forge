import { describe, it, expect, vi, beforeEach } from "vitest"
import { mount } from "@vue/test-utils"

// The panel's API composable talks to fetch + Inertia's router; mock it so the
// test drives the component's own logic (ordering, sink/default markers, cap,
// delete confirmation) without a backend.
const api = {
  create: vi.fn(async () => ({ ok: true, data: {} })),
  update: vi.fn(async () => ({ ok: true, data: {} })),
  remove: vi.fn(async () => ({ ok: true, data: {} })),
  swap: vi.fn(async () => ({ ok: true, data: {} })),
  refresh: vi.fn(),
}
vi.mock("../src/composables/useCategories", () => ({ useCategories: () => api }))

import SettingsCategoriesPanel from "../src/components/settings/SettingsCategoriesPanel.vue"
import type { UserCategory } from "../src/types"

function cat(over: Partial<UserCategory>): UserCategory {
  return {
    id: 1, slug: "work", label: "Work", color_id: "blue",
    sort_order: 0, is_sink: false, is_new_block_default: false, ...over,
  } as UserCategory
}

const SEED: UserCategory[] = [
  cat({ id: 1, slug: "work", label: "Work", sort_order: 0, is_new_block_default: true }),
  cat({ id: 2, slug: "personal", label: "Personal", color_id: "violet", sort_order: 1 }),
  cat({ id: 3, slug: "health", label: "Health", color_id: "emerald", sort_order: 2 }),
  cat({ id: 4, slug: "other", label: "Other", color_id: "gray", sort_order: 3, is_sink: true }),
]

beforeEach(() => {
  vi.clearAllMocks()
  vi.stubGlobal("confirm", vi.fn(() => true))
})

describe("SettingsCategoriesPanel", () => {
  it("renders one row per category in sort_order", () => {
    // Shuffle input to prove the component sorts, not the caller.
    const shuffled = [SEED[2], SEED[0], SEED[3], SEED[1]]
    const wrapper = mount(SettingsCategoriesPanel, { props: { categories: shuffled } })
    const rows = wrapper.findAll(".category-row")
    expect(rows.length).toBe(4)
    const labels = rows.map((r) => (r.find("input").element as HTMLInputElement).value)
    expect(labels).toEqual(["Work", "Personal", "Health", "Other"])
  })

  it("shows the default marker on the new-block-default row", () => {
    const wrapper = mount(SettingsCategoriesPanel, { props: { categories: SEED } })
    const rows = wrapper.findAll(".category-row")
    expect(rows[0].text()).toContain("Default")
    expect(rows[1].text()).toContain("Set default")
  })

  it("hides Delete on the sink and shows a Sink marker instead", () => {
    const wrapper = mount(SettingsCategoriesPanel, { props: { categories: SEED } })
    const rows = wrapper.findAll(".category-row")
    // Non-sink rows have a Delete button.
    expect(rows[0].findAll("button").some((b) => b.text() === "Delete")).toBe(true)
    // Sink row (Other) has no Delete button, shows "Sink".
    expect(rows[3].findAll("button").some((b) => b.text() === "Delete")).toBe(false)
    expect(rows[3].text()).toContain("Sink")
  })

  it("disables Add at the eight-category cap", () => {
    const eight = Array.from({ length: 8 }, (_, i) =>
      cat({ id: i + 1, slug: `c${i}`, label: `C${i}`, sort_order: i, is_sink: i === 7 }),
    )
    const wrapper = mount(SettingsCategoriesPanel, { props: { categories: eight } })
    const addBtn = wrapper.findAll("button").find((b) => b.text() === "Add")!
    expect(addBtn.attributes("disabled")).toBeDefined()
  })

  it("keeps Add enabled below the cap", () => {
    const wrapper = mount(SettingsCategoriesPanel, { props: { categories: SEED } })
    const addBtn = wrapper.findAll("button").find((b) => b.text() === "Add")!
    expect(addBtn.attributes("disabled")).toBeUndefined()
  })

  it("deletes a non-sink category after confirmation and refreshes props", async () => {
    const wrapper = mount(SettingsCategoriesPanel, { props: { categories: SEED } })
    const deleteBtn = wrapper.findAll(".category-row")[1].findAll("button")
      .find((b) => b.text() === "Delete")!
    await deleteBtn.trigger("click")
    expect(api.remove).toHaveBeenCalledWith(2)
    expect(api.refresh).toHaveBeenCalledWith(true)
  })

  it("surfaces an inline error when the API rejects an add", async () => {
    api.create.mockResolvedValueOnce({ ok: false, errors: { category: "Nope" } })
    const wrapper = mount(SettingsCategoriesPanel, { props: { categories: SEED } })
    await wrapper.find("form").trigger("submit")
    await Promise.resolve()
    expect(wrapper.find(".error-text").text()).toBe("Nope")
  })
})
