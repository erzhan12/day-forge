// E2E reproduction for the TimeBlock double-PATCH race.
//
// Phase 5 Test 5 surfaced the bug: pressing Enter on an inline title
// edit fired TWO PATCH /api/blocks/<id>/ requests instead of one,
// because both ``@keydown.enter`` and ``@blur`` bind to ``saveTitle``
// and the blur handler races against Inertia's prop reload.
//
// This script intercepts network calls, performs the rename via UI,
// and asserts exactly 1 PATCH fires. Pre-seeds the test data via a
// Django shell call so the test is hermetic.
//
// Run from frontend/:  node scripts/playwright/timeblock-double-save.mjs
//
// ⚠️  See template-editor-layout.mjs for warnings about the
// ``playwright`` test user (LOCAL DEV ONLY).

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

// A future date well outside any human use, deterministic for the test.
const SCHEDULE_DATE = "2026-08-17"  // Monday
const SEED_TITLE = "Original block"

const REPO_ROOT = resolve(process.cwd(), "..")

// Pre-seed: ensure the playwright user has a Schedule on SCHEDULE_DATE
// with exactly one TimeBlock named SEED_TITLE. Idempotent.
console.log("→ Seeding test data via Django shell…")
execSync(
  `uv run python backend/manage.py shell -c "
from schedules.models import Schedule, TimeBlock
from django.contrib.auth.models import User
import datetime
u = User.objects.get(username='${USERNAME}')
s, _ = Schedule.objects.update_or_create(
    user=u, date=datetime.date(2026, 8, 17), defaults={'status': 'active'}
)
TimeBlock.objects.filter(schedule=s).delete()
TimeBlock.objects.create(
    schedule=s, title='${SEED_TITLE}', start_time='09:00',
    end_time='10:00', category='work',
)
print('seeded schedule', s.id)
"`,
  { stdio: "inherit", cwd: REPO_ROOT },
)

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({
  viewport: { width: 1280, height: 800 },
})
const page = await context.newPage()

// Network spy: count PATCH /api/blocks/<id>/ calls and capture bodies
// so we can show the duplicate when it fires.
const patchCalls = []
page.on("request", (req) => {
  if (
    req.method() === "PATCH" &&
    /\/api\/blocks\/\d+\/$/.test(req.url())
  ) {
    patchCalls.push({
      url: req.url(),
      body: req.postData(),
      timestamp: Date.now(),
    })
  }
})

try {
  console.log("→ Logging in…")
  await page.goto(`${BASE}/accounts/login/`, { waitUntil: "networkidle" })
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

  // Find the seeded block's title span and enter edit mode.
  // 60-min block is NOT compact, so the title lives in ``.block-body .title``.
  const titleSpan = page
    .locator(".title")
    .filter({ hasText: SEED_TITLE })
    .first()
  await titleSpan.waitFor({ timeout: 5000 })

  console.log(`→ Clicking title to enter edit mode…`)
  await titleSpan.click()

  const titleInput = page.locator(".title-input").first()
  await titleInput.waitFor({ timeout: 2000 })

  // Clear cleanly: select all + type, then Enter.
  console.log(`→ Renaming and pressing Enter…`)
  await titleInput.fill("Renamed by playwright")
  await titleInput.press("Enter")

  // Wait long enough for both PATCHes to fire if the bug is present.
  // The double-fire happens within milliseconds of the first; 1500ms is
  // generous headroom for the slowest dev machine.
  await page.waitForTimeout(1500)

  console.log(`\n=== Network capture ===`)
  console.log(`PATCH /api/blocks/<id>/ calls: ${patchCalls.length}`)
  patchCalls.forEach((c, i) => {
    console.log(`  [${i + 1}] ${c.url}`)
    console.log(`      body: ${c.body}`)
  })

  console.log(`\n=== Verdict ===`)
  if (patchCalls.length === 1) {
    console.log("✅ PASS — exactly 1 PATCH (single-flight guard working)")
    process.exitCode = 0
  } else {
    console.log(
      `❌ FAIL — expected 1 PATCH, got ${patchCalls.length} (race condition present)`,
    )
    process.exitCode = 1
  }
} catch (err) {
  console.error("\nScript error:")
  console.error(err)
  process.exitCode = 2
} finally {
  await browser.close()
}
