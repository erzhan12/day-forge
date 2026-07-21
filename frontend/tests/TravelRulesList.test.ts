// TravelRulesList — reorder direction semantics.
//
// The `order` field is ASCENDING-wins: the lowest order matches first, so the
// top row is the winner. "Move up" must therefore DECREASE a rule's order.
//
// This is the opposite of templates_mgr's RulesList.bumpPriority, where "up"
// raises a priority number. Both components render an up/down arrow pair over
// a list of user-ordered rules, so a future edit that copies the sibling's
// direction logic would silently invert matching precedence here — rules would
// start winning in the reverse of the order the user sees. That failure is
// invisible in the UI until a match resolves to the wrong rule, hence this
// test pins the direction explicitly.

import { describe, expect, it, vi } from "vitest"
import { mount } from "@vue/test-utils"

const updateRule = vi.fn().mockResolvedValue({ ok: true })
const createRule = vi.fn().mockResolvedValue({ ok: true })
const deleteRule = vi.fn().mockResolvedValue({ ok: true })

vi.mock("../src/composables/useTravelRules", () => ({
  useTravelRules: () => ({ createRule, updateRule, deleteRule }),
}))

import TravelRulesList from "../src/components/TravelRulesList.vue"
import type { TravelRule } from "../src/types"

// No `as TravelRule` cast: the annotation alone must typecheck, so a field
// rename on the interface breaks this fixture instead of silently passing.
function rule(id: number, keyword: string, order: number): TravelRule {
  return {
    id,
    keyword,
    travel_there_minutes: 30,
    travel_back_minutes: 30,
    category: "",
    order,
  }
}

// Rendered top-to-bottom: gym(0), dentist(1), office(2).
const RULES = [rule(1, "gym", 0), rule(2, "dentist", 1), rule(3, "office", 2)]

function mountList(rules: TravelRule[] = RULES) {
  updateRule.mockClear()
  return mount(TravelRulesList, { props: { rules } })
}

function upButtons(wrapper: ReturnType<typeof mountList>) {
  return wrapper.findAll('button[aria-label="Move up (match earlier)"]')
}

function downButtons(wrapper: ReturnType<typeof mountList>) {
  return wrapper.findAll('button[aria-label="Move down (match later)"]')
}

describe("TravelRulesList reorder direction", () => {
  it('"up" swaps a rule to its predecessor\'s lower order', async () => {
    const wrapper = mountList()
    // Middle row: dentist, order 1. Up should take it to gym's 0.
    await upButtons(wrapper)[1].trigger("click")

    expect(updateRule).toHaveBeenCalledWith(2, { order: 0 })
    expect(updateRule).toHaveBeenCalledWith(1, { order: 1 })
  })

  it('"down" swaps a rule to its successor\'s higher order', async () => {
    const wrapper = mountList()
    await downButtons(wrapper)[1].trigger("click")

    expect(updateRule).toHaveBeenCalledWith(2, { order: 2 })
    expect(updateRule).toHaveBeenCalledWith(3, { order: 1 })
  })

  it('"up" swaps with the immediate predecessor, not an arbitrary lower value', async () => {
    const wrapper = mountList()
    await upButtons(wrapper)[2].trigger("click")

    // office(2) must take dentist's exact order (1) — asserting merely "< 2"
    // would accept a jump to 0, which is a different (wrong) reordering.
    const officeCall = updateRule.mock.calls.find((c) => c[0] === 3)
    expect(officeCall?.[1].order).toBe(1)
    expect(updateRule).toHaveBeenCalledWith(2, { order: 2 })
  })

  it("is a no-op at the boundaries", async () => {
    const wrapper = mountList()
    await upButtons(wrapper)[0].trigger("click")
    expect(updateRule).not.toHaveBeenCalled()

    await downButtons(wrapper)[2].trigger("click")
    expect(updateRule).not.toHaveBeenCalled()
  })

  it("biases by -1 when neighbours share an order (legacy rows)", async () => {
    // Equal orders make a value swap a no-op, so the component nudges instead.
    const wrapper = mountList([rule(1, "gym", 0), rule(2, "dentist", 0)])
    await upButtons(wrapper)[1].trigger("click")

    expect(updateRule).toHaveBeenCalledOnce()
    expect(updateRule).toHaveBeenCalledWith(2, { order: -1 })
  })

  it("surfaces an error when the equal-order bias PATCH fails", async () => {
    // The bias can land outside the API's accepted order range for a row
    // already at a bound; without this the arrow is a silent no-op.
    const wrapper = mountList([rule(1, "gym", 0), rule(2, "dentist", 0)])
    updateRule.mockResolvedValueOnce({ ok: false })
    await upButtons(wrapper)[1].trigger("click")
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain("Reorder failed")
    expect(wrapper.emitted("changed")).toBeUndefined()
  })

  it("surfaces an error when a swap PATCH fails", async () => {
    const wrapper = mountList()
    updateRule.mockResolvedValueOnce({ ok: true }).mockResolvedValueOnce({ ok: false })
    await upButtons(wrapper)[1].trigger("click")
    await wrapper.vm.$nextTick()

    expect(wrapper.text()).toContain("Reorder failed")
    expect(wrapper.emitted("changed")).toBeUndefined()
  })
})
