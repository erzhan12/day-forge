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
//
// Dates are computed from Django's `timezone.localdate()` at run time, so
// the test doesn't rot when the calendar advances.
//
// Run from frontend/:
//   node scripts/playwright/skipped-tasks-today-aware.mjs

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

const REPO_ROOT = resolve(process.cwd(), "..")

// Read Django's notion of "today" so the test doesn't rot on the
// calendar. The shell preamble line ("X objects imported automatically...")
// is filtered out by matching the ISO date on its own line.
function djangoToday() {
  const out = execSync(
    `uv run python backend/manage.py shell -c "from django.utils import timezone; print(timezone.localdate().isoformat())"`,
    { cwd: REPO_ROOT },
  ).toString()
  const match = out.match(/^\d{4}-\d{2}-\d{2}$/m)
  if (!match) throw new Error(`could not parse Django date from:\n${out}`)
  return match[0]
}

function daysBefore(isoDate, n) {
  const d = new Date(isoDate + "T00:00:00Z")
  d.setUTCDate(d.getUTCDate() - n)
  return d.toISOString().slice(0, 10)
}

const TODAY = djangoToday()
const PAST_MIXED = daysBefore(TODAY, 6)
const PAST_CLEAN = daysBefore(TODAY, 8)

console.log(`-> Seeding 3 schedules (today=${TODAY}, mixed=${PAST_MIXED}, clean=${PAST_CLEAN}) via Django shell...`)
try {
  execSync(
    `uv run python backend/manage.py shell -c "
from schedules.models import Schedule, TimeBlock
from django.contrib.auth.models import User
import datetime as dt
u = User.objects.get(username='${USERNAME}')
today_d = dt.date.fromisoformat('${TODAY}')
mixed_d = dt.date.fromisoformat('${PAST_MIXED}')
clean_d = dt.date.fromisoformat('${PAST_CLEAN}')

# Today: past-uncompleted, past-completed (control), future-uncompleted
today, _ = Schedule.objects.update_or_create(user=u, date=today_d, defaults={'status':'active'})
today.time_blocks.all().delete()
TimeBlock.objects.create(schedule=today, title='Morning standup',  start_time='08:00', end_time='09:00', category='work',     is_completed=False, sort_order=0)
TimeBlock.objects.create(schedule=today, title='Coffee',           start_time='10:00', end_time='10:30', category='personal', is_completed=True,  sort_order=1)
TimeBlock.objects.create(schedule=today, title='Afternoon focus',  start_time='14:00', end_time='15:00', category='work',     is_completed=False, sort_order=2)

# Past mixed: 2 blocks, 1 uncompleted ('Email')
mixed, _ = Schedule.objects.update_or_create(user=u, date=mixed_d, defaults={'status':'active'})
mixed.time_blocks.all().delete()
TimeBlock.objects.create(schedule=mixed, title='Standup', start_time='09:00', end_time='09:30', category='work', is_completed=True, sort_order=0)
TimeBlock.objects.create(schedule=mixed, title='Email',   start_time='10:00', end_time='10:30', category='work', is_completed=False, sort_order=1)

# Past clean: 1 block fully completed - Skipped section MUST be hidden
clean, _ = Schedule.objects.update_or_create(user=u, date=clean_d, defaults={'status':'active'})
clean.time_blocks.all().delete()
TimeBlock.objects.create(schedule=clean, title='Workout', start_time='09:00', end_time='10:00', category='health', is_completed=True, sort_order=0)
print('seeded today/past-mixed/past-clean')
"`,
    { stdio: "inherit", cwd: REPO_ROOT },
  )
} catch (err) {
  console.error("\nSeed failed (Django running? user 'playwright' exists?)")
  console.error(err.message)
  process.exit(2)
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await context.newPage()

// Install fake clock BEFORE any navigation so Date.now() / new Date() in
// SkippedTasks.vue (both the "today vs past" classifier and the
// HH:MM filter) are pinned. Start at 11:30 local — past the 09:00 block
// end but before the 14:00 block start.
await page.clock.install({ time: new Date(`${TODAY}T11:30:00`) })

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
  console.log(`-> Login (clock pinned to ${TODAY}T11:30 local)...`)
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
  await page.clock.setSystemTime(new Date(`${TODAY}T15:30:00`))
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
