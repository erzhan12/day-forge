// Feature 0106 — Dark 4a day fit, controls and text floor.
//
// Pins the playwright user to Dark 4a, seeds the fixture Sunday 22 Nov 2026
// (Planning 09:40–10:05, Email 11:15–11:40, Short call 11:40–11:45, Lunch
// Walk 11:45–12:10, Deep work 15:00–16:00) and an empty draft Saturday
// 21 Nov 2026, fixes the browser clock at 11:42 in the user's zone, and
// checks at 1440 × 900 and 390 × 844:
//   - the whole day fits the schedule column at scrollTop 0 (wide);
//   - header secondary buttons are 32 px;
//   - the 5-minute block is a 28 px compact row with its checkbox, handle,
//     title, duration and × inside the card, each hit-testable on its own;
//   - the mid-day gap reads "Free · 2h 50m" and "12:10–15:00";
//   - the empty-day state shows both actions (stacked at 390 px);
//   - the Add Block form and every Settings topic use 36 px fields with the
//     field background and control border, and the root color-scheme is dark;
//   - the chat input uses the body font, 14 px, grey text and placeholder;
//   - Log out is absent from Schedule and present in Settings;
//   - no horizontal scroll at 390 px;
//   - every visible text node is >= 13 px with >= 4.5:1 composited contrast
//     (disabled controls exempt).
//
// Not covered here (unit tests and manual checks own them): the calendar
// card (needs a connected calendar account), the open picture-in-picture
// state, and clock times other than 11:42.
//
// Run from frontend/:
//   node scripts/playwright/dark4a-day-fit.mjs [--cleanup]
//
// Pre-reqs: Django :8006, Vite :5173, playwright user. No LLM key. The user's
// theme is restored afterwards; --cleanup deletes the two seeded days.

import { chromium } from "@playwright/test"
import {
  BASE,
  ELEMENT_TIMEOUT_MS,
  USERNAME,
  cleanupSchedules,
  login,
  makeFailAggregator,
  pinTheme,
  preflight,
  restoreTheme,
  seed,
} from "./test-utils.mjs"

const DAY = "2026-11-22"
const EMPTY_DAY = "2026-11-21"
const WIDE = { width: 1440, height: 900 }
const NARROW = { width: 390, height: 844 }
const FIELD_BG = "rgb(29, 31, 34)"
const CONTROL_BORDER = "rgb(106, 110, 117)"
const SECONDARY_TEXT = "rgb(156, 163, 175)"
const SETTINGS_TOPICS = [
  "appearance", "schedule", "ai-assistant", "notifications",
  "integrations", "categories", "templates-rules",
]

const BLOCKS = [
  ["Planning", "09:40", "10:05", "work"],
  ["Email", "11:15", "11:40", "work"],
  ["Short call", "11:40", "11:45", "personal"],
  ["Lunch Walk", "11:45", "12:10", "health"],
  ["Deep work", "15:00", "16:00", "work"],
].map(([title, start_time, end_time, category], index) => ({
  title, start_time, end_time, category, sort_order: index * 10,
}))

const { failures, fail } = makeFailAggregator()

function check(condition, message) {
  if (!condition) fail(message)
}

/** UTC instant for a wall-clock time in `timeZone`. */
function zonedInstant(date, time, timeZone) {
  const [y, m, d] = date.split("-").map(Number)
  const [hh, mm] = time.split(":").map(Number)
  const guess = Date.UTC(y, m - 1, d, hh, mm)
  const parts = Object.fromEntries(
    new Intl.DateTimeFormat("en-US", {
      timeZone, hourCycle: "h23", year: "numeric", month: "2-digit",
      day: "2-digit", hour: "2-digit", minute: "2-digit",
    }).formatToParts(new Date(guess)).map((p) => [p.type, p.value]),
  )
  const asZoned = Date.UTC(+parts.year, +parts.month - 1, +parts.day, +parts.hour, +parts.minute)
  return new Date(guess - (asZoned - guess))
}

// ---------------------------------------------------------------------------
// In-page probes. Each runs inside page.evaluate and returns plain data.

/** Every visible text node: computed size >= 13 px, composited contrast >= 4.5. */
function textSweep(rootSelector) {
  const canvas = document.createElement("canvas")
  canvas.width = canvas.height = 1
  const ctx = canvas.getContext("2d", { willReadFrequently: true })
  function rgba(color) {
    ctx.clearRect(0, 0, 1, 1)
    ctx.fillStyle = "rgba(0,0,0,0)"
    ctx.fillStyle = color
    ctx.fillRect(0, 0, 1, 1)
    const [r, g, b, a] = ctx.getImageData(0, 0, 1, 1).data
    return [r, g, b, a / 255]
  }
  function over(top, bottom) {
    const a = top[3] + bottom[3] * (1 - top[3])
    if (a === 0) return [0, 0, 0, 0]
    return [0, 1, 2].map((i) => (top[i] * top[3] + bottom[i] * bottom[3] * (1 - top[3])) / a).concat(a)
  }
  function luminance([r, g, b]) {
    const c = [r, g, b].map((v) => {
      const s = v / 255
      return s <= 0.03928 ? s / 12.92 : ((s + 0.055) / 1.055) ** 2.4
    })
    return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]
  }
  function backdrop(el) {
    const chain = []
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      chain.push(rgba(getComputedStyle(node).backgroundColor))
    }
    let color = rgba(getComputedStyle(document.documentElement).backgroundColor)
    if (color[3] < 1) color = over(color, [255, 255, 255, 1])
    for (let i = chain.length - 1; i >= 0; i -= 1) color = over(chain[i], color)
    return color
  }
  function opacity(el) {
    let value = 1
    for (let node = el; node && node.nodeType === 1; node = node.parentElement) {
      value *= Number(getComputedStyle(node).opacity)
    }
    return value
  }
  const root = document.querySelector(rootSelector) ?? document.body
  const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT)
  const offenders = []
  let checked = 0
  for (let node = walker.nextNode(); node; node = walker.nextNode()) {
    const text = node.textContent.replace(/\s+/g, " ").trim()
    if (!text) continue
    const el = node.parentElement
    if (!el || el.closest("script, style, option, [hidden], [inert], [aria-hidden='true']")) continue
    if (el.closest(":disabled, [aria-disabled='true']")) continue
    const range = document.createRange()
    range.selectNodeContents(node)
    const rect = range.getBoundingClientRect()
    if (rect.width < 2 || rect.height < 2) continue // sr-only and collapsed text
    const style = getComputedStyle(el)
    if (style.visibility === "hidden" || style.display === "none") continue
    checked += 1
    const size = parseFloat(style.fontSize)
    const bg = backdrop(el)
    const fg = rgba(style.color)
    fg[3] *= opacity(el)
    const shown = over(fg, bg)
    const [hi, lo] = [luminance(shown), luminance(bg)].sort((a, b) => b - a)
    const ratio = (hi + 0.05) / (lo + 0.05)
    if (size < 13 || ratio < 4.5) {
      offenders.push(`"${text.slice(0, 40)}" ${size}px ${ratio.toFixed(2)}:1 <${el.tagName.toLowerCase()}.${String(el.className).slice(0, 40)}>`)
    }
  }
  return { checked, offenders: offenders.slice(0, 25), total: offenders.length }
}

/** Visible fields and field buttons under `rootSelector` that miss the skin. */
function fieldSweep({ rootSelector, bg, border }) {
  const root = document.querySelector(rootSelector)
  if (!root) return { count: 0, bad: [`missing ${rootSelector}`] }
  const bad = []
  let count = 0
  const selector = "input:not([type=checkbox]):not([type=radio]):not([type=hidden]), select, textarea, .df-btn--field"
  for (const el of root.querySelectorAll(selector)) {
    if (!el.offsetParent || el.closest("[hidden], [inert]")) continue
    count += 1
    const cs = getComputedStyle(el)
    const height = Math.round(el.getBoundingClientRect().height)
    const isTextarea = el.tagName === "TEXTAREA"
    if ((!isTextarea && height !== 36) || cs.backgroundColor !== bg || cs.borderTopColor !== border) {
      bad.push(`${el.tagName.toLowerCase()}.${el.className} h=${height} bg=${cs.backgroundColor} border=${cs.borderTopColor}`)
    }
  }
  return { count, bad }
}

function horizontalOverflow() {
  return document.documentElement.scrollWidth - document.documentElement.clientWidth
}

// ---------------------------------------------------------------------------

await preflight()

let browser
let previousTheme
try {
  previousTheme = pinTheme("dark_4a")
  console.log(`→ Pinned Dark 4a (was ${previousTheme}); seeding ${DAY} and ${EMPTY_DAY}…`)
  seed("seed_schedule", {
    SEED_MODE: "schedules",
    SEED_USERNAME: USERNAME,
    SEED_SCHEDULES_JSON: JSON.stringify([
      { date: DAY, status: "active", blocks: BLOCKS },
      { date: EMPTY_DAY, status: "draft", blocks: [] },
    ]),
    SEED_MARKER: "seeded {count}",
  })

  browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: WIDE })
  const page = await context.newPage()
  await login(page, { waitForUsername: true })

  // Read the user's zone from the Inertia page, then fix the clock at 11:42.
  await page.goto(`${BASE}/schedule/${DAY}/`, { waitUntil: "networkidle" })
  const timeZone = await page.evaluate(() => {
    const data = JSON.parse(document.querySelector("#app")?.dataset.page ?? "{}")
    return data.props?.schedule_window?.time_zone ?? "UTC"
  })
  await page.clock.setFixedTime(zonedInstant(DAY, "11:42", timeZone))
  console.log(`→ Clock fixed at ${DAY} 11:42 ${timeZone}`)

  async function openSchedule(date) {
    await page.goto(`${BASE}/schedule/${date}/`, { waitUntil: "networkidle" })
    await page.evaluate(() => window.scrollTo(0, 0))
  }

  // ---- Wide schedule ------------------------------------------------------
  await page.setViewportSize(WIDE)
  await openSchedule(DAY)
  await page.waitForSelector('[data-testid="timeline-4a"]', { timeout: ELEMENT_TIMEOUT_MS })

  const wide = await page.evaluate(() => {
    const timeline = document.querySelector('[data-testid="timeline-4a"]')
    const scheme = getComputedStyle(document.documentElement).colorScheme
    const header = [...document.querySelectorAll(".df-btn--secondary")]
      .filter((el) => el.offsetParent && !el.closest('[data-testid="timeline-4a"], .settings-page'))
      .map((el) => `${el.textContent.trim()}:${Math.round(el.getBoundingClientRect().height)}`)
    const labels = [...document.querySelectorAll('[data-testid="gap-4a-label"]')].map((el) => el.textContent.trim())
    const ranges = [...document.querySelectorAll('[data-testid="gap-4a-range"]')].map((el) => el.textContent.trim())
    return {
      theme: document.documentElement.dataset.theme,
      scheme,
      timelineBottom: Math.round(timeline.getBoundingClientRect().bottom),
      viewport: window.innerHeight,
      scrollY: window.scrollY,
      header,
      labels,
      ranges,
      logout: !!document.querySelector(".logout-footer"),
    }
  })
  check(wide.theme === "dark_4a", `theme is ${wide.theme}, want dark_4a`)
  check(wide.scheme === "dark", `root color-scheme is ${wide.scheme}, want dark`)
  check(wide.scrollY === 0 && wide.timelineBottom <= wide.viewport,
    `day does not fit at 1440×900: timeline bottom ${wide.timelineBottom}px, viewport ${wide.viewport}px, scrollY ${wide.scrollY}`)
  check(wide.header.length >= 2 && wide.header.every((h) => h.endsWith(":32")),
    `header secondary buttons not all 32 px: ${wide.header.join(", ")}`)
  check(wide.labels.some((l) => l.includes("Free · 2h 50m")), `no "Free · 2h 50m" gap label: ${wide.labels.join(" | ")}`)
  check(wide.ranges.includes("12:10–15:00"), `no 12:10–15:00 gap range: ${wide.ranges.join(" | ")}`)
  check(!wide.logout, "Schedule renders the logout footer in Dark 4a")

  async function compactRow() {
    return page.evaluate(() => {
      const title = [...document.querySelectorAll(".time-block-4a .title")]
        .find((el) => el.textContent.trim() === "Short call")
      const card = title?.closest(".time-block-4a")
      if (!card) return { missing: true }
      const box = card.getBoundingClientRect()
      const parts = {
        checkbox: card.querySelector("input.checkbox"),
        handle: card.querySelector(".drag-handle"),
        title,
        duration: card.querySelector(".duration"),
        remove: card.querySelector(".delete-btn"),
      }
      const outside = []
      const unhittable = []
      for (const [name, el] of Object.entries(parts)) {
        if (!el) { outside.push(`${name}: missing`); continue }
        const r = el.getBoundingClientRect()
        if (r.top < box.top - 0.5 || r.bottom > box.bottom + 0.5 || r.left < box.left - 0.5 || r.right > box.right + 0.5) {
          outside.push(`${name} ${Math.round(r.top)}–${Math.round(r.bottom)} vs card ${Math.round(box.top)}–${Math.round(box.bottom)}`)
        }
        if (name === "title" || name === "duration") continue
        const hit = document.elementFromPoint(r.left + r.width / 2, r.top + r.height / 2)
        const owner = name === "checkbox" ? hit?.closest(".check-hit") ?? hit : hit
        if (!owner || !(el.contains(owner) || owner.contains(el))) unhittable.push(`${name} → ${hit?.className ?? "nothing"}`)
      }
      return {
        height: Math.round(box.height * 10) / 10,
        compact: card.classList.contains("is-compact"),
        duration: parts.duration?.textContent.trim(),
        outside,
        unhittable,
      }
    })
  }

  const rowWide = await compactRow()
  check(!rowWide.missing, "Short call block not rendered")
  if (!rowWide.missing) {
    check(rowWide.compact && rowWide.height >= 27.5 && rowWide.height <= 36,
      `Short call row: compact=${rowWide.compact} height=${rowWide.height}px, want a compact row of 28–35 px`)
    check(rowWide.duration === "5m", `Short call duration "${rowWide.duration}", want 5m`)
    check(rowWide.outside.length === 0, `compact row parts outside the card: ${rowWide.outside.join("; ")}`)
  }

  const chatWide = await page.evaluate(() => {
    const input = document.querySelector(".command-input")
    if (!input) return null
    const cs = getComputedStyle(input)
    return {
      variant: input.className,
      font: cs.fontFamily,
      size: cs.fontSize,
      color: cs.color,
      placeholder: getComputedStyle(input, "::placeholder").color,
    }
  })
  function checkChat(chat, where) {
    if (!chat) return fail(`${where}: chat input not rendered`)
    check(!/mono|Menlo|SFMono/i.test(chat.font), `${where}: chat input font is monospace (${chat.font})`)
    check(chat.size === "14px", `${where}: chat input ${chat.size}, want 14px`)
    check(chat.color === SECONDARY_TEXT && chat.placeholder === SECONDARY_TEXT,
      `${where}: chat text ${chat.color} / placeholder ${chat.placeholder}, want ${SECONDARY_TEXT}`)
  }
  checkChat(chatWide, "1440 sidebar")
  check(chatWide?.variant.includes("variant-sidebar"), `1440 chat variant ${chatWide?.variant}, want sidebar`)

  await page.locator(".add-btn").first().click()
  await page.waitForSelector("form .title-input", { timeout: ELEMENT_TIMEOUT_MS })
  await page.mouse.move(0, 0) // keep hover borders out of the measurement
  const addForm = await page.evaluate(fieldSweep, { rootSelector: "form:has(.title-input)", bg: FIELD_BG, border: CONTROL_BORDER })
  check(addForm.count >= 5 && addForm.bad.length === 0,
    `Add Block form (wide) fields: ${addForm.count} checked; ${addForm.bad.join("; ")}`)
  await page.locator(".cancel-btn").click()

  const sweepWide = await page.evaluate(textSweep, ".schedule-page")
  console.log(`→ Text sweep, schedule 1440: ${sweepWide.checked} text nodes`)
  check(sweepWide.total === 0, `text floor, schedule 1440 (${sweepWide.checked} nodes): ${sweepWide.offenders.join(" | ")}`)

  // ---- Narrow schedule ----------------------------------------------------
  await page.setViewportSize(NARROW)
  await openSchedule(DAY)
  await page.waitForSelector('[data-testid="timeline-4a"]', { timeout: ELEMENT_TIMEOUT_MS })
  check(await page.evaluate(horizontalOverflow) === 0, "schedule scrolls sideways at 390 px")

  await page.locator(".title", { hasText: "Short call" }).scrollIntoViewIfNeeded()
  const rowNarrow = await compactRow()
  if (!rowNarrow.missing) {
    check(rowNarrow.outside.length === 0, `390 compact row parts outside the card: ${rowNarrow.outside.join("; ")}`)
    check(rowNarrow.unhittable.length === 0, `390 compact row controls not independently tappable: ${rowNarrow.unhittable.join("; ")}`)
  }

  const chatNarrow = await page.evaluate(() => {
    const input = document.querySelector(".command-input")
    if (!input) return null
    const cs = getComputedStyle(input)
    return { variant: input.className, font: cs.fontFamily, size: cs.fontSize, color: cs.color, placeholder: getComputedStyle(input, "::placeholder").color }
  })
  checkChat(chatNarrow, "390 dock")
  check(chatNarrow?.variant.includes("variant-dock"), `390 chat variant ${chatNarrow?.variant}, want dock`)

  await page.evaluate(() => window.scrollTo(0, 0))
  const sweepNarrow = await page.evaluate(textSweep, ".schedule-page")
  check(sweepNarrow.total === 0, `text floor, schedule 390 (${sweepNarrow.checked} nodes): ${sweepNarrow.offenders.join(" | ")}`)

  // ---- Empty draft day ----------------------------------------------------
  for (const viewport of [WIDE, NARROW]) {
    await page.setViewportSize(viewport)
    await openSchedule(EMPTY_DAY)
    const empty = await page.evaluate(() => {
      const state = document.querySelector('[data-testid="empty-day-state"]')
      const create = document.querySelector('[data-testid="empty-day-create-template"]')
      const plan = document.querySelector('[data-testid="empty-day-plan-with-ai"]')
      if (!state || !create || !plan) return { missing: true }
      const a = create.getBoundingClientRect()
      const b = plan.getBoundingClientRect()
      return { stacked: b.top >= a.bottom - 0.5, sideBySide: Math.abs(a.top - b.top) < 1 }
    })
    const where = `${viewport.width}px empty day`
    if (empty.missing) {
      fail(`${where}: empty-day state missing (the user may have a weekend template)`)
    } else if (viewport === NARROW) {
      check(empty.stacked, `${where}: actions are not stacked`)
    }
    const sweepEmpty = await page.evaluate(textSweep, ".schedule-page")
    check(sweepEmpty.total === 0, `text floor, ${where}: ${sweepEmpty.offenders.join(" | ")}`)
  }

  // ---- Settings -----------------------------------------------------------
  for (const viewport of [WIDE, NARROW]) {
    await page.setViewportSize(viewport)
    await page.goto(`${BASE}/settings/#appearance`, { waitUntil: "networkidle" })
    for (const topic of SETTINGS_TOPICS) {
      await page.evaluate((hash) => { window.location.hash = hash }, topic)
      await page.waitForTimeout(250)
      const where = `${viewport.width}px settings/${topic}`
      await page.mouse.move(0, 0)
      const fields = await page.evaluate(fieldSweep, {
        rootSelector: `[data-settings-topic="${topic}"]`, bg: FIELD_BG, border: CONTROL_BORDER,
      })
      check(fields.bad.length === 0, `${where} fields: ${fields.bad.join("; ")}`)
      if (viewport === NARROW) {
        check(await page.evaluate(horizontalOverflow) === 0, `${where} scrolls sideways`)
      }
      const sweep = await page.evaluate(textSweep, ".settings-page")
      console.log(`→ ${where}: ${fields.count} fields, ${sweep.checked} text nodes`)
      check(sweep.total === 0, `text floor, ${where}: ${sweep.offenders.join(" | ")}`)
    }
    const logout = await page.evaluate(() =>
      [...document.querySelectorAll('[data-testid="settings-logout"]')]
        .filter((el) => el.offsetParent)
        .map((el) => ({ inNav: !!el.closest("nav.settings-nav"), height: Math.round(el.getBoundingClientRect().height) })),
    )
    const wantNav = viewport === WIDE
    check(logout.length === 1 && logout[0].inNav === wantNav && logout[0].height === 32,
      `${viewport.width}px settings Log out: ${JSON.stringify(logout)}, want one 32 px button ${wantNav ? "in the nav" : "below the content"}`)
  }
} finally {
  await browser?.close()
  cleanupSchedules([DAY, EMPTY_DAY])
  restoreTheme(previousTheme)
}

if (failures.length) {
  console.error(`\n❌ ${failures.length} Dark 4a check(s) failed:`)
  for (const message of failures) console.error(`   - ${message}`)
  process.exitCode = 1
} else {
  console.log("\n✅ Dark 4a day fit, controls and text floor look correct.")
}
