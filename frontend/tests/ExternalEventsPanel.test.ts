// Render snapshots for ExternalEventsPanel.vue across the four states:
// not-connected, loading (skeleton), error, populated.

import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"

import ExternalEventsPanel from "../src/components/ExternalEventsPanel.vue"

const EVENT = {
  title: "Lunch",
  start: "2026-05-07T14:00:00+00:00",
  end: "2026-05-07T15:00:00+00:00",
  calendar_name: "Personal",
  all_day: false,
  external_uid: "uid-1",
}

const ALL_DAY_EVENT = {
  title: "Conference",
  start: "2026-05-07T00:00:00+00:00",
  end: "2026-05-08T00:00:00+00:00",
  calendar_name: "Work",
  all_day: true,
  external_uid: "uid-2",
}

describe("ExternalEventsPanel", () => {
  it("renders nothing when not connected", () => {
    const wrapper = mount(ExternalEventsPanel, {
      props: { events: [], loading: false, error: null, connected: false },
    })
    expect(wrapper.find("section.external-events").exists()).toBe(false)
  })

  it("renders the loading skeleton when loading", () => {
    const wrapper = mount(ExternalEventsPanel, {
      props: { events: [], loading: true, error: null, connected: true },
    })
    expect(wrapper.find(".ee-loading").exists()).toBe(true)
    expect(wrapper.find(".ee-skeleton").exists()).toBe(true)
  })

  it("renders an error row with a Retry button when error is set", async () => {
    const wrapper = mount(ExternalEventsPanel, {
      props: {
        events: [],
        loading: false,
        error: "Apple Calendar service unavailable.",
        connected: true,
      },
    })
    expect(wrapper.find(".ee-error").exists()).toBe(true)
    const button = wrapper.find(".ee-retry")
    expect(button.exists()).toBe(true)
    await button.trigger("click")
    expect(wrapper.emitted("retry")).toBeTruthy()
  })

  it("renders a list of events with all-day badge", () => {
    const wrapper = mount(ExternalEventsPanel, {
      props: {
        events: [ALL_DAY_EVENT, EVENT],
        loading: false,
        error: null,
        connected: true,
      },
    })
    const items = wrapper.findAll('[data-testid="external-event"]')
    expect(items).toHaveLength(2)
    expect(items[0].text()).toContain("All day")
    expect(items[0].text()).toContain("Conference")
    expect(items[1].text()).toContain("Lunch")
  })

  it("renders empty-state copy when connected but no events", () => {
    const wrapper = mount(ExternalEventsPanel, {
      props: { events: [], loading: false, error: null, connected: true },
    })
    expect(wrapper.find(".ee-empty").exists()).toBe(true)
  })
})
