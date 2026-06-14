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
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"
const SCHEDULE_DATE = "2027-03-15"
const STUB_HEIGHT_PX = 60 // STUB_MINUTES(30) × PX_PER_MINUTE(2)
const REPO_ROOT = resolve(process.cwd(), "..")

function fail(msg) {
  console.error(`\n❌ ${msg}`)
  process.exit(1)
}

console.log("→ Seeding 09:00–18:00 schedule…")
execSync(
  `uv run python backend/manage.py shell -c "
from datetime import date
from django.contrib.auth.models import User
from schedules.models import Schedule, TimeBlock
u = User.objects.get(username='${USERNAME}')
d = date.fromisoformat('${SCHEDULE_DATE}')
s, _ = Schedule.objects.get_or_create(user=u, date=d, defaults={'status': 'active'})
s.status = 'active'
s.save(update_fields=['status'])
TimeBlock.objects.filter(schedule=s).delete()
TimeBlock.objects.create(schedule=s, title='Morning focus', start_time='09:00', end_time='12:00', category='work', sort_order=0)
TimeBlock.objects.create(schedule=s, title='Afternoon work', start_time='13:00', end_time='18:00', category='work', sort_order=10)
print('seeded', s.id)
"`,
  { cwd: REPO_ROOT, stdio: "inherit" },
)

const browser = await chromium.launch({ headless: true })
try {
  const page = await browser.newPage()

  console.log("→ Logging in…")
  await page.goto(`${BASE}/accounts/login/`, { waitUntil: "networkidle" })
  await page.waitForSelector("#username")
  await page.fill("#username", USERNAME)
  await page.fill("#password", PASSWORD)
  await Promise.all([
    page.waitForURL(/\/schedule\//),
    page.click('button[type="submit"]'),
  ])

  console.log(`→ Opening /schedule/${SCHEDULE_DATE}/…`)
  await page.goto(`${BASE}/schedule/${SCHEDULE_DATE}/`, {
    waitUntil: "networkidle",
  })

  await page.waitForSelector(".gap-slot", { timeout: 10000 })

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
  if (Math.abs(leading.slotHeight - STUB_HEIGHT_PX) > 4) {
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
  if (Math.abs(trailing.slotHeight - STUB_HEIGHT_PX) > 4) {
    fail(
      `Trailing gap height ${trailing.slotHeight}px (inline ${trailing.inlineHeight}), expected ~${STUB_HEIGHT_PX}px`,
    )
  }

  console.log("→ Clicking leading stub to verify full-range prefill…")
  await page.locator(".gap-slot.compact").first().click()
  await page.waitForSelector(".add-form input[type='time']", { timeout: 5000 })

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
  await browser.close()
}
