import { describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"

const createRule = vi.fn().mockResolvedValue({ ok: true })
const updateRule = vi.fn().mockResolvedValue({ ok: true })
const swapRules = vi.fn().mockResolvedValue({ ok: true })
const deleteRule = vi.fn().mockResolvedValue({ ok: true })

vi.mock("../src/composables/useRules", () => ({
  useRules: () => ({ createRule, updateRule, swapRules, deleteRule }),
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

function upButtons(wrapper: ReturnType<typeof mountList>) {
  return wrapper.findAll('button[aria-label="Increase priority"]')
}

function downButtons(wrapper: ReturnType<typeof mountList>) {
  return wrapper.findAll('button[aria-label="Decrease priority"]')
}

describe("RulesList", () => {
  it("shows 0-based priority ranks while keeping the highest-priority rule first", () => {
    const wrapper = mountList([
      rule(2, "Highest-priority rule", 7),
      rule(1, "Lower-priority rule", 2),
    ])

    const rows = wrapper.findAll(".rule-row")
    const topBadge = rows[0].get(".priority-badge")
    const secondBadge = rows[1].get(".priority-badge")

    expect(rows[0].get(".rule-text").text()).toBe("Highest-priority rule")
    expect(topBadge.text()).toBe("0")
    expect(secondBadge.text()).toBe("1")
    expect(topBadge.attributes("title")).toContain("0 is highest")
    expect(topBadge.attributes("aria-label")).toContain("rank 0")
    expect(topBadge.attributes("aria-label")).toContain("0 is highest")
  })

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

  it("does not tooltip the legitimately-disabled arrows in a multi-rule list", () => {
    const wrapper = mountList([
      rule(3, "Top rule", 2),
      rule(2, "Middle rule", 1),
      rule(1, "Bottom rule", 0),
    ])

    const arrows = arrowButtons(wrapper)
    // Top rule's ▲ (index 0) and bottom rule's ▼ (last) are disabled but
    // must carry no tooltip — that copy is reserved for the single-rule case.
    const topUp = arrows[0]
    const bottomDown = arrows[arrows.length - 1]
    expect(topUp.attributes("disabled")).toBeDefined()
    expect(topUp.attributes("title")).toBeUndefined()
    expect(bottomDown.attributes("disabled")).toBeDefined()
    expect(bottomDown.attributes("title")).toBeUndefined()
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

  it("surfaces an error and preserves input when create fails", async () => {
    createRule.mockClear()
    createRule.mockResolvedValueOnce({
      ok: false,
      errors: { text: ["Server rejected"] },
    })
    const wrapper = mountList([])
    await wrapper.get('input[type="text"]').setValue("Keep me")

    await wrapper.get("form").trigger("submit")
    await wrapper.vm.$nextTick()

    expect(wrapper.find(".error-text").text()).not.toBe("")
    // Input preserved so the user can retry without retyping.
    expect(
      (wrapper.get('input[type="text"]').element as HTMLInputElement).value,
    ).toBe("Keep me")
  })

  it("swaps distinct priorities atomically and emits changed", async () => {
    swapRules.mockClear()
    updateRule.mockClear()
    const wrapper = mountList([
      rule(2, "Top rule", 1),
      rule(1, "Bottom rule", 0),
    ])

    await downButtons(wrapper)[0].trigger("click")

    expect(swapRules).toHaveBeenCalledOnce()
    expect(swapRules).toHaveBeenCalledWith(2, 1)
    expect(updateRule).not.toHaveBeenCalled()
    expect(wrapper.emitted("changed")).toHaveLength(1)
  })

  it("surfaces an error when an atomic priority swap fails", async () => {
    swapRules.mockReset()
    swapRules.mockResolvedValueOnce({ ok: false })
    const wrapper = mountList([
      rule(2, "Top rule", 1),
      rule(1, "Bottom rule", 0),
    ])

    await downButtons(wrapper)[0].trigger("click")
    await wrapper.vm.$nextTick()

    expect(swapRules).toHaveBeenCalledOnce()
    expect(wrapper.text()).toContain("Reorder failed")
    expect(wrapper.emitted("changed")).toBeUndefined()
    swapRules.mockResolvedValue({ ok: true })
  })

  it("nudges one row when legacy neighbours share a priority", async () => {
    swapRules.mockClear()
    updateRule.mockClear()
    const wrapper = mountList([
      rule(1, "Older", 0),
      rule(2, "Newer", 0),
    ])

    await upButtons(wrapper)[1].trigger("click")

    expect(swapRules).not.toHaveBeenCalled()
    expect(updateRule).toHaveBeenCalledOnce()
    expect(updateRule).toHaveBeenCalledWith(2, { priority: 1 })
  })

  it("surfaces an error when the equal-priority nudge PATCH fails", async () => {
    swapRules.mockClear()
    updateRule.mockClear()
    updateRule.mockResolvedValueOnce({ ok: false })
    const wrapper = mountList([rule(1, "Older", 0), rule(2, "Newer", 0)])

    await upButtons(wrapper)[1].trigger("click")
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain("Reorder failed")
    expect(wrapper.emitted("changed")).toBeUndefined()
  })
})
