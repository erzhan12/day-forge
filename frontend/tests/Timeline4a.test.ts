import { afterEach, describe, expect, it, vi } from "vitest"
import { mount, VueWrapper } from "@vue/test-utils"

import Timeline4a from "../src/components/Timeline4a.vue"
import type { TimeBlock } from "../src/types"

let wrapper: VueWrapper | null = null

afterEach(() => {
  wrapper?.unmount()
  wrapper = null
})

const BLOCK: TimeBlock = {
  id: 1,
  title: "Work",
  start_time: "09:00",
  end_time: "10:00",
  category: "work",
  is_completed: false,
  sort_order: 0,
}

function mountTimeline(overrides: Record<string, unknown> = {}) {
  Element.prototype.scrollIntoView = vi.fn()
  wrapper = mount(Timeline4a, {
    props: {
      blocks: [BLOCK],
      date: "2026-08-22",
      scheduleWindow: { start: "06:00", end: "23:00" },
      nowMinutes: 10 * 60,
      nowDate: "2026-08-22",
      pxPerMinute: 1.6,
      disabled: false,
      ...overrides,
    },
  })
  return wrapper
}

describe("Timeline4a now-line", () => {
  it("shows the now-line when nowDate matches the viewed date", () => {
    mountTimeline()
    expect(wrapper!.find('[data-testid="now-line-4a"]').exists()).toBe(true)
  })

  it("hides the now-line when viewing a different date", () => {
    mountTimeline({ date: "2026-08-21", nowDate: "2026-08-22", nowMinutes: 10 * 60 })
    expect(wrapper!.find('[data-testid="now-line-4a"]').exists()).toBe(false)
  })
})
