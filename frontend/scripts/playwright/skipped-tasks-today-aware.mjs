// Phase 6 Test 10: SkippedTasks today-aware filtering.
//
// Verifies four invariants of frontend/src/components/SkippedTasks.vue:
//   A. Today, before block end_time → block NOT in Skipped (still future-window).
//   B. Today, after block end_time + setInterval tick → block IS in Skipped.
//   C. Past day → every uncompleted block in Skipped, regardless of clock.
//   D. Past day with no uncompleted → entire <section> hidden (no header).
//
// Wall-clock dependency is faked via Playwright's `page.clock` API, so
// the test is deterministic regardless of when it runs.
//
// Pre-reqs:
//   * Django :8006, Vite :5173.
//   * `playwright` user, `playwright-pw-do-not-use-in-prod` password.
//   * Schedules seeded for 2026-05-02 (clean), 2026-05-04 (mixed),
//     2026-05-06 (today). See the seed snippet in the parent shell.
//   * Django's `timezone.localdate()` must equal 2026-05-06 at run time
//     (verified via `make shell` if in doubt).
//
// Run from frontend/:
//   node scripts/playwright/skipped-tasks-today-aware.mjs

import { chromium } from "@playwright/test"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

const TODAY = "2026-05-06"
const PAST_MIXED = "2026-05-04"
const PAST_CLEAN = "2026-05-02"

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await context.newPage()

// Install fake clock BEFORE any navigation so Date.now() / new Date() in
// SkippedTasks.vue (both the "today vs past" classifier and the
// HH:MM filter) are pinned. Start at 11:30 local — past the 09:00 block
// end but before the 14:00 block start.
await page.clock.install({ time: new Date("2026-05-06T11:30:00") })

function fail(msg) {
  console.error(`\n FAIL ${msg}`)
  throw new Error(msg)
}

async function login() {
  await page.goto(`${BASE}/accounts/login/`, { waitUntil: "networkidle" })
  await page.fill("#username", USERNAME)
  await page.fill("#password", PASSWORD)
  await Promise.all([
    page.waitForURL(/\/schedule\//),
    page.click('button[type="submit"]'),
  ])
}

async function getSkippedTitles() {
  const items = page.locator(".skipped-tasks .skipped-row .title")
  const n = await items.count()
  const out = []
  for (let i = 0; i < n; i++) {
    out.push((await items.nth(i).textContent())?.trim())
  }
  return out
}

async function isSkippedSectionVisible() {
  return (await page.locator(".skipped-tasks").count()) > 0
}

try {
  console.log("-> Login (clock pinned to 2026-05-06T11:30 local)...")
  await login()

  // ── Inv A: today @ 11:30 — only past-window block in Skipped ──
  console.log(`-> Goto /analytics/${TODAY}/ at faked 11:30...`)
  await page.goto(`${BASE}/analytics/${TODAY}/`, { waitUntil: "networkidle" })
  let titles = await getSkippedTitles()
  console.log("   Skipped:", titles)
  if (!(titles.length === 1 && titles[0] === "Morning standup")) {
    fail(`A: expected ['Morning standup'] only, got ${JSON.stringify(titles)}`)
  }

  // ── Inv B: advance clock to 15:30 → setInterval tick adds future block ──
  console.log("-> Advance fake clock to 15:30, run 60s (fires setInterval)...")
  await page.clock.setSystemTime(new Date("2026-05-06T15:30:00"))
  await page.clock.runFor(60_000)
  await page
    .locator(".skipped-tasks .skipped-row")
    .nth(1)
    .waitFor({ state: "visible", timeout: 5000 })
  titles = await getSkippedTitles()
  console.log("   Skipped:", titles)
  if (
    !(
      titles.length === 2 &&
      titles.includes("Morning standup") &&
      titles.includes("Afternoon focus")
    )
  ) {
    fail(
      `B: expected both 'Morning standup' and 'Afternoon focus' after 15:30, got ${JSON.stringify(titles)}`,
    )
  }
  // Also: 'Coffee' (completed) must NEVER appear.
  if (titles.includes("Coffee")) {
    fail("B: completed 'Coffee' block must not appear in Skipped")
  }

  // ── Inv C: past mixed day — uncompleted shown regardless of clock ──
  console.log(`-> Goto /analytics/${PAST_MIXED}/ (past mixed)...`)
  await page.goto(`${BASE}/analytics/${PAST_MIXED}/`, { waitUntil: "networkidle" })
  titles = await getSkippedTitles()
  console.log("   Skipped:", titles)
  if (!(titles.length === 1 && titles[0] === "Email")) {
    fail(`C: expected ['Email'] on past mixed day, got ${JSON.stringify(titles)}`)
  }

  // ── Inv D: past clean day — entire section hidden ──
  console.log(`-> Goto /analytics/${PAST_CLEAN}/ (past, fully completed)...`)
  await page.goto(`${BASE}/analytics/${PAST_CLEAN}/`, { waitUntil: "networkidle" })
  if (await isSkippedSectionVisible()) {
    fail("D: .skipped-tasks must be entirely hidden on a fully-completed past day")
  }
  console.log("   Skipped section: HIDDEN")

  console.log("\nPASS - all 4 today-aware-filter invariants hold.")
  process.exitCode = 0
} catch (err) {
  console.error("\nScript error:")
  console.error(err)
  process.exitCode = 2
} finally {
  await browser.close()
}
