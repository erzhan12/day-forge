import { describe, it, expect, vi, beforeEach } from "vitest"
import { ref } from "vue"
import { mount } from "@vue/test-utils"

// Mock @inertiajs/vue3 so `usePage()` returns a reactive page object we
// can mutate per-test.
const pagePropsRef = ref<{ ui_preferences?: { theme?: string } }>({})

vi.mock("@inertiajs/vue3", () => ({
  usePage: () => ({
    get props() {
      return pagePropsRef.value
    },
  }),
}))

import { useThemeFromProps } from "../src/composables/useThemeFromProps"

const TestHost = {
  setup() {
    useThemeFromProps()
    return () => null
  },
}

describe("useThemeFromProps", () => {
  beforeEach(() => {
    delete document.documentElement.dataset.theme
    pagePropsRef.value = {}
  })

  it("applies the theme when ui_preferences.theme is present and valid", async () => {
    pagePropsRef.value = { ui_preferences: { theme: "strategic" } }
    mount(TestHost)
    // immediate watcher fires synchronously on mount
    expect(document.documentElement.dataset.theme).toBe("strategic")
  })

  it("preserves the current DOM when ui_preferences is absent", async () => {
    // SSR has set data-theme to strategic. Mount a page that omits the prop
    // (simulates an Inertia partial reload). The watcher MUST NOT write 'classic'.
    document.documentElement.dataset.theme = "strategic"
    pagePropsRef.value = {}
    mount(TestHost)
    expect(document.documentElement.dataset.theme).toBe("strategic")
  })

  it("preserves the current DOM when theme is unrecognized", async () => {
    document.documentElement.dataset.theme = "strategic"
    pagePropsRef.value = { ui_preferences: { theme: "neon" } }
    mount(TestHost)
    expect(document.documentElement.dataset.theme).toBe("strategic")
  })

  it("updates the DOM when the prop changes after mount (PATCH → reload flow)", async () => {
    pagePropsRef.value = { ui_preferences: { theme: "classic" } }
    mount(TestHost)
    expect(document.documentElement.dataset.theme).toBe("classic")
    // Simulate `router.reload({ only: ["ui_preferences"] })` resolving:
    pagePropsRef.value = { ui_preferences: { theme: "strategic" } }
    // Flush microtasks so the watcher reacts to the change.
    await Promise.resolve()
    expect(document.documentElement.dataset.theme).toBe("strategic")
  })
})
