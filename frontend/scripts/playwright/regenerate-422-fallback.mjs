// Phase 5 Test 12 — UI-side reproduction of the 422 fallback when a
// template is deleted between page load and Regenerate click.
//
// Backend-side already verified via curl (counter=None, 422 envelope
// correct). This script covers the UI contracts:
//   1. Regenerate pill is enabled on a fresh draft schedule when
//      ``has_template_for_type=true``.
//   2. Clicking Regenerate after the template has been DELETE'd
//      (without page reload — the prop is stale) surfaces an inline
//      error "No template configured. Open Settings to create one."
//   3. Manual editing (+ Add Block) still works after the 422 — the
//      missing template only blocks AI-draft, not other actions.
//   4. After re-creating the template via the API, navigating to a
//      fresh date renders the button as enabled again.
//
// Run from frontend/:
//   node scripts/playwright/regenerate-422-fallback.mjs
//
// ⚠️  WARNING — LOCAL DEV ONLY (see the user-creation snippet in
// timeblock-double-save.mjs / template-editor-layout.mjs).

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

// Two future dates: the first is for the stale-prop scenario, the
// second is for the recovery check (so the recovery path doesn't run
// against the same Schedule that just experienced a 422).
const STALE_DATE = "2026-09-21"   // Monday
const RECOVERY_DATE = "2026-09-28" // Monday

const REPO_ROOT = resolve(process.cwd(), "..")

function shell(cmd) {
  return execSync(`uv run python backend/manage.py shell -c "${cmd}"`, {
    encoding: "utf8",
    cwd: REPO_ROOT,
  })
}

console.log("→ Setup: ensure playwright user has 'A weekday' template + empty draft schedules…")
shell(`
from django.contrib.auth.models import User
from templates_mgr.models import Template
from schedules.models import Schedule, TimeBlock
import datetime
u = User.objects.get(username='${USERNAME}')
Template.objects.filter(user=u).delete()
Template.objects.create(
    user=u, type='weekday', name='A weekday',
    blocks=[{'title': 'Deep work', 'start_time': '09:00', 'end_time': '12:00', 'category': 'work'}],
)
for d in (datetime.date(2026, 9, 21), datetime.date(2026, 9, 28)):
    s, _ = Schedule.objects.update_or_create(user=u, date=d, defaults={'status': 'draft'})
    TimeBlock.objects.filter(schedule=s).delete()
print('seeded')
`)

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({
  viewport: { width: 1280, height: 800 },
})
const page = await context.newPage()

const aiCalls = []
page.on("response", async (resp) => {
  if (/\/api\/ai\/schedules\/[^/]+\/generate-draft\/$/.test(resp.url())) {
    let body = ""
    try { body = await resp.text() } catch {}
    aiCalls.push({ url: resp.url(), status: resp.status(), body })
  }
})

const failures = []
function check(label, ok, detail = "") {
  console.log(`  ${ok ? "✅" : "❌"} ${label}${detail ? " — " + detail : ""}`)
  if (!ok) failures.push(label)
}

try {
  // Login
  console.log("→ Logging in…")
  await page.goto(`${BASE}/accounts/login/`, { waitUntil: "networkidle" })
  await page.fill("#username", USERNAME)
  await page.fill("#password", PASSWORD)
  await Promise.all([
    page.waitForURL(/\/schedule\//),
    page.click('button[type="submit"]'),
  ])

  // ────────────────────────────────────────────────────────────────
  // Contract 1: Regenerate pill enabled on a fresh draft schedule
  // ────────────────────────────────────────────────────────────────
  console.log(`\n→ [1/4] Open /schedule/${STALE_DATE}/ — expect Regenerate pill enabled`)
  await page.goto(`${BASE}/schedule/${STALE_DATE}/`, { waitUntil: "networkidle" })

  const regenBtn = page.locator(".regenerate-btn, button:has-text('Regenerate'), [class*='regenerate']").first()
  const regenVisible = await regenBtn.count() > 0 && await regenBtn.isVisible().catch(() => false)
  const regenDisabled = regenVisible ? await regenBtn.isDisabled() : true
  check("Regenerate pill is visible", regenVisible)
  check("Regenerate pill is enabled", regenVisible && !regenDisabled)

  // ────────────────────────────────────────────────────────────────
  // Simulate: template gets DELETE'd in another tab (we do it via
  // direct backend mutation; the page on screen still has the stale
  // ``has_template_for_type=true`` prop in memory).
  // ────────────────────────────────────────────────────────────────
  console.log(`\n→ Simulating template deletion (without reloading the schedule page)…`)
  shell(`
from django.contrib.auth.models import User
from templates_mgr.models import Template
u = User.objects.get(username='${USERNAME}')
Template.objects.filter(user=u, type='weekday').delete()
print('deleted')
`)

  // ────────────────────────────────────────────────────────────────
  // Contract 2: clicking Regenerate now → 422 + friendly inline error
  // ────────────────────────────────────────────────────────────────
  console.log(`\n→ [2/4] Click Regenerate on stale page — expect 422 + inline error`)
  aiCalls.length = 0  // reset capture
  await regenBtn.click()
  // Wait for the POST to land + Vue to render the error
  for (let i = 0; i < 20 && aiCalls.length === 0; i++) {
    await page.waitForTimeout(250)
  }
  await page.waitForTimeout(500)

  const lastCall = aiCalls[aiCalls.length - 1]
  check(
    "POST /generate-draft/ returned 422",
    lastCall && lastCall.status === 422,
    lastCall ? `got ${lastCall.status}` : "no call captured",
  )

  // The friendly inline error lives in ``.draft-error`` per Schedule.vue
  const errorEl = page.locator(".draft-error")
  const errorVisible = await errorEl.count() > 0
  const errorText = errorVisible ? await errorEl.innerText() : ""
  check(
    "Inline error visible",
    errorVisible,
  )
  check(
    "Error text is the friendly mapped message (not raw backend text)",
    errorText.includes("No template configured") &&
      errorText.includes("Open Settings"),
    `got: ${errorText.slice(0, 100)}`,
  )

  // ────────────────────────────────────────────────────────────────
  // Contract 3: manual editing still works (+ Add Block opens form)
  // ────────────────────────────────────────────────────────────────
  console.log(`\n→ [3/4] Manual editing still works (+ Add Block usable)`)
  // AddBlockForm.vue renders a collapsed ``.add-btn`` trigger by
  // default; clicking it expands the actual form. The contract here
  // is "the trigger is enabled despite the missing template" — the
  // 422 only blocks AI flows, not manual editing.
  const addBlockTrigger = page.locator(".add-btn").first()
  const triggerExists = await addBlockTrigger.count() > 0
  check("+ Add block trigger button mounted", triggerExists)
  if (triggerExists) {
    check(
      "+ Add block trigger NOT disabled",
      !(await addBlockTrigger.isDisabled()),
    )
    // And clicking it should expand the form (proves manual flow works)
    await addBlockTrigger.click()
    await page.waitForTimeout(200)
    const titleInput = page.locator(".add-form .title-input").first()
    check(
      "Clicking + Add block expands the form (title input visible)",
      await titleInput.count() > 0 && (await titleInput.isVisible()),
    )
  }

  // ────────────────────────────────────────────────────────────────
  // Contract 4: re-create template + visit fresh date → button enabled
  // ────────────────────────────────────────────────────────────────
  console.log(`\n→ [4/4] Re-create template, visit a fresh date — expect Regenerate enabled`)
  shell(`
from django.contrib.auth.models import User
from templates_mgr.models import Template
u = User.objects.get(username='${USERNAME}')
Template.objects.create(
    user=u, type='weekday', name='A weekday',
    blocks=[{'title': 'Deep work', 'start_time': '09:00', 'end_time': '12:00', 'category': 'work'}],
)
print('re-created')
`)

  await page.goto(`${BASE}/schedule/${RECOVERY_DATE}/`, { waitUntil: "networkidle" })
  // Wait for any auto-draft kicker to settle. This date might trigger
  // auto_draft_pending=true (created Schedule row → first visit). We
  // don't want to get caught in that — clear blocks if so.
  await page.waitForTimeout(2000)
  // Force back to empty-draft state for a clean Regenerate-button check
  shell(`
from django.contrib.auth.models import User
from schedules.models import Schedule, TimeBlock
import datetime
u = User.objects.get(username='${USERNAME}')
s = Schedule.objects.get(user=u, date=datetime.date(2026, 9, 28))
TimeBlock.objects.filter(schedule=s).delete()
s.status = 'draft'
s.save(update_fields=['status'])
`)
  await page.goto(`${BASE}/schedule/${RECOVERY_DATE}/`, { waitUntil: "networkidle" })

  const regenBtn2 = page.locator(".regenerate-btn, button:has-text('Regenerate'), [class*='regenerate']").first()
  const regenVisible2 = await regenBtn2.count() > 0
  const regenDisabled2 = regenVisible2 ? await regenBtn2.isDisabled() : true
  check("After recovery: Regenerate pill is visible", regenVisible2)
  check("After recovery: Regenerate pill is enabled", regenVisible2 && !regenDisabled2)

  console.log(`\n=== Verdict ===`)
  if (failures.length === 0) {
    console.log("✅ PASS — all 4 contracts hold")
    process.exitCode = 0
  } else {
    console.log(`❌ FAIL — ${failures.length} failures:`)
    for (const f of failures) console.log(`    • ${f}`)
    process.exitCode = 1
  }
} catch (err) {
  console.error("\nScript error:")
  console.error(err)
  process.exitCode = 2
} finally {
  await browser.close()
}
