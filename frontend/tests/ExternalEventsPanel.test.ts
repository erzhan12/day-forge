// Render tests for ExternalEventsPanel.vue. Feature 0022 restructured the
// error branch to be NON-suppressing (banners coexist with the list) and
// added the account email chip + per-account error banners.

import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"

import ExternalEventsPanel from "../src/components/ExternalEventsPanel.vue"

const APPLE_EVENT = {
  title: "Lunch",
  start: "2026-05-07T14:00:00+00:00",
  end: "2026-05-07T15:00:00+00:00",
  calendar_name: "Personal",
  all_day: false,
  external_uid: "uid-1",
  account_label: "", // Apple: empty sentinel → only the calendar chip
}

const ALL_DAY_EVENT = {
  title: "Conference",
  start: "2026-05-07T00:00:00+00:00",
  end: "2026-05-08T00:00:00+00:00",
  calendar_name: "Work",
  all_day: true,
  external_uid: "uid-2",
  account_label: "",
}

const GOOGLE_EVENT = {
  title: "Standup",
  start: "2026-05-07T09:00:00+00:00",
  end: "2026-05-07T09:15:00+00:00",
  calendar_name: "Team",
  all_day: false,
  external_uid: "g1@google",
  account_label: "alice@gmail.com", // Google: both chips
}

describe("ExternalEventsPanel", () => {
  it("renders nothing when not connected", () => {
    const wrapper = mount(ExternalEventsPanel, {
      props: { events: [], loading: false, connected: false },
    })
    expect(wrapper.find("section.external-events").exists()).toBe(false)
  })

  it("renders the loading skeleton when loading with no events", () => {
    const wrapper = mount(ExternalEventsPanel, {
      props: { events: [], loading: true, connected: true },
    })
    expect(wrapper.find(".ee-loading").exists()).toBe(true)
    expect(wrapper.find(".ee-skeleton").exists()).toBe(true)
  })

  it("renders a list of events with all-day badge", () => {
    const wrapper = mount(ExternalEventsPanel, {
      props: { events: [ALL_DAY_EVENT, APPLE_EVENT], loading: false, connected: true },
    })
    const items = wrapper.findAll('[data-testid="external-event"]')
    expect(items).toHaveLength(2)
    expect(items[0].text()).toContain("All day")
    expect(items[0].text()).toContain("Conference")
    expect(items[1].text()).toContain("Lunch")
  })

  it("renders empty-state copy when connected with no events and no errors", () => {
    const wrapper = mount(ExternalEventsPanel, {
      props: { events: [], loading: false, connected: true },
    })
    expect(wrapper.find(".ee-empty").exists()).toBe(true)
  })

  it("renders event title prominently on its own row", () => {
    const wrapper = mount(ExternalEventsPanel, {
      props: { events: [GOOGLE_EVENT], loading: false, connected: true },
    })
    const item = wrapper.find('[data-testid="external-event"]')
    const title = item.find(".ee-event-title")
    expect(title.exists()).toBe(true)
    expect(title.text()).toBe("Standup")
    expect(item.find(".ee-meta").exists()).toBe(true)
  })

  it("renders a Google row with only the account email, an Apple row with only the calendar chip", () => {
    const wrapper = mount(ExternalEventsPanel, {
      props: { events: [APPLE_EVENT, GOOGLE_EVENT], loading: false, connected: true },
    })
    const items = wrapper.findAll('[data-testid="external-event"]')
    // Apple row: calendar chip only, no account chip.
    expect(items[0].find(".ee-calendar-chip").exists()).toBe(true)
    expect(items[0].find(".ee-account-chip").exists()).toBe(false)
    // Google row: account email only — no calendar-name chip (summary is often a display name).
    expect(items[1].find(".ee-calendar-chip").exists()).toBe(false)
    const accountChip = items[1].find(".ee-account-chip")
    expect(accountChip.exists()).toBe(true)
    expect(accountChip.text()).toBe("alice@gmail.com")
  })

  it("renders a provider error banner ALONGSIDE the event list (non-suppressing)", async () => {
    const wrapper = mount(ExternalEventsPanel, {
      props: {
        events: [APPLE_EVENT],
        loading: false,
        connected: true,
        errorBanners: [
          { provider: "google", message: "Google Calendar service unavailable." },
        ],
      },
    })
    // Banner AND list both render.
    expect(wrapper.find('[data-testid="provider-error"]').exists()).toBe(true)
    expect(wrapper.findAll('[data-testid="external-event"]')).toHaveLength(1)
  })

  it("emits retry with the banner's provider", async () => {
    const wrapper = mount(ExternalEventsPanel, {
      props: {
        events: [],
        loading: false,
        connected: true,
        errorBanners: [
          { provider: "apple", message: "Apple Calendar unavailable." },
          { provider: "google", message: "Google Calendar unavailable." },
        ],
      },
    })
    const buttons = wrapper.findAll(".ee-retry")
    expect(buttons).toHaveLength(2)
    await buttons[0].trigger("click")
    await buttons[1].trigger("click")
    expect(wrapper.emitted("retry")).toEqual([["apple"], ["google"]])
  })

  it("renders a per-account Reconnect CTA for reconnect_required", () => {
    const wrapper = mount(ExternalEventsPanel, {
      props: {
        events: [GOOGLE_EVENT],
        loading: false,
        connected: true,
        accountErrors: [
          { account_id: 5, email: "bob@gmail.com", error: "reconnect_required" },
        ],
      },
    })
    const banner = wrapper.find('[data-testid="account-error"]')
    expect(banner.exists()).toBe(true)
    expect(banner.text()).toContain("bob@gmail.com")
    const reconnect = banner.find(".ee-reconnect")
    expect(reconnect.exists()).toBe(true)
    expect(reconnect.attributes("href")).toBe("/settings/")
    // List still renders alongside the per-account banner.
    expect(wrapper.findAll('[data-testid="external-event"]')).toHaveLength(1)
  })

  it("renders a softer message for an unavailable account (no Reconnect CTA)", () => {
    const wrapper = mount(ExternalEventsPanel, {
      props: {
        events: [],
        loading: false,
        connected: true,
        accountErrors: [
          { account_id: 6, email: "carol@gmail.com", error: "unavailable" },
        ],
      },
    })
    const banner = wrapper.find('[data-testid="account-error"]')
    expect(banner.text()).toContain("temporarily unavailable")
    expect(banner.find(".ee-reconnect").exists()).toBe(false)
  })
})
