// Manual Test 4 (0006): editing a reviewed schedule unfreezes it
// (mark_active_on_edit). Covers: analytics → schedule link, completion
// toggle + PATCH, return to analytics (Active + Mark reviewed), then
// Add Block, drag reorder, delete, and AI command bar — each after
// re-freezing via Mark reviewed.
//
// 💸 The AI step issues one real LLM request (same as ai-command-noop.mjs);
//    LLM_MODEL (gpt-4o-mini by default) ≈ $0.001-$0.003 per run as of 2026-05.
//
// Run from frontend/:
//   node scripts/playwright/analytics-unfreeze-on-edit.mjs
//
// Pre-reqs: Django :8006, Vite :5173, user ``playwright`` (see other
// scripts for the shell one-liner), LLM_API_KEY for the final step.

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"
/** Past date (analytics is past-only vs local today). */
const DATE = "2026-05-05"

const REPO_ROOT = resolve(process.cwd(), "..")

console.log("→ Seeding reviewed schedule + 3 blocks via Django shell…")
try {
  execSync(
    `uv run python backend/manage.py shell -c "
from schedules.models import Schedule, TimeBlock
from analytics.services import recompute_review_from_schedule
from django.contrib.auth.models import User
import datetime
u = User.objects.get(username='${USERNAME}')
d = datetime.date(2026, 5, 5)
s, _ = Schedule.objects.update_or_create(
    user=u, date=d, defaults={'status': 'active'}
)
TimeBlock.objects.filter(schedule=s).delete()
TimeBlock.objects.create(
    schedule=s, title='Alpha', start_time='09:00', end_time='10:00',
    category='work', is_completed=False,
)
TimeBlock.objects.create(
    schedule=s, title='Beta', start_time='10:00', end_time='11:00',
    category='work', is_completed=True,
)
TimeBlock.objects.create(
    schedule=s, title='Gamma', start_time='11:00', end_time='12:00',
    category='work', is_completed=False,
)
recompute_review_from_schedule(s)
s.status = 'reviewed'
s.save(update_fields=['status'])
print('seeded schedule', s.id, 'blocks', s.time_blocks.count())
"`,
    { stdio: "inherit", cwd: REPO_ROOT },
  )
} catch {
  console.error("\n❌ Seed failed (Django running? user playwright exists?)")
  process.exit(2)
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
const page = await context.newPage()

function fail(msg) {
  console.error(`\n❌ ${msg}`)
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

async function assertAnalyticsReviewed() {
  await page.goto(`${BASE}/analytics/${DATE}/`, { waitUntil: "networkidle" })
  const reviewed = page.locator(".status-badge.status-reviewed")
  if ((await reviewed.count()) !== 1) fail("expected Reviewed badge on analytics")
  if ((await page.locator(".mark-reviewed-btn").count()) !== 0) {
    fail("Mark reviewed should be hidden when already reviewed")
  }
}

async function assertScheduleNoAnalyticsBadge() {
  if ((await page.locator(".status-badge").count()) !== 0) {
    fail("schedule view should not show analytics status-badge")
  }
}

async function assertAnalyticsActive() {
  await page.goto(`${BASE}/analytics/${DATE}/`, { waitUntil: "networkidle" })
  const active = page.locator(".status-badge.status-active")
  if ((await active.count()) !== 1) fail("expected Active badge after unfreeze")
  const btn = page.locator(".mark-reviewed-btn")
  if ((await btn.count()) !== 1) fail("expected Mark reviewed when active")
}

async function markReviewedFromPanel() {
  await page.goto(`${BASE}/analytics/${DATE}/`, { waitUntil: "networkidle" })
  const btn = page.locator(".mark-reviewed-btn")
  await btn.waitFor({ state: "visible", timeout: 8000 })
  await Promise.all([
    page.waitForResponse(
      (r) =>
        r.url().includes(`/api/analytics/schedules/${DATE}/mark-reviewed/`) &&
        r.request().method() === "POST" &&
        r.status() === 200,
    ),
    btn.click(),
  ])
  await page.locator(".status-badge.status-reviewed").waitFor({ timeout: 15000 })
}

try {
  console.log("→ Login…")
  await login()

  console.log("→ Step A: analytics shows Reviewed…")
  await assertAnalyticsReviewed()

  console.log("→ Step B: Back to schedule, toggle completion…")
  await Promise.all([
    page.waitForURL(new RegExp(`/schedule/${DATE}/`)),
    page.click("a.back-link"),
  ])
  await assertScheduleNoAnalyticsBadge()

  const patchPromise = page.waitForResponse(
    (r) =>
      r.request().method() === "PATCH" &&
      /\/api\/blocks\/\d+\/$/.test(r.url()) &&
      r.status() === 200,
  )
  const alphaBlock = page.locator(".time-block").filter({ hasText: "Alpha" })
  await alphaBlock.locator('input[type="checkbox"]').first().click()
  const patchResp = await patchPromise
  console.log(`   PATCH ${patchResp.url()} → ${patchResp.status()}`)

  console.log("→ Step C: analytics Active + re-freeze…")
  await assertAnalyticsActive()
  await markReviewedFromPanel()

  console.log("→ Step D: Add Block unfreezes…")
  await page.goto(`${BASE}/schedule/${DATE}/`, { waitUntil: "networkidle" })
  await page.getByRole("button", { name: "+ Add Block" }).click()
  await page.locator(".add-form .title-input").fill("Delta")
  const form = page.locator(".add-form")
  await form.getByLabel("Start").fill("14:00")
  await form.getByLabel("End").fill("15:00")
  await Promise.all([
    page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().includes(`/api/schedules/${DATE}/blocks/`) &&
        r.status() === 201,
    ),
    page.locator(".add-form .submit-btn").click(),
  ])
  await assertAnalyticsActive()
  await markReviewedFromPanel()

  console.log("→ Step E: drag reorder unfreezes…")
  await page.goto(`${BASE}/schedule/${DATE}/`, { waitUntil: "networkidle" })
  const blocks = page.locator(".time-block")
  const n = await blocks.count()
  if (n < 2) fail("need ≥2 blocks for reorder")
  const srcHandle = blocks.nth(0).locator(".drag-handle")
  const dst = blocks.nth(n - 1)
  await Promise.all([
    page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().includes("/api/blocks/reorder/") &&
        r.status() === 200,
    ),
    srcHandle.dragTo(dst, { targetPosition: { x: 40, y: 10 } }),
  ])
  await assertAnalyticsActive()
  await markReviewedFromPanel()

  console.log("→ Step F: delete unfreezes…")
  await page.goto(`${BASE}/schedule/${DATE}/`, { waitUntil: "networkidle" })
  page.once("dialog", (d) => d.accept())
  await Promise.all([
    page.waitForResponse(
      (r) =>
        r.request().method() === "DELETE" &&
        /\/api\/blocks\/\d+\/$/.test(r.url()) &&
        r.status() === 200,
    ),
    page.locator(".time-block").filter({ hasText: "Delta" }).locator(".delete-btn").click(),
  ])
  await assertAnalyticsActive()
  await markReviewedFromPanel()

  console.log("→ Step G: AI command bar (one LLM call)…")
  await page.goto(`${BASE}/schedule/${DATE}/`, { waitUntil: "networkidle" })
  const cmd = page.locator(".command-input")
  await cmd.waitFor({ state: "visible", timeout: 5000 })
  // Backend only calls mark_active_on_edit when parsed_actions is non-empty.
  await cmd.fill("add a block titled LLMProbe at 16:00 for 30 minutes")
  await Promise.all([
    page.waitForResponse(
      (r) =>
        r.request().method() === "POST" &&
        r.url().includes(`/api/ai/schedules/${DATE}/command/`) &&
        r.status() === 200,
      { timeout: 120_000 },
    ),
    cmd.press("Enter"),
  ])
  await assertAnalyticsActive()

  console.log("\n✅ PASS — Test 4 Playwright path complete (toggle, add, reorder, delete, AI).")
  process.exitCode = 0
} catch (err) {
  console.error("\nScript error:")
  console.error(err)
  process.exitCode = 2
} finally {
  await browser.close()
}
