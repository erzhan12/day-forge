import { beforeEach, describe, expect, it, vi } from "vitest"
import { nextTick } from "vue"
import { flushPromises, mount } from "@vue/test-utils"

const mocks = vi.hoisted(() => {
  const { ref } = require("vue") as typeof import("vue")
  return { props: ref<Record<string, unknown>>({}), reload: vi.fn(), request: vi.fn() }
})
vi.mock("@inertiajs/vue3", () => ({
  usePage: () => ({ get props() { return mocks.props.value } }),
  router: { reload: mocks.reload },
}))
vi.mock("../src/composables/useHttp", () => ({ requestJson: mocks.request }))

import DefaultBlockGapEditor from "../src/components/settings/DefaultBlockGapEditor.vue"
import SettingsTemplatesRulesPanel from "../src/components/settings/SettingsTemplatesRulesPanel.vue"
import { isValidDefaultBlockGap, resolveDefaultBlockGap } from "../src/utils/blockGap"

beforeEach(() => {
  mocks.props.value = { ui_preferences: { default_block_gap_minutes: 20 } }
  mocks.reload.mockReset()
  mocks.request.mockReset().mockResolvedValue({ ok: true })
})

function editor() { return mount(DefaultBlockGapEditor) }
type Editor = ReturnType<typeof editor>
async function save(wrapper: Editor, value: string) {
  await wrapper.get("input").setValue(value)
  await wrapper.get("button").trigger("click")
  await flushPromises()
}

describe("DefaultBlockGapEditor", () => {
  it.each([0, 5, 20, 120, undefined, null, "5", 7, true])("resolves saved %s strictly", (raw) => {
    mocks.props.value = { ui_preferences: { default_block_gap_minutes: raw } }
    const wrapper = editor()
    expect((wrapper.get("input").element as HTMLInputElement).value)
      .toBe(String([0, 5, 20, 120].includes(raw as number) && typeof raw === "number" ? raw : 10))
    expect(wrapper.get("input").attributes()).toMatchObject({ type: "number", min: "0", max: "120", step: "5" })
    expect(wrapper.get("label").text()).toBe("Default gap between blocks (minutes)")
  })

  it.each(["", "2.5", "-5", "125", "7"])("rejects draft %s before HTTP", async (value) => {
    const wrapper = editor()
    await save(wrapper, value)
    expect(mocks.request).not.toHaveBeenCalled()
    expect(wrapper.get('[role="alert"]').text()).toContain("5-minute")
  })

  it("sends only the gap and holds saving through accepted-prop refresh", async () => {
    const wrapper = editor()
    const rules = mount(SettingsTemplatesRulesPanel, {
      props: { weekdayTemplate: null, weekendTemplate: null, rules: [], travelRules: [] },
      global: { stubs: { TemplateEditor: true, RulesList: true, TravelRulesList: true } },
    })
    let finishRequest!: (result: { ok: boolean }) => void
    mocks.request.mockReturnValue(new Promise((resolve) => { finishRequest = resolve }))
    await wrapper.get("input").setValue("0")
    await wrapper.get("button").trigger("click")
    await wrapper.get("button").trigger("click")
    expect(mocks.request).toHaveBeenCalledExactlyOnceWith("/api/user/preferences/", "PATCH", { default_block_gap_minutes: 0 })
    expect(wrapper.get("button").attributes("disabled")).toBeDefined()
    finishRequest({ ok: true })
    await flushPromises()
    expect(mocks.reload).toHaveBeenCalledOnce()
    const callbacks = mocks.reload.mock.calls[0][0]
    expect(callbacks.only).toEqual(["ui_preferences"])
    expect(wrapper.get("button").attributes("disabled")).toBeDefined()
    mocks.props.value = { ui_preferences: { default_block_gap_minutes: 0 } }
    await nextTick()
    callbacks.onSuccess()
    callbacks.onFinish()
    await nextTick()
    expect(wrapper.get('[role="status"]').text()).toContain("saved")
    expect(rules.text()).toContain("0-minute gap")
    expect(rules.text()).toContain("back-to-back")
    wrapper.unmount()
    expect((editor().get("input").element as HTMLInputElement).value).toBe("0")
  })

  it.each([
    [{ default_block_gap_minutes: "Field", detail: "Detail", body: "Body" }, "Field"],
    [{ detail: "Detail", body: "Body" }, "Detail"],
    [{ body: ["Body"] }, "Body"],
  ])("shows ordered errors without changing accepted prefs", async (errors, expected) => {
    mocks.request.mockResolvedValue({ ok: false, errors })
    const wrapper = editor()
    await save(wrapper, "5")
    expect(wrapper.get('[role="alert"]').text()).toBe(expected)
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    expect(mocks.props.value.ui_preferences).toEqual({ default_block_gap_minutes: 20 })
    expect(mocks.reload).not.toHaveBeenCalled()
  })

  it.each(["onError", "onFinish"])("reports saved but failed refresh via %s", async (callback) => {
    const wrapper = editor()
    await save(wrapper, "5")
    const callbacks = mocks.reload.mock.calls[0][0]
    callbacks[callback]({ detail: "Server error" })
    callbacks.onFinish()
    await nextTick()
    expect(wrapper.get('[role="alert"]').text()).toContain("saved, but")
    expect(wrapper.find('[role="status"]').exists()).toBe(false)
    expect(wrapper.get("button").attributes("disabled")).toBeUndefined()
  })

  it("synchronizes accepted props and ignores callbacks after disposal", async () => {
    const wrapper = editor()
    mocks.props.value = { ui_preferences: { default_block_gap_minutes: 120 } }
    await nextTick()
    expect((wrapper.get("input").element as HTMLInputElement).value).toBe("120")
    await save(wrapper, "5")
    wrapper.unmount()
    const callbacks = mocks.reload.mock.calls[0][0]
    expect(() => { callbacks.onSuccess(); callbacks.onError({}); callbacks.onFinish() }).not.toThrow()
  })

  it.each([true, "0", 2.5, NaN, Infinity, null, undefined, -5, 125, 7])("normalizes invalid %s", (raw) => {
    expect(isValidDefaultBlockGap(raw)).toBe(false)
    expect(resolveDefaultBlockGap(raw)).toBe(10)
  })
})
