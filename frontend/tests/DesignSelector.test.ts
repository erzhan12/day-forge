import { describe, it, expect, vi, beforeEach } from "vitest"
import { nextTick } from "vue"
import { mount, flushPromises } from "@vue/test-utils"
import type { ApiResult } from "../src/composables/useHttp"

// -- mocks ---------------------------------------------------------------
// vi.mock is hoisted; declare the shared spies/refs via vi.hoisted so the
// factory can reference them.
const mocks = vi.hoisted(() => {
  const { ref } = require("vue") as typeof import("vue")
  return {
    pagePropsRef: ref<{ ui_preferences?: { theme?: string } }>({
      ui_preferences: { theme: "classic" },
    }),
    routerReloadSpy: vi.fn(),
    saveThemeSpy: vi.fn(),
  }
})

vi.mock("@inertiajs/vue3", () => ({
  router: { reload: mocks.routerReloadSpy },
  usePage: () => ({
    get props() {
      return mocks.pagePropsRef.value
    },
  }),
}))

vi.mock("../src/composables/usePreferences", () => ({
  usePreferences: () => ({ saveTheme: mocks.saveThemeSpy }),
}))

const { pagePropsRef, routerReloadSpy, saveThemeSpy } = mocks

import DesignSelector from "../src/components/DesignSelector.vue"

beforeEach(() => {
  pagePropsRef.value = { ui_preferences: { theme: "classic" } }
  routerReloadSpy.mockReset()
  saveThemeSpy.mockReset()
  delete document.documentElement.dataset.theme
})

describe("DesignSelector", () => {
  it("falls back to <html data-theme> when ui_preferences prop is absent", async () => {
    pagePropsRef.value = {}
    document.documentElement.dataset.theme = "strategic"
    const wrapper = mount(DesignSelector)
    // Selector shows Strategic checked because the DOM has the
    // last-known value, even though the prop is missing.
    expect(
      wrapper
        .find('[data-theme-option="strategic"]')
        .attributes("aria-checked"),
    ).toBe("true")
    expect(
      wrapper
        .find('[data-theme-option="classic"]')
        .attributes("aria-checked"),
    ).toBe("false")
  })

  it("renders the three theme options as a radio group", () => {
    const wrapper = mount(DesignSelector)
    const group = wrapper.find('[role="radiogroup"]')
    expect(group.exists()).toBe(true)
    const radios = wrapper.findAll('[role="radio"]')
    expect(radios).toHaveLength(3)
    // Classic is checked from page props.
    expect(
      wrapper
        .find('[data-theme-option="classic"]')
        .attributes("aria-checked"),
    ).toBe("true")
    expect(
      wrapper
        .find('[data-theme-option="strategic"]')
        .attributes("aria-checked"),
    ).toBe("false")
  })

  it("calls saveTheme when a different option is clicked and triggers router.reload", async () => {
    saveThemeSpy.mockResolvedValueOnce({ ok: true })
    const wrapper = mount(DesignSelector)
    await wrapper.find('[data-theme-option="strategic"]').trigger("click")
    await flushPromises()
    expect(saveThemeSpy).toHaveBeenCalledWith("strategic")
    expect(routerReloadSpy).toHaveBeenCalledWith(
      expect.objectContaining({
        only: ["ui_preferences"],
        onSuccess: expect.any(Function),
        onError: expect.any(Function),
        onFinish: expect.any(Function),
      }),
    )
  })

  it("does not call saveTheme when the currently-selected option is clicked", async () => {
    const wrapper = mount(DesignSelector)
    await wrapper.find('[data-theme-option="classic"]').trigger("click")
    await flushPromises()
    expect(saveThemeSpy).not.toHaveBeenCalled()
    expect(routerReloadSpy).not.toHaveBeenCalled()
  })

  it("sets aria-disabled on all three cards while save is pending", async () => {
    let resolveSave: ((r: ApiResult) => void) | undefined
    saveThemeSpy.mockImplementationOnce(
      () => new Promise<ApiResult>((r) => (resolveSave = r)),
    )
    const wrapper = mount(DesignSelector)
    await wrapper.find('[data-theme-option="strategic"]').trigger("click")
    // Click handler runs synchronously up to `await saveTheme`; allow Vue
    // to flush the resulting reactivity.
    await nextTick()
    for (const id of ["classic", "strategic", "light_premium"]) {
      expect(
        wrapper.find(`[data-theme-option="${id}"]`).attributes("aria-disabled"),
      ).toBe("true")
    }
    resolveSave!({ ok: true })
    await flushPromises()
  })

  it("clicking a sibling while saving does NOT fire a second PATCH", async () => {
    let resolveSave: ((r: ApiResult) => void) | undefined
    saveThemeSpy.mockImplementationOnce(
      () => new Promise<ApiResult>((r) => (resolveSave = r)),
    )
    const wrapper = mount(DesignSelector)
    await wrapper.find('[data-theme-option="strategic"]').trigger("click")
    await nextTick()
    // Try clicking another option while the PATCH is in flight.
    await wrapper.find('[data-theme-option="light_premium"]').trigger("click")
    await nextTick()
    expect(saveThemeSpy).toHaveBeenCalledTimes(1)
    expect(saveThemeSpy).toHaveBeenCalledWith("strategic")
    resolveSave!({ ok: true })
    await flushPromises()
  })

  it("onFinish removes aria-disabled (success path)", async () => {
    saveThemeSpy.mockResolvedValueOnce({ ok: true })
    const wrapper = mount(DesignSelector)
    await wrapper.find('[data-theme-option="strategic"]').trigger("click")
    await flushPromises()
    expect(routerReloadSpy).toHaveBeenCalled()
    const opts = routerReloadSpy.mock.calls[0][0]
    opts.onSuccess?.()
    opts.onFinish?.()
    await nextTick()
    for (const id of ["classic", "strategic", "light_premium"]) {
      expect(
        wrapper.find(`[data-theme-option="${id}"]`).attributes("aria-disabled"),
      ).toBe("false")
    }
  })

  it("onError fallback applies the theme to <html> and surfaces a warning", async () => {
    saveThemeSpy.mockResolvedValueOnce({ ok: true })
    const wrapper = mount(DesignSelector)
    await wrapper.find('[data-theme-option="strategic"]').trigger("click")
    await flushPromises()
    const opts = routerReloadSpy.mock.calls[0][0]
    opts.onError?.()
    opts.onFinish?.()
    await nextTick()
    expect(document.documentElement.dataset.theme).toBe("strategic")
    expect(wrapper.text()).toContain("Refresh to fully sync")
  })

  it("onError after unmount does NOT mutate the global DOM", async () => {
    // Simulates: user clicks Save → navigates away (component unmounts)
    // → late onError fires. The stale callback must NOT write
    // data-theme to whatever page is now mounted (e.g. /accounts/login/).
    saveThemeSpy.mockResolvedValueOnce({ ok: true })
    const wrapper = mount(DesignSelector)
    await wrapper.find('[data-theme-option="strategic"]').trigger("click")
    await flushPromises()
    const opts = routerReloadSpy.mock.calls[0][0]
    wrapper.unmount()
    // Simulate the "next page" having set its own theme (e.g. Login set
    // 'strategic' on mount, or the user is on a Classic page).
    document.documentElement.dataset.theme = "classic"
    opts.onError?.()
    // The stale onError must be a no-op.
    expect(document.documentElement.dataset.theme).toBe("classic")
  })

  it("onSuccess after unmount does NOT throw or mutate refs", async () => {
    saveThemeSpy.mockResolvedValueOnce({ ok: true })
    const wrapper = mount(DesignSelector)
    await wrapper.find('[data-theme-option="strategic"]').trigger("click")
    await flushPromises()
    const opts = routerReloadSpy.mock.calls[0][0]
    wrapper.unmount()
    // Should be a silent no-op — not throw.
    expect(() => opts.onSuccess?.()).not.toThrow()
  })

  it("onFinish removes aria-disabled (error path)", async () => {
    saveThemeSpy.mockResolvedValueOnce({ ok: true })
    const wrapper = mount(DesignSelector)
    await wrapper.find('[data-theme-option="strategic"]').trigger("click")
    await flushPromises()
    const opts = routerReloadSpy.mock.calls[0][0]
    opts.onError?.()
    opts.onFinish?.()
    await nextTick()
    for (const id of ["classic", "strategic", "light_premium"]) {
      expect(
        wrapper.find(`[data-theme-option="${id}"]`).attributes("aria-disabled"),
      ).toBe("false")
    }
  })

  it("a failed PATCH keeps the previous theme selected and surfaces an error", async () => {
    saveThemeSpy.mockResolvedValueOnce({
      ok: false,
      errors: { detail: "Server error (500)" },
    })
    const wrapper = mount(DesignSelector)
    await wrapper.find('[data-theme-option="strategic"]').trigger("click")
    await flushPromises()
    expect(routerReloadSpy).not.toHaveBeenCalled()
    expect(
      wrapper
        .find('[data-theme-option="classic"]')
        .attributes("aria-checked"),
    ).toBe("true")
    expect(wrapper.text()).toContain("Server error (500)")
    // aria-disabled lifted after the failure.
    for (const id of ["classic", "strategic", "light_premium"]) {
      expect(
        wrapper.find(`[data-theme-option="${id}"]`).attributes("aria-disabled"),
      ).toBe("false")
    }
  })

  it("keyboard Space triggers selection", async () => {
    saveThemeSpy.mockResolvedValueOnce({ ok: true })
    const wrapper = mount(DesignSelector)
    await wrapper
      .find('[data-theme-option="strategic"]')
      .trigger("keydown", { key: " " })
    await flushPromises()
    expect(saveThemeSpy).toHaveBeenCalledWith("strategic")
  })

  it("keyboard Enter triggers selection (parity with Space)", async () => {
    saveThemeSpy.mockResolvedValueOnce({ ok: true })
    const wrapper = mount(DesignSelector)
    await wrapper
      .find('[data-theme-option="strategic"]')
      .trigger("keydown", { key: "Enter" })
    await flushPromises()
    expect(saveThemeSpy).toHaveBeenCalledWith("strategic")
  })

  it("Space while saving does NOT fire a second PATCH", async () => {
    let resolveSave: ((r: ApiResult) => void) | undefined
    saveThemeSpy.mockImplementationOnce(
      () => new Promise<ApiResult>((r) => (resolveSave = r)),
    )
    const wrapper = mount(DesignSelector)
    await wrapper.find('[data-theme-option="strategic"]').trigger("click")
    await nextTick()
    // Keyboard activation must also be gated by the aria-disabled state.
    await wrapper
      .find('[data-theme-option="light_premium"]')
      .trigger("keydown", { key: " " })
    await nextTick()
    expect(saveThemeSpy).toHaveBeenCalledTimes(1)
    expect(saveThemeSpy).toHaveBeenCalledWith("strategic")
    resolveSave!({ ok: true })
    await flushPromises()
  })

  it("Enter while saving does NOT fire a second PATCH", async () => {
    let resolveSave: ((r: ApiResult) => void) | undefined
    saveThemeSpy.mockImplementationOnce(
      () => new Promise<ApiResult>((r) => (resolveSave = r)),
    )
    const wrapper = mount(DesignSelector)
    await wrapper.find('[data-theme-option="strategic"]').trigger("click")
    await nextTick()
    await wrapper
      .find('[data-theme-option="light_premium"]')
      .trigger("keydown", { key: "Enter" })
    await nextTick()
    expect(saveThemeSpy).toHaveBeenCalledTimes(1)
    resolveSave!({ ok: true })
    await flushPromises()
  })

  it("arrow-right moves focus to the next option", async () => {
    const wrapper = mount(DesignSelector, { attachTo: document.body })
    const first = wrapper.find('[data-theme-option="classic"]')
    ;(first.element as HTMLElement).focus()
    await first.trigger("keydown", { key: "ArrowRight" })
    expect(document.activeElement).toBe(
      wrapper.find('[data-theme-option="strategic"]').element,
    )
    wrapper.unmount()
  })

  it("arrow-right still moves focus while a save is pending", async () => {
    // Plan §Phase 5: arrow navigation is independent of save state.
    // Users may want to compare options visually while a PATCH is in
    // flight; only activation keys (Space/Enter) are gated on isSaving.
    let resolveSave: ((r: ApiResult) => void) | undefined
    saveThemeSpy.mockImplementationOnce(
      () => new Promise<ApiResult>((r) => (resolveSave = r)),
    )
    const wrapper = mount(DesignSelector, { attachTo: document.body })
    await wrapper.find('[data-theme-option="strategic"]').trigger("click")
    await nextTick()
    // All three cards are aria-disabled but still focusable.
    const first = wrapper.find('[data-theme-option="classic"]')
    ;(first.element as HTMLElement).focus()
    await first.trigger("keydown", { key: "ArrowRight" })
    expect(document.activeElement).toBe(
      wrapper.find('[data-theme-option="strategic"]').element,
    )
    // Focus moved, but no second PATCH was fired.
    expect(saveThemeSpy).toHaveBeenCalledTimes(1)
    resolveSave!({ ok: true })
    await flushPromises()
    wrapper.unmount()
  })
})
