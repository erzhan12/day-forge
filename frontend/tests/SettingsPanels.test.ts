import { describe, expect, it, vi } from "vitest"
import { defineComponent, h } from "vue"
import { mount } from "@vue/test-utils"

import SettingsIntegrationsPanel from "../src/components/settings/SettingsIntegrationsPanel.vue"
import SettingsTemplatesRulesPanel from "../src/components/settings/SettingsTemplatesRulesPanel.vue"

function integrationProps(overrides: Record<string, unknown> = {}) {
  return {
    calendarForm: { apple_id: "", password: "", base_url: "" },
    showAdvanced: false,
    calendarDefaultBaseUrl: "https://caldav.icloud.com/",
    isCalendarConnected: false,
    calendarAppleId: null,
    calendarError: null,
    calendarMessage: null,
    calendarBusy: false,
    handleCalendarConnect: vi.fn(),
    handleCalendarDisconnect: vi.fn(),
    toggleCalendarAdvanced: vi.fn(),
    googleAccounts: [],
    googleError: null,
    googleMessage: null,
    googleAccountError: null,
    googleBusy: false,
    handleGoogleConnect: vi.fn(),
    handleGoogleDisconnect: vi.fn(),
    todoistForm: { token: "" },
    isTodoistConnected: false,
    todoistVerifiedAt: null,
    todoistError: null,
    todoistMessage: null,
    todoistBusy: false,
    handleTodoistConnect: vi.fn(),
    handleTodoistDisconnect: vi.fn(),
    habiticaForm: { api_user_id: "", api_token: "" },
    isHabiticaConnected: false,
    habiticaVerifiedAt: null,
    habiticaConnectedUserId: null,
    habiticaError: null,
    habiticaMessage: null,
    habiticaBusy: false,
    handleHabiticaConnect: vi.fn(),
    handleHabiticaDisconnect: vi.fn(),
    ...overrides,
  }
}

describe("SettingsIntegrationsPanel", () => {
  it("keeps all integration blocks and migrated form styles", () => {
    const wrapper = mount(SettingsIntegrationsPanel, {
      props: integrationProps(),
      global: { stubs: { ExternalCalendarPlacementToggle: true } },
    })
    expect(wrapper.findAll("h2")).toHaveLength(1)
    expect(wrapper.findAll("h3.subsection-title")).toHaveLength(4)
    expect(wrapper.findAll(".cal-form")).toHaveLength(3)
    expect(wrapper.find(".cal-field").exists()).toBe(true)
    for (const provider of ["apple", "google", "todoist", "habitica"]) {
      expect(wrapper.find(`[data-testid="settings-integration-${provider}"]`).exists())
        .toBe(true)
    }
  })

  it("forwards every connect action and the advanced toggle", async () => {
    const props = integrationProps()
    const wrapper = mount(SettingsIntegrationsPanel, {
      props,
      global: { stubs: { ExternalCalendarPlacementToggle: true } },
    })
    await wrapper.get('[data-testid="settings-integration-apple"] form').trigger("submit")
    await wrapper.get('[data-testid="settings-integration-google"] .cal-submit').trigger("click")
    await wrapper.get('[data-testid="settings-integration-todoist"] form').trigger("submit")
    await wrapper.get('[data-testid="settings-integration-habitica"] form').trigger("submit")
    await wrapper.get(".cal-advanced-toggle").trigger("click")

    expect(props.handleCalendarConnect).toHaveBeenCalledOnce()
    expect(props.handleGoogleConnect).toHaveBeenCalledOnce()
    expect(props.handleTodoistConnect).toHaveBeenCalledOnce()
    expect(props.handleHabiticaConnect).toHaveBeenCalledOnce()
    expect(props.toggleCalendarAdvanced).toHaveBeenCalledOnce()
  })

  it("forwards disconnects, including the selected Google account id", async () => {
    const props = integrationProps({
      isCalendarConnected: true,
      calendarAppleId: "person@icloud.com",
      googleAccounts: [{ id: 42, email: "person@gmail.com", last_verified_at: null }],
      isTodoistConnected: true,
      isHabiticaConnected: true,
    })
    const wrapper = mount(SettingsIntegrationsPanel, {
      props,
      global: { stubs: { ExternalCalendarPlacementToggle: true } },
    })
    await wrapper.get('[data-testid="settings-integration-apple"] .cal-disconnect').trigger("click")
    await wrapper.get('[data-testid="settings-integration-google"] .cal-disconnect').trigger("click")
    await wrapper.get('[data-testid="settings-integration-todoist"] .cal-disconnect').trigger("click")
    await wrapper.get('[data-testid="settings-integration-habitica"] .cal-disconnect').trigger("click")

    expect(props.handleCalendarDisconnect).toHaveBeenCalledOnce()
    expect(props.handleGoogleDisconnect).toHaveBeenCalledWith(42)
    expect(props.handleTodoistDisconnect).toHaveBeenCalledOnce()
    expect(props.handleHabiticaDisconnect).toHaveBeenCalledOnce()
  })

  it("preserves distinct Google OAuth and account error branches", () => {
    const oauth = mount(SettingsIntegrationsPanel, {
      props: integrationProps({
        googleError: "OAuth error",
        googleMessage: "Connected",
        googleAccountError: "API error",
      }),
      global: { stubs: { ExternalCalendarPlacementToggle: true } },
    })
    expect(oauth.get('[data-testid="settings-integration-google"] .cal-error').text())
      .toBe("OAuth error")

    const account = mount(SettingsIntegrationsPanel, {
      props: integrationProps({ googleAccountError: "API error" }),
      global: { stubs: { ExternalCalendarPlacementToggle: true } },
    })
    expect(account.get('[data-testid="settings-integration-google"] .cal-error').text())
      .toBe("API error")
  })

  it("shows the custom CalDAV URL with the supplied placeholder", () => {
    const wrapper = mount(SettingsIntegrationsPanel, {
      props: integrationProps({ showAdvanced: true }),
      global: { stubs: { ExternalCalendarPlacementToggle: true } },
    })
    expect(wrapper.get('input[type="url"]').attributes("placeholder"))
      .toBe("https://caldav.icloud.com/")
  })
})

describe("SettingsTemplatesRulesPanel", () => {
  const EventStub = (event: string) =>
    defineComponent({
      emits: [event],
      setup(_, { emit }) {
        return () => h("button", { onClick: () => emit(event) }, event)
      },
    })

  it("renders one-column subsections and re-emits distinct list events", async () => {
    const wrapper = mount(SettingsTemplatesRulesPanel, {
      props: {
        weekdayTemplate: null,
        weekendTemplate: null,
        rules: [],
        travelRules: [],
      },
      global: {
        stubs: {
          TemplateEditor: EventStub("saved"),
          RulesList: EventStub("changed"),
          TravelRulesList: EventStub("changed"),
        },
      },
    })
    expect(wrapper.findAll("h2")).toHaveLength(1)
    expect(wrapper.findAll("h3.subsection-title").map((node) => node.text()))
      .toEqual(["Templates", "Rules", "Travel-time rules"])
    expect(wrapper.find(".template-grid").exists()).toBe(true)

    const buttons = wrapper.findAll("button")
    await buttons[0].trigger("click")
    await buttons[2].trigger("click")
    await buttons[3].trigger("click")
    expect(wrapper.emitted("saved")).toHaveLength(1)
    expect(wrapper.emitted("rules-changed")).toHaveLength(1)
    expect(wrapper.emitted("travel-changed")).toHaveLength(1)
  })
})
