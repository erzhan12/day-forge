import { describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"

const createRule = vi.fn().mockResolvedValue({ ok: true })
const updateRule = vi.fn().mockResolvedValue({ ok: true })
const deleteRule = vi.fn().mockResolvedValue({ ok: true })

vi.mock("../src/composables/useRules", () => ({
  useRules: () => ({ createRule, updateRule, deleteRule }),
}))

import RulesList from "../src/components/RulesList.vue"
import type { Rule } from "../src/types"

function rule(id: number, text: string, priority: number): Rule {
  return { id, text, is_active: true, priority }
}

function mountList(rules: Rule[]) {
  return mount(RulesList, { props: { rules } })
}

function arrowButtons(wrapper: ReturnType<typeof mountList>) {
  return wrapper.findAll("button.arrow-btn")
}

describe("RulesList", () => {
  it("explains disabled reorder arrows when there is only one rule", () => {
    const wrapper = mountList([rule(1, "Only rule", 0)])

    const arrows = arrowButtons(wrapper)
    expect(arrows).toHaveLength(2)
    for (const arrow of arrows) {
      expect(arrow.attributes("disabled")).toBeDefined()
      expect(arrow.attributes("title")).toBe("Add another rule to reorder")
    }
  })

  it("does not show the single-rule tooltip when rules can be reordered", () => {
    const wrapper = mountList([
      rule(2, "Top rule", 1),
      rule(1, "Bottom rule", 0),
    ])

    for (const arrow of arrowButtons(wrapper)) {
      expect(arrow.attributes("title")).toBeUndefined()
    }
  })

  it("lets the backend assign priority when creating a rule", async () => {
    createRule.mockClear()
    const wrapper = mountList([])
    await wrapper.get('input[type="text"]').setValue("  New rule  ")

    await wrapper.get("form").trigger("submit")

    expect(createRule).toHaveBeenCalledOnce()
    expect(createRule).toHaveBeenCalledWith({
      text: "New rule",
      is_active: true,
    })
  })
})
