// Manual Test 4 (0006): editing a reviewed schedule unfreezes it
// (mark_active_on_edit). Covers: analytics → schedule link, completion
// toggle + PATCH, return to analytics (Active + Mark reviewed), then
// Add Block, drag reorder, delete — each after re-freezing via Mark
// reviewed.
//
// AI-triggered unfreeze (mark_active_on_edit via apply_actions) used to
// live as "Step G" here against the retired Phase-4 one-shot endpoint. That
// path was removed when the chat rewrite (feature 0007) replaced the
// single-shot CommandBar UI; the AI-edit invariant is now covered by
// ai-chat-single-turn-apply.mjs against the current /chat/ surface.
//
// Run from frontend/:
//   node scripts/playwright/analytics-unfreeze-on-edit.mjs
//
// Pre-reqs: Django :8006, Vite :5173, user ``playwright`` (see other
// scripts for the shell one-liner). No LLM_API_KEY required — this
// script is LLM-free after the Step-G removal.

import { chromium } from "@playwright/test"
import {
  BASE,
  ANALYTICS_BUTTON_TIMEOUT_MS,
  PANEL_TIMEOUT_MS,
  USERNAME,
  cleanupSchedules,
  failFast,
  login,
  preflight,
  seed,
} from "./test-utils.mjs"
/** Past date (analytics is past-only vs local today). */
const DATE = "2026-05-05"

await preflight()

const fail = failFast

let browser
try {
  console.log("→ Seeding reviewed schedule + 3 blocks via Django shell…")
  seed("seed_analytics_reviewed", {
    SEED_USERNAME: USERNAME,
    SEED_DATE: DATE,
    SEED_BLOCKS_JSON: JSON.stringify([
      { title: "Alpha", start_time: "09:00", end_time: "10:00", category: "work", is_completed: false },
      { title: "Beta", start_time: "10:00", end_time: "11:00", category: "work", is_completed: true },
      { title: "Gamma", start_time: "11:00", end_time: "12:00", category: "work", is_completed: false },
    ]),
  })

  browser = await chromium.launch({ headless: true })
  const context = await browser.newContext({ viewport: { width: 1280, height: 900 } })
  const page = await context.newPage()

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
    await btn.waitFor({ state: "visible", timeout: ANALYTICS_BUTTON_TIMEOUT_MS })
    await Promise.all([
      page.waitForResponse(
        (r) =>
          r.url().includes(`/api/analytics/schedules/${DATE}/mark-reviewed/`) &&
          r.request().method() === "POST" &&
          r.status() === 200,
      ),
      btn.click(),
    ])
    await page.locator(".status-badge.status-reviewed").waitFor({ timeout: PANEL_TIMEOUT_MS })
  }

  console.log("→ Login…")
  await login(page)

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

  // Step G (Phase-4 AI command bar one-shot) was removed:
  // after feature 0007 the CommandBar surface submits to /api/ai/.../chat/
  // (multi-turn), so the original probe
  // here would hang waiting for a response that never matches. The
  // mark_active_on_edit invariant for AI-triggered edits is covered
  // separately by ai-chat-single-turn-apply.mjs, which exercises the
  // current chat surface end-to-end against a real LLM.

  console.log("\n✅ PASS — Test 4 Playwright path complete (toggle, add, reorder, delete).")
  process.exitCode = 0
} catch (err) {
  console.error("\nScript error:")
  console.error(err)
  process.exitCode = 2
} finally {
  await browser?.close()
  cleanupSchedules([DATE])
}
