// Feature 0113 — phone schedule pass at 390 x 844 and 375 x 667 (Dark 4a).
//
// Pins the playwright user to Dark 4a, seeds Sunday 22 Nov 2026 with six
// blocks and gaps, and for each viewport (touch, isMobile) checks:
//   - no horizontal scroll; the phone list renders; rows that fit above the
//     chat dock are logged (the 375 x 667 count is informational);
//   - the chat dock rests as one 52 px row and the FAB is 56 px, 16 px from the
//     right and 16 px above the dock;
//   - FAB -> add sheet -> Save adds a block and shows `Block added`, which
//     disappears after about 5 s; × shows `Block deleted` and its Undo
//     restores the block; a row tap opens the title-only edit sheet and the
//     rename lands in the list;
//   - a focused chat field hides the FAB, shows the chips and adds no privacy
//     line; ⓘ opens the full text; the gear menu opens.
// Screenshots go to SCREENSHOT_DIR (default /workspace/pr8-screens).
//
// Run from frontend/:
//   node scripts/playwright/mobile-day-fit.mjs [--cleanup]
//
// Pre-reqs: Django :8006, Vite :5173, playwright user. No LLM key. LOCAL
// DEVELOPMENT ONLY: the seed step truncates the target schedule and the script
// writes blocks to it.

import { mkdirSync } from "node:fs"
import { chromium } from "@playwright/test"
import {
  ELEMENT_TIMEOUT_MS,
  USERNAME,
  BASE,
  cleanupSchedules,
  login,
  makeFailAggregator,
  pinTheme,
  preflight,
  restoreTheme,
  seed,
} from "./test-utils.mjs"

const DAY = "2026-11-22"
const SCREENSHOT_DIR = process.env.SCREENSHOT_DIR || "/workspace/pr8-screens"
const VIEWPORTS = [
  { name: "390x844", width: 390, height: 844 },
  { name: "375x667", width: 375, height: 667 },
]
const BLOCKS = [
  ["Standup", "09:00", "09:15", "work"],
  ["Deep work", "09:30", "11:00", "work"],
  ["Email", "11:00", "11:30", "work"],
  ["Lunch", "12:00", "12:45", "personal"],
  ["Gym", "13:30", "14:30", "health"],
  ["Review", "15:00", "15:30", "work"],
].map(([title, start_time, end_time, category], index) => ({
  title, start_time, end_time, category, sort_order: index * 10,
}))

const { failures, fail } = makeFailAggregator()
const check = (condition, message) => { if (!condition) fail(message) }

await preflight()
mkdirSync(SCREENSHOT_DIR, { recursive: true })

let browser
let previousTheme
try {
  previousTheme = pinTheme("dark_4a")
  console.log(`→ Pinned Dark 4a (was ${previousTheme})`)
  browser = await chromium.launch({ headless: true })

  for (const vp of VIEWPORTS) {
    console.log(`→ ${vp.name}: seeding ${DAY}`)
    // Each viewport starts from the same day: the previous one added and renamed blocks.
    seed("seed_schedule", {
      SEED_MODE: "schedules",
      SEED_USERNAME: USERNAME,
      SEED_SCHEDULES_JSON: JSON.stringify([{ date: DAY, status: "active", blocks: BLOCKS }]),
      SEED_MARKER: "seeded {count}",
    })
    const context = await browser.newContext({
      viewport: { width: vp.width, height: vp.height },
      hasTouch: true,
      isMobile: true,
      deviceScaleFactor: 2,
    })
    const page = await context.newPage()
    const shot = (state) => page.screenshot({ path: `${SCREENSHOT_DIR}/${vp.name}-${state}.png` })
    const where = (message) => `${vp.name}: ${message}`
    const overflow = () => page.evaluate(() =>
      document.documentElement.scrollWidth - document.documentElement.clientWidth)
    const rowTitles = () => page.locator('[data-testid="mobile-block-row"] .title').allTextContents()

    await login(page)
    await page.goto(`${BASE}/schedule/${DAY}/`, { waitUntil: "networkidle" })
    await page.waitForSelector('[data-testid="timeline-mobile"]', { timeout: ELEMENT_TIMEOUT_MS })
    await shot("1-list")

    check(await overflow() <= 0, where("page scrolls sideways"))
    check((await rowTitles()).length === BLOCKS.length, where(`block rows ${(await rowTitles()).length}, want ${BLOCKS.length}`))

    const layout = await page.evaluate(() => {
      const rect = (selector) => document.querySelector(selector)?.getBoundingClientRect()
      const bar = rect('[data-testid="command-bar"]')
      const fab = rect('[data-testid="mobile-fab"]')
      const rows = [...document.querySelectorAll('[data-testid="mobile-block-row"], [data-testid="mobile-gap-row"]')]
      const fitting = bar ? rows.filter((row) => row.getBoundingClientRect().bottom <= bar.top).length : 0
      return {
        barHeight: bar?.height, barTop: bar?.top,
        fabW: fab?.width, fabH: fab?.height,
        fabRight: fab ? window.innerWidth - fab.right : null,
        fabGap: fab && bar ? bar.top - fab.bottom : null,
        rows: rows.length, fitting,
      }
    })
    console.log(`  rows ${layout.rows}, ${layout.fitting} fully above the chat dock without scrolling`)
    check(layout.barHeight === 52, where(`chat dock rests at ${layout.barHeight}px, want 52`))
    check(layout.fabW === 56 && layout.fabH === 56, where(`FAB ${layout.fabW}x${layout.fabH}, want 56x56`))
    check(Math.abs(layout.fabRight - 16) <= 1, where(`FAB right offset ${layout.fabRight}, want 16`))
    check(Math.abs(layout.fabGap - 16) <= 1, where(`FAB sits ${layout.fabGap}px above the dock, want 16`))

    // Add through the FAB.
    await page.locator('[data-testid="mobile-fab"]').tap()
    await page.waitForSelector('[data-testid="bottom-sheet"] .title-input', { timeout: ELEMENT_TIMEOUT_MS })
    await shot("2-add-sheet")
    await page.locator('[data-testid="bottom-sheet"] .title-input').fill("Sheet block")
    await page.locator('[data-testid="bottom-sheet"] input[type="time"]').first().fill("16:00")
    await page.locator('[data-testid="bottom-sheet"] input[type="time"]').nth(1).fill("16:30")
    await page.locator('[data-testid="bottom-sheet"] .submit-btn').tap()
    await page.waitForSelector('[data-testid="undo-toast"]', { timeout: ELEMENT_TIMEOUT_MS })
    check(((await page.locator('[data-testid="undo-toast"]').textContent()) || "").includes("Block added"),
      where("add toast does not say Block added"))
    check((await rowTitles()).includes("Sheet block"), where("added block missing from the list"))
    await shot("3-added-toast")
    const toastGone = await page.waitForSelector('[data-testid="undo-toast"]', { state: "detached", timeout: 7000 })
      .then(() => true).catch(() => false)
    check(toastGone, where("toast still visible after 7 s"))

    // Delete then Undo.
    const before = (await rowTitles()).length
    await page.locator('[data-testid="mobile-block-row"]', { hasText: "Sheet block" }).locator(".delete-btn").tap()
    await page.waitForSelector('[data-testid="undo-toast"]', { timeout: ELEMENT_TIMEOUT_MS })
    check(((await page.locator('[data-testid="undo-toast"]').textContent()) || "").includes("Block deleted"),
      where("delete toast does not say Block deleted"))
    check((await rowTitles()).length === before - 1, where("block not removed on ×"))
    await shot("4-deleted-toast")
    const undo = page.locator('[data-testid="undo-toast"] .toast-undo-btn')
    const undoBox = await undo.boundingBox()
    check(undoBox && undoBox.height >= 44, where(`Undo hit area ${undoBox?.height}px, want >= 44`))
    await undo.tap()
    await page.waitForFunction(
      (n) => document.querySelectorAll('[data-testid="mobile-block-row"]').length === n, before,
      { timeout: ELEMENT_TIMEOUT_MS },
    ).catch(() => fail(where("Undo did not restore the block")))

    // Edit sheet rename.
    await page.locator('[data-testid="mobile-block-row"] .title', { hasText: "Gym" }).tap()
    await page.waitForSelector('[data-testid="edit-block-form"]', { timeout: ELEMENT_TIMEOUT_MS })
    await shot("5-edit-sheet")
    await page.locator('[data-testid="edit-block-title"]').fill("Gym time")
    await page.locator('[data-testid="edit-block-save"]').tap()
    await page.waitForSelector('[data-testid="edit-block-form"]', { state: "detached", timeout: ELEMENT_TIMEOUT_MS })
    check((await rowTitles()).includes("Gym time"), where("rename missing from the list"))

    // Chat focus: FAB hidden, chips shown, no privacy line, no sideways scroll.
    await page.locator('[data-testid="chat-input"]').tap()
    await page.waitForTimeout(300)
    check(!(await page.locator('[data-testid="mobile-fab"]').isVisible()), where("FAB visible while the chat field is focused"))
    check(await page.locator('[data-testid="chat-result-chip"]').isVisible(), where("chips not shown while focused"))
    check(!(((await page.locator('[data-testid="command-bar"]').textContent()) || "").includes("may be sent to the AI provider")),
      where("a privacy line is rendered on the phone panel"))
    check(await overflow() <= 0, where("page scrolls sideways with chips open"))
    await shot("6-chat-focused")
    await page.locator('[data-testid="chat-input"]').evaluate((el) => el.blur())
    await page.waitForTimeout(200)
    check(await page.locator('[data-testid="mobile-fab"]').isVisible(), where("FAB did not return after blur"))

    await page.locator('[data-testid="chat-privacy-info"]').tap()
    await page.waitForSelector('[data-testid="chat-privacy-full"]', { timeout: ELEMENT_TIMEOUT_MS })
    await shot("7-privacy-sheet")
    await page.locator('[data-testid="sheet-close"]').tap()

    await page.locator('[data-testid="mobile-gear"]').tap()
    await page.waitForTimeout(300)
    await shot("8-gear-menu")
    await context.close()
  }

  console.log("\n=== Verdict ===")
  if (failures.length === 0) {
    console.log(`✅ PASS — phone pass at ${VIEWPORTS.map((v) => v.name).join(" and ")}; screenshots in ${SCREENSHOT_DIR}`)
  } else {
    console.log("❌ FAIL —")
    for (const reason of failures) console.log(`    • ${reason}`)
    process.exitCode = 1
  }
} catch (error) {
  console.error("\nScript error:")
  console.error(error)
  process.exitCode = 2
} finally {
  await browser?.close()
  restoreTheme(previousTheme)
  cleanupSchedules([DAY])
}
