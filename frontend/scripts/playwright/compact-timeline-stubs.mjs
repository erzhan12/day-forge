// Feature 0017 — compact timeline edge stubs e2e check.
//
// Seeds a 09:00–18:00 day, asserts leading/trailing gap slots render
// at stub height (~60px) with compact styling, and stub click emits
// the full semantic range into the add form.
//
// Run from frontend/:
//   node scripts/playwright/compact-timeline-stubs.mjs
//
// Pre-reqs: Django :8006, Vite :5173, playwright user. No LLM key.

import { chromium } from "@playwright/test"
import {
  BASE,
  ELEMENT_TIMEOUT_MS,
  UI_RESPONSE_TIMEOUT_MS,
  USERNAME,
  cleanupSchedules,
  failFast,
  login,
  preflight,
  seed,
} from "./test-utils.mjs"
const SCHEDULE_DATE = "2027-03-15"
const STUB_HEIGHT_PX = 60 // STUB_MINUTES(30) × PX_PER_MINUTE(2)
// Slot-height asserts allow ±4px: the rendered slot includes GapSlot border
// (1px dashed top+bottom) and box-sizing padding, plus sub-pixel browser
// rounding of getBoundingClientRect — so the measured height lands a few px off
// the exact STUB_HEIGHT_PX without indicating a layout regression.
const STUB_HEIGHT_TOLERANCE_PX = 4
await preflight()
const fail = failFast

let browser
try {
  console.log("→ Seeding 09:00–18:00 schedule…")
  seed("seed_schedule", {
    SEED_MODE: "schedules",
    SEED_USERNAME: USERNAME,
    SEED_SCHEDULES_JSON: JSON.stringify([
      {
        date: SCHEDULE_DATE,
        status: "active",
        blocks: [
          { title: "Morning focus", start_time: "09:00", end_time: "12:00", category: "work", sort_order: 0 },
          { title: "Afternoon work", start_time: "13:00", end_time: "18:00", category: "work", sort_order: 10 },
        ],
      },
    ]),
    SEED_MARKER: "seeded {id}",
  })

  browser = await chromium.launch({ headless: true })
  const page = await browser.newPage()

  console.log("→ Logging in…")
  await login(page, { waitForUsername: true })

  console.log(`→ Opening /schedule/${SCHEDULE_DATE}/…`)
  await page.goto(`${BASE}/schedule/${SCHEDULE_DATE}/`, {
    waitUntil: "networkidle",
  })

  await page.waitForSelector(".gap-slot", { timeout: UI_RESPONSE_TIMEOUT_MS })

  const gapInfo = await page.evaluate(() => {
    const slots = [...document.querySelectorAll(".schedule-slot")]
    return slots
      .filter((slot) => slot.querySelector(".gap-slot"))
      .map((slot) => {
        const gap = slot.querySelector(".gap-slot")
        const rect = slot.getBoundingClientRect()
        return {
          text: gap?.textContent?.trim() ?? "",
          compact: gap?.classList.contains("compact") ?? false,
          slotHeight: Math.round(rect.height),
          inlineHeight: slot.style.height,
        }
      })
  })

  console.log("→ Gap slots found:", JSON.stringify(gapInfo, null, 2))

  if (gapInfo.length < 2) {
    fail(`Expected ≥2 gap slots (leading + trailing), got ${gapInfo.length}`)
  }

  const leading = gapInfo[0]
  const trailing = gapInfo[gapInfo.length - 1]

  if (!leading.compact) {
    fail(`Leading gap missing .compact class — text: ${leading.text}`)
  }
  if (!leading.text.includes("earlier")) {
    fail(`Leading gap missing "earlier" hint — text: ${leading.text}`)
  }
  if (Math.abs(leading.slotHeight - STUB_HEIGHT_PX) > STUB_HEIGHT_TOLERANCE_PX) {
    fail(
      `Leading gap height ${leading.slotHeight}px (inline ${leading.inlineHeight}), expected ~${STUB_HEIGHT_PX}px`,
    )
  }

  if (!trailing.compact) {
    fail(`Trailing gap missing .compact class — text: ${trailing.text}`)
  }
  if (!trailing.text.includes("later")) {
    fail(`Trailing gap missing "later" hint — text: ${trailing.text}`)
  }
  if (Math.abs(trailing.slotHeight - STUB_HEIGHT_PX) > STUB_HEIGHT_TOLERANCE_PX) {
    fail(
      `Trailing gap height ${trailing.slotHeight}px (inline ${trailing.inlineHeight}), expected ~${STUB_HEIGHT_PX}px`,
    )
  }

  console.log("→ Clicking leading stub to verify full-range prefill…")
  await page.locator(".gap-slot.compact").first().click()
  await page.waitForSelector(".add-form input[type='time']", { timeout: ELEMENT_TIMEOUT_MS })

  const prefill = await page.evaluate(() => {
    const times = [...document.querySelectorAll(".add-form input[type='time']")]
    const start = times[0]
    const end = times[1]
    return { start: start?.value, end: end?.value }
  })

  if (prefill.start !== "06:00" || prefill.end !== "09:00") {
    fail(
      `Add form prefill expected 06:00–09:00, got ${prefill.start}–${prefill.end}`,
    )
  }

  console.log("\n✅ Compact timeline stubs look correct.")
} finally {
  await browser?.close()
  cleanupSchedules([SCHEDULE_DATE])
}
