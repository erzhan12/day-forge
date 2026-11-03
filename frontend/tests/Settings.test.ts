import { afterEach, beforeEach, describe, expect, it, vi } from "vitest"
import { defineComponent, h, nextTick, reactive, ref } from "vue"
import { mount, type VueWrapper } from "@vue/test-utils"

vi.mock("@inertiajs/vue3", () => ({
  Link: defineComponent({
    inheritAttrs: false,
    setup(_, { attrs, slots }) {
      return () => h("a", attrs, slots.default?.())
    },
  }),
  router: { reload: vi.fn() },
  usePage: () => ({
    props: {
      ui_preferences: {
        theme: "classic",
        chat_suggestions: [
          "Plan my remaining day",
          "Add a focused work block",
          "Make room for a break",
        ],
      },
    },
  }),
}))

vi.mock("../src/composables/useThemeFromProps", () => ({
  useThemeFromProps: vi.fn(),
}))

vi.mock("../src/composables/useCalendarAccount", () => ({
  useCalendarAccount: () => ({
    state: reactive({ status: null, loading: false, error: null }),
    fetchAccountStatus: vi.fn(),
    connect: vi.fn().mockResolvedValue({ ok: true }),
    disconnect: vi.fn().mockResolvedValue({ ok: true }),
    _internals: { accountOperationInFlight: ref(null) },
  }),
}))

const { fetchAccounts } = vi.hoisted(() => ({ fetchAccounts: vi.fn() }))

vi.mock("../src/composables/useGoogleAccount", () => ({
  useGoogleAccount: () => ({
    state: reactive({ accounts: [], loading: false, error: null }),
    fetchAccounts,
    connect: vi.fn(),
    disconnect: vi.fn().mockResolvedValue({ ok: true }),
    _internals: { operationInFlight: ref(false) },
  }),
}))

vi.mock("../src/composables/useTodoistAccount", () => ({
  useTodoistAccount: () => ({
    state: reactive({ status: null, loading: false, error: null }),
    fetchAccountStatus: vi.fn(),
    connect: vi.fn().mockResolvedValue({ ok: true }),
    disconnect: vi.fn().mockResolvedValue({ ok: true }),
    _internals: { accountOperationInFlight: ref(null) },
  }),
}))

vi.mock("../src/composables/useHabiticaAccount", () => ({
  useHabiticaAccount: () => ({
    state: reactive({ status: null, loading: false, error: null }),
    fetchAccountStatus: vi.fn(),
    connect: vi.fn().mockResolvedValue({ ok: true }),
    disconnect: vi.fn().mockResolvedValue({ ok: true }),
    _internals: { accountOperationInFlight: ref(null) },
  }),
}))

const { useDailyExportTokenMock, fetchStatusMock } = vi.hoisted(() => ({
  useDailyExportTokenMock: vi.fn(),
  fetchStatusMock: vi.fn(),
}))

vi.mock("../src/composables/useDailyExportToken", () => ({
  useDailyExportToken: useDailyExportTokenMock,
}))

import Settings from "../src/pages/Settings.vue"
import DailyExportTokenPanel from "../src/components/settings/DailyExportTokenPanel.vue"
import { makeCategories } from "./helpers/schedule"

function stubMatchMedia(matches: boolean): void {
  vi.stubGlobal(
    "matchMedia",
    vi.fn(() => ({
      matches,
      media: "(min-width: 1024px)",
      addEventListener: vi.fn(),
      removeEventListener: vi.fn(),
    })),
  )
}

function mountSettings(
  categories = makeCategories(),
  extraProps: Record<string, unknown> = {},
): VueWrapper {
  return mount(Settings, {
    attachTo: document.body,
    props: {
      templates: [],
      rules: [],
      travel_rules: [],
      categories,
      schedule_window: { start: "06:00", end: "23:00", time_zone: "Asia/Almaty" },
      ...extraProps,
    },
    global: {
      stubs: {
        SoundNotificationToggle: true,
        DesktopNotificationToggle: true,
        TemplateEditor: true,
        RulesList: true,
        TravelRulesList: true,
        ExternalCalendarPlacementToggle: true,
      },
    },
  })
}

let wrapper: VueWrapper | null = null

beforeEach(() => {
  window.history.replaceState({}, "", "/settings/#appearance")
  fetchStatusMock.mockReset()
  useDailyExportTokenMock.mockReset().mockImplementation(() => ({
    state: reactive({ hasToken: false, createdAt: null, rawToken: null, loading: false, error: null }),
    fetchStatus: fetchStatusMock,
    createToken: vi.fn(),
    revokeToken: vi.fn(),
    dismissRawToken: vi.fn(),
    dispose: vi.fn(),
  }))
})

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
  vi.unstubAllGlobals()
  vi.restoreAllMocks()
  vi.clearAllMocks()
})

describe("Settings topic shell", () => {
  it("shows a reload error instead of category controls for an empty catalog", () => {
    wrapper = mountSettings([])
    expect(wrapper.get('[role="alert"]').text()).toContain("Category data could not be loaded")
    expect(wrapper.find('[data-settings-topic="categories"]').exists()).toBe(false)
  })
  it("passes the persisted schedule timezone to the page-level mismatch prompt", () => {
    stubMatchMedia(true)
    wrapper = mountSettings()
    expect(wrapper.findComponent({ name: "TimeZoneMismatchPrompt" }).props("timeZone")).toBe("Asia/Almaty")
  })

  it("mounts the AI Assistant editor inside a stable section", () => {
    stubMatchMedia(true)
    window.history.replaceState({}, "", "/settings/#ai-assistant")
    wrapper = mountSettings()

    expect(wrapper.get('[data-testid="settings-ai-chat-suggestions"]').exists())
      .toBe(true)
    expect(wrapper.findAll('[data-testid="chat-suggestion-input"]'))
      .toHaveLength(3)
  })

  it("renders desktop hash navigation and the selected appearance controls", () => {
    stubMatchMedia(true)
    wrapper = mountSettings()

    const nav = wrapper.get('nav[aria-label="Settings topics"]')
    expect(nav.findAll('a[href^="#"]')).toHaveLength(7)
    expect(nav.get('a[href="#appearance"]').attributes("aria-current")).toBe(
      "page",
    )
    expect(wrapper.get('[data-settings-topic="appearance"]').attributes("hidden"))
      .toBeUndefined()
    expect(wrapper.get('[data-settings-topic="integrations"]').attributes())
      .toHaveProperty("hidden")

    const appearance = wrapper.get('[data-settings-topic="appearance"]')
    const themes = appearance.get('[role="radiogroup"]')
    expect(themes.findAll('[role="radio"]').map((option) =>
      option.get(".design-card__title").text(),
    )).toEqual(["Classic", "Strategic", "Light Premium", "Dark 4a"])
    expect(themes.get('[data-theme-option="classic"]').attributes("aria-checked"))
      .toBe("true")
    expect(themes.findAll('[aria-checked="true"]')).toHaveLength(1)
  })

  it("marks topic headings for scroll-margin under the sticky mobile select", () => {
    stubMatchMedia(false)
    wrapper = mountSettings()
    const ids = [
      "appearance",
      "categories",
      "schedule",
      "ai-assistant",
      "notifications",
      "integrations",
      "templates-rules",
    ]
    for (const id of ids) {
      expect(wrapper.get(`#settings-topic-${id}`).classes()).toContain(
        "settings-topic-heading",
      )
    }
  })

  it("does not set inert on the active panel", () => {
    stubMatchMedia(true)
    wrapper = mountSettings()
    const active = wrapper.get('[data-settings-topic="appearance"]')
    const hidden = wrapper.get('[data-settings-topic="integrations"]')
    expect(active.attributes("inert")).toBeUndefined()
    expect(active.element.hasAttribute("inert")).toBe(false)
    expect(hidden.element.hasAttribute("inert")).toBe(true)
  })

  it("follows hash changes without unmounting inactive panels", async () => {
    stubMatchMedia(true)
    wrapper = mountSettings()
    window.history.replaceState({}, "", "/settings/#integrations")
    window.dispatchEvent(new HashChangeEvent("hashchange"))
    await nextTick()

    expect(wrapper.get('[data-settings-topic="integrations"]').attributes("hidden"))
      .toBeUndefined()
    expect(wrapper.get('[data-settings-topic="appearance"]').attributes())
      .toHaveProperty("hidden")
  })

  it("renders a labeled mobile select and adapts its native change event", async () => {
    stubMatchMedia(false)
    wrapper = mountSettings()

    expect(wrapper.find('nav[aria-label="Settings topics"]').exists()).toBe(false)
    const select = wrapper.get("#settings-topic-select")
    expect(wrapper.get('label[for="settings-topic-select"]').text()).toBe("Topic")
    expect(select.findAll("option")).toHaveLength(7)
    await select.setValue("templates-rules")
    await nextTick()

    expect(window.location.hash).toBe("#templates-rules")
    expect(wrapper.get('[data-settings-topic="templates-rules"]').attributes("hidden"))
      .toBeUndefined()
  })

  it("preserves child-local drafts while panels are hidden", async () => {
    stubMatchMedia(true)
    window.history.replaceState({}, "", "/settings/#schedule")
    wrapper = mountSettings()
    const start = wrapper.get('.day-window-editor input[type="time"]')
    await start.setValue("07:15")

    window.history.replaceState({}, "", "/settings/#appearance")
    window.dispatchEvent(new HashChangeEvent("hashchange"))
    await nextTick()
    window.history.replaceState({}, "", "/settings/#schedule")
    window.dispatchEvent(new HashChangeEvent("hashchange"))
    await nextTick()

    expect(wrapper.get('.day-window-editor input[type="time"]').element.value)
      .toBe("07:15")
  })

  it("focuses the panel heading for Enter navigation, once", async () => {
    stubMatchMedia(true)
    wrapper = mountSettings()
    const link = wrapper.get('a[href="#notifications"]')
    await link.trigger("keydown", { key: "Enter" })
    window.history.replaceState({}, "", "/settings/#notifications")
    window.dispatchEvent(new HashChangeEvent("hashchange"))
    await nextTick()
    await nextTick()
    expect(document.activeElement?.id).toBe("settings-topic-notifications")

    window.history.replaceState({}, "", "/settings/#integrations")
    window.dispatchEvent(new HashChangeEvent("hashchange"))
    await nextTick()
    await nextTick()
    expect(document.activeElement?.id).toBe("settings-topic-notifications")
  })

  it("does not focus headings after pointer or Space navigation", async () => {
    stubMatchMedia(true)
    wrapper = mountSettings()
    const scheduleLink = wrapper.get('a[href="#schedule"]')
    scheduleLink.element.focus()
    await scheduleLink.trigger("keydown", { key: " " })
    window.history.replaceState({}, "", "/settings/#schedule")
    window.dispatchEvent(new HashChangeEvent("hashchange"))
    await nextTick()
    await nextTick()
    expect(document.activeElement).toBe(scheduleLink.element)
  })

  it("does not add a hash or leave keyboard intent armed for the active link", async () => {
    stubMatchMedia(true)
    window.history.replaceState({}, "", "/settings/")
    wrapper = mountSettings()
    const appearanceLink = wrapper.get('a[href="#appearance"]')
    appearanceLink.element.focus()
    await appearanceLink.trigger("keydown", { key: "Enter" })
    const click = new MouseEvent("click", { bubbles: true, cancelable: true })
    appearanceLink.element.dispatchEvent(click)

    expect(click.defaultPrevented).toBe(true)
    expect(window.location.hash).toBe("")

    window.history.replaceState({}, "", "/settings/#integrations")
    window.dispatchEvent(new HashChangeEvent("hashchange"))
    await nextTick()
    await nextTick()
    expect(document.activeElement).toBe(appearanceLink.element)
  })

  it("focuses the destination heading after a mobile select change", async () => {
    stubMatchMedia(false)
    wrapper = mountSettings()
    await wrapper.get("#settings-topic-select").setValue("templates-rules")
    await nextTick()
    expect(document.activeElement?.id).toBe("settings-topic-templates-rules")
  })

  it("lands Google OAuth callbacks on Integrations with one atomic replace", async () => {
    stubMatchMedia(true)
    window.history.replaceState({}, "", "/settings/?google=error&reason=denied")
    const replaceSpy = vi.spyOn(window.history, "replaceState")
    const pushSpy = vi.spyOn(window.history, "pushState")
    wrapper = mountSettings()
    await nextTick()

    expect(window.location.hash).toBe("#integrations")
    expect(window.location.search).toBe("")
    expect(wrapper.get('[data-settings-topic="integrations"]').attributes("hidden"))
      .toBeUndefined()
    expect(wrapper.get('[data-testid="settings-integration-google"]').text())
      .toContain("Google connection was cancelled.")
    expect(replaceSpy).toHaveBeenCalledTimes(1)
    expect(replaceSpy.mock.calls[0][2]).toBe("/settings/#integrations")
    expect(pushSpy).not.toHaveBeenCalled()
  })

  it("lands Google OAuth success on Integrations and refetches accounts", async () => {
    stubMatchMedia(true)
    window.history.replaceState({}, "", "/settings/?google=connected")
    const replaceSpy = vi.spyOn(window.history, "replaceState")
    const pushSpy = vi.spyOn(window.history, "pushState")
    wrapper = mountSettings()
    await nextTick()

    expect(window.location.hash).toBe("#integrations")
    expect(window.location.search).toBe("")
    expect(wrapper.get('[data-settings-topic="integrations"]').attributes("hidden"))
      .toBeUndefined()
    expect(wrapper.get('[data-testid="settings-integration-google"]').text())
      .toContain("Google Calendar connected.")
    expect(fetchAccounts).toHaveBeenCalledTimes(2)
    expect(replaceSpy).toHaveBeenCalledTimes(1)
    expect(replaceSpy.mock.calls[0][2]).toBe("/settings/#integrations")
    expect(String(replaceSpy.mock.calls[0][2])).not.toContain("google=")
    expect(pushSpy).not.toHaveBeenCalled()
  })
})


it("places the default gap control below the day window under Schedule", async () => {
  window.history.replaceState({}, "", "/settings/#schedule")
  stubMatchMedia(true)
  wrapper = mountSettings()
  await nextTick()
  const panel = wrapper.get('[aria-label="Day window"]').element.parentElement!
  expect(panel.textContent).toContain("Default gap between blocks (minutes)")
  expect(panel.querySelector('input[type="number"]')).not.toBeNull()
})

describe("DailyExportTokenPanel wiring (feature 0088)", () => {
  it("mounts the export-token panel only while Integrations is active", async () => {
    stubMatchMedia(true)
    wrapper = mountSettings()
    expect(wrapper.find('[data-testid="settings-integration-export-token"]').exists())
      .toBe(false)

    window.history.replaceState({}, "", "/settings/#integrations")
    window.dispatchEvent(new HashChangeEvent("hashchange"))
    await nextTick()
    expect(wrapper.find('[data-testid="settings-integration-export-token"]').exists())
      .toBe(true)
    expect(useDailyExportTokenMock).toHaveBeenCalledTimes(1)

    window.history.replaceState({}, "", "/settings/#appearance")
    window.dispatchEvent(new HashChangeEvent("hashchange"))
    await nextTick()
    // Unlike every other integrations sub-panel (which stay mounted via
    // v-show), this one must fully tear down — it holds a one-time secret.
    expect(wrapper.find('[data-testid="settings-integration-export-token"]').exists())
      .toBe(false)
  })

  it("passes the page's auth_user_id through to the panel", async () => {
    window.history.replaceState({}, "", "/settings/#integrations")
    stubMatchMedia(true)
    wrapper = mountSettings(makeCategories(), { auth_user_id: 42 })
    await nextTick()
    const panel = wrapper.findComponent(DailyExportTokenPanel)
    expect(panel.props("authUserId")).toBe(42)
    expect(fetchStatusMock).toHaveBeenCalled()
  })

  it("remounts the panel (fresh composable instance) when the account changes", async () => {
    window.history.replaceState({}, "", "/settings/#integrations")
    stubMatchMedia(true)
    wrapper = mountSettings(makeCategories(), { auth_user_id: 1 })
    await nextTick()
    expect(useDailyExportTokenMock).toHaveBeenCalledTimes(1)

    await wrapper.setProps({ auth_user_id: 2 })
    await nextTick()
    // A different `:key` forces Vue to destroy and recreate the component,
    // which creates a brand-new composable instance rather than reusing one
    // that might still hold the previous account's raw token in memory.
    expect(useDailyExportTokenMock).toHaveBeenCalledTimes(2)
  })
})
