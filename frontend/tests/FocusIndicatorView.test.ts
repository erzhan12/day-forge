/**
 * PiP status window rendering (feature 0079 restyle).
 *
 * The 0066 privacy invariant is deliberately reversed here: the active state
 * now shows the block title and its category colour, so that "in a block" vs
 * "in a pause" is readable without reading the text. Clock times and the date
 * remain private, and `document.title` stays generic (see useFocusIndicator).
 */
import { describe, expect, it } from "vitest"
import { mount } from "@vue/test-utils"
import FocusIndicatorView from "../src/components/FocusIndicatorView.vue"

// Sentinels that must still NEVER appear in the PiP view. The block title is
// no longer among them; wall-clock times, the date and the raw category slug
// are.
const PRIVATE = ["2026-08-12", "09:00", "10:00"]

const WORK = "oklch(0.72 0.12 250)"

function mountView(props: Record<string, unknown> = {}) {
  return mount(FocusIndicatorView, {
    props: {
      active: true,
      progressPercent: 42,
      errorState: false,
      ...props,
    },
  })
}

describe("FocusIndicatorView — frame", () => {
  it.each([
    { name: "active", props: { active: true, remainingMinutes: 18 } },
    {
      name: "pause",
      props: { active: false, nextBlockTitle: "vibe", nextBlockRemainingMinutes: 75 },
    },
    { name: "day finished", props: { active: false, dayFinished: true } },
    { name: "neutral", props: { active: false } },
  ])("renders exactly two rows and one track in the $name state", ({ props }) => {
    const w = mountView(props)
    expect(w.findAll(".fi-row")).toHaveLength(2)
    expect(w.findAll(".fi-track")).toHaveLength(1)
  })

  it("conveys state via a non-color data attribute (not color alone)", () => {
    expect(mountView({ active: true }).find(".focus-indicator").attributes("data-state")).toBe(
      "active",
    )
    expect(
      mountView({ active: false }).find(".focus-indicator").attributes("data-state"),
    ).toBe("neutral")
    expect(
      mountView({ active: true, errorState: true }).find(".focus-indicator").attributes(
        "data-state",
      ),
    ).toBe("error")
  })

  it.each([
    { active: true, errorState: false },
    { active: false, errorState: false },
    { active: true, errorState: true },
  ])("renders no control of its own — the PiP chrome owns dismissal", (props) => {
    const w = mountView(props)
    expect(w.find("button").exists()).toBe(false)
    expect(w.find('[aria-label="Close focus indicator"]').exists()).toBe(false)
  })

  it("does not render a Complete control", () => {
    expect(mountView({ active: true }).find(".fi-complete").exists()).toBe(false)
    expect(mountView({ active: false }).find(".fi-complete").exists()).toBe(false)
  })
})

describe("FocusIndicatorView — active state", () => {
  it("renders an accessible progressbar carrying the elapsed percent", () => {
    const w = mountView({ active: true, progressPercent: 42 })
    const bar = w.find('[role="progressbar"]')
    expect(bar.exists()).toBe(true)
    expect(bar.attributes("aria-valuemin")).toBe("0")
    expect(bar.attributes("aria-valuemax")).toBe("100")
    expect(bar.attributes("aria-valuenow")).toBe("42")
    expect(w.find(".fi-fill").attributes("style")).toContain("width: 42%")
  })

  it("shows the block title and the timeline's remaining-minutes copy", () => {
    const w = mountView({ blockTitle: "LeverX [2]", remainingMinutes: 18 })
    expect(w.find(".fi-title").text()).toBe("LeverX [2]")
    expect(w.find(".fi-remaining").text()).toBe("18m left")
    for (const s of PRIVATE) expect(w.html()).not.toContain(s)
  })

  it("formats hour-plus remaining the same as the timeline badge", () => {
    expect(mountView({ remainingMinutes: 90 }).find(".fi-remaining").text()).toBe("1h 30m left")
  })

  it("paints the rail and the fill in the category colour", () => {
    const w = mountView({ categoryColor: WORK })
    expect(w.find(".fi-rail").attributes("style")).toContain(WORK)
    expect(w.find(".fi-fill").attributes("style")).toContain(WORK)
    // The raw category slug is a colour here, never a label.
    expect(w.text()).not.toContain("work")
  })

  it("falls back to the neutral grey when no category colour is supplied", () => {
    const w = mountView({ categoryColor: null })
    expect(w.find(".fi-rail").attributes("style")).toContain("#8E9299")
  })

  it.each(["", "   "])("renders Untitled for an empty block title", (blockTitle) => {
    expect(mountView({ blockTitle }).find(".fi-title").text()).toBe("Untitled")
  })

  it.each([null, undefined, Number.NaN, 0, -1])(
    "hides the countdown when remaining minutes are invalid (%s)",
    (remainingMinutes) => {
      const w = mountView({ remainingMinutes })
      expect(w.find(".fi-remaining").exists()).toBe(false)
      // The bar itself still renders — progress is independent of the label.
      expect(w.find('[role="progressbar"]').exists()).toBe(true)
    },
  )

  it("ignores pause props while active", () => {
    const w = mountView({
      active: true,
      remainingMinutes: 18,
      nextBlockTitle: "vibe",
      nextBlockRemainingMinutes: 75,
      pausePercent: 80,
    })
    expect(w.find(".fi-next-title").exists()).toBe(false)
    expect(w.find(".fi-pause-glyph").exists()).toBe(false)
    expect(w.find(".fi-track--dashed").exists()).toBe(false)
    expect(w.find(".fi-remaining").text()).toBe("18m left")
  })

  it("in error state keeps the bar and shows a generic retry affordance", () => {
    const w = mountView({ active: true, errorState: true })
    expect(w.find('[role="progressbar"]').exists()).toBe(true)
    const retry = w.find(".fi-retry")
    expect(retry.exists()).toBe(true)
    expect(retry.text()).toBe("Retry")
    expect(retry.attributes("role")).toBe("alert")
    for (const s of PRIVATE) expect(w.html()).not.toContain(s)
  })
})

describe("FocusIndicatorView — pause state", () => {
  function mountPause(props: Record<string, unknown> = {}) {
    return mountView({
      active: false,
      nextBlockTitle: "vibe",
      nextBlockRemainingMinutes: 75,
      pausePercent: 30,
      ...props,
    })
  }

  it("labels the pause and names the next block with an arrow", () => {
    const w = mountPause()
    expect(w.findAll(".fi-pause-glyph i")).toHaveLength(2)
    expect(w.find(".fi-sr-only").text()).toBe("Pause")
    expect(w.find(".fi-arrow").text()).toBe("→")
    expect(w.find(".fi-next-title").text()).toBe("vibe")
    expect(w.find(".fi-next-remaining").text()).toBe("1h 15m left")
  })

  it("renders a dashed track whose fill tracks the elapsed pause", () => {
    const w = mountPause({ pausePercent: 30 })
    const track = w.find(".fi-track")
    expect(track.classes()).toContain("fi-track--dashed")
    expect(track.attributes("role")).toBe("progressbar")
    expect(track.attributes("aria-valuenow")).toBe("30")
    const fill = w.find(".fi-fill")
    expect(fill.classes()).toContain("fi-fill--pause")
    expect(fill.attributes("style")).toContain("width: 30%")
  })

  it("keeps the dashed track decorative when the pause has no measurable origin", () => {
    // Before the day's first block there is nothing to measure elapsed pause
    // against, so the track carries no progressbar role and no fill.
    const w = mountPause({ pausePercent: null })
    expect(w.find(".fi-next-title").text()).toBe("vibe")
    const track = w.find(".fi-track")
    expect(track.classes()).toContain("fi-track--dashed")
    expect(track.attributes("role")).toBeUndefined()
    expect(w.find(".fi-fill").exists()).toBe(false)
  })

  it("uses no category colour anywhere — the whole window reads grey", () => {
    const w = mountPause({ categoryColor: WORK })
    expect(w.html()).not.toContain(WORK)
    expect(w.find(".fi-rail").exists()).toBe(false)
    // #ECEAE6 is the in-block foreground and must not leak into a pause.
    expect(w.html()).not.toContain("#ECEAE6")
  })

  it.each(["", "   "])("renders Untitled for an empty next title", (nextBlockTitle) => {
    const w = mountPause({ nextBlockTitle })
    expect(w.find(".fi-next-title").text()).toBe("Untitled")
    expect(w.find(".fi-next-remaining").text()).toBe("1h 15m left")
    expect(w.find(".fi-neutral").exists()).toBe(false)
  })

  it.each([null, undefined, Number.NaN, 0, -1])(
    "falls closed to neutral when the next countdown is invalid (%s)",
    (nextBlockRemainingMinutes) => {
      const w = mountPause({ nextBlockRemainingMinutes })
      expect(w.find(".fi-next-title").exists()).toBe(false)
      expect(w.find(".fi-neutral").text()).toBe("—")
      expect(w.find(".fi-sr-only").text()).toBe("No active block")
    },
  )

  it("treats a null title as no next block even with a positive countdown", () => {
    const w = mountPause({ nextBlockTitle: null })
    expect(w.find(".fi-next-title").exists()).toBe(false)
    expect(w.find(".fi-next-remaining").exists()).toBe(false)
    expect(w.find(".fi-neutral").text()).toBe("—")
  })

  it("shows the day-finished label with an empty, non-measuring track", () => {
    const w = mountView({ active: false, dayFinished: true })
    expect(w.findAll(".fi-pause-glyph i")).toHaveLength(2)
    expect(w.find(".fi-sr-only").text()).toBe("Pause")
    expect(w.find(".fi-pause-done").text()).toBe("· day finished")
    expect(w.find(".fi-next-title").exists()).toBe(false)
    const track = w.find(".fi-track")
    expect(track.classes()).toContain("fi-track--dashed")
    expect(track.attributes("role")).toBeUndefined()
    expect(w.find(".fi-fill").exists()).toBe(false)
  })

  it("keeps the neutral off-today state decorative, not a progressbar", () => {
    const w = mountView({ active: false })
    expect(w.find(".fi-neutral").text()).toBe("—")
    expect(w.find(".fi-sr-only").text()).toBe("No active block")
    expect(w.find(".fi-pause-done").exists()).toBe(false)
    expect(w.find('[role="progressbar"]').exists()).toBe(false)
    expect(w.find(".fi-track").classes()).toContain("fi-track--dashed")
    expect(w.find(".fi-fill").exists()).toBe(false)
  })
})
