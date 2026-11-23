// Feature 0106: the template editor carries the shared Dark 4a control
// classes. The rules come from the app.css skin, so the classes are inert in
// the other themes.
import { describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"

vi.mock("../src/composables/useTemplates", () => ({
  useTemplates: () => ({
    createTemplate: vi.fn(),
    saveTemplate: vi.fn(),
    deleteTemplate: vi.fn(),
  }),
}))

import TemplateEditor from "../src/components/TemplateEditor.vue"
import { makeCategories } from "./helpers/schedule"
import type { Template } from "../src/types"

const TEMPLATE: Template = {
  id: 7,
  name: "Weekday",
  type: "weekday",
  blocks: [{ title: "Deep work", start_time: "09:00", end_time: "11:00", category: "work" }],
}

describe("TemplateEditor", () => {
  it("tags fields and buttons with df-field / df-btn", () => {
    const wrapper = mount(TemplateEditor, {
      props: { template: TEMPLATE, slotType: "weekday", categories: makeCategories() },
    })
    const fields = wrapper.findAll(".input")
    expect(fields.length).toBeGreaterThanOrEqual(5)
    for (const field of fields) expect(field.classes()).toContain("df-field")

    expect(wrapper.get(".add-row-btn").classes()).toEqual(expect.arrayContaining(["df-btn", "df-btn--field"]))
    expect(wrapper.get(".row-delete-btn").classes()).toEqual(
      expect.arrayContaining(["df-btn", "df-btn--field", "df-btn--danger"]),
    )
    expect(wrapper.get(".form-actions .primary-btn").classes()).toEqual(
      expect.arrayContaining(["df-btn", "df-btn--primary"]),
    )
    expect(wrapper.get(".danger-btn").classes()).toEqual(
      expect.arrayContaining(["df-btn", "df-btn--field", "df-btn--danger"]),
    )
  })
})
