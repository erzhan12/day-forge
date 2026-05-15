// Feature 0009 follow-up — Playwright coverage for /generate-draft/ happy path.
//
// 💸 COST WARNING — one real LLM call per run (uses LLM_DRAFT_MODEL,
// typically 5–10× the cost of LLM_MODEL). Don't loop in CI.
//
// /generate-draft/ has a UI driver (RegenerateDraftButton, .regen-btn),
// visible only when schedule.status='draft' AND blocks.length===0 AND
// the user has a matching template. This script seeds all three and
// clicks the real button.
//
// Scenario:
//   1. Seed empty draft schedule on 2027-03-22 (weekday).
//   2. Seed/refresh a weekday Template for the playwright user with a
//      minimal blocks list (the LLM uses it as context).
//   3. UI login → navigate to date.
//   4. Wait for .regen-btn enabled, click it.
//   5. Wait for /generate-draft/ response.
//   6. Wire-level: 200, body {blocks: [...], explanation: string},
//      blocks.length >= 1.
//   7. DB: ≥1 TimeBlock; latest AIInteraction has kind=draft,
//      success=True, user_command='[DRAFT]'; schedule.status
//      STAYS 'draft' (drafts NEVER promote to active).
//
// Run from frontend/:
//   node scripts/playwright/ai-draft-on-empty-day.mjs
//
// Concurrency: run this script SERIALLY with the other ai-*.mjs scripts.
// They share the `playwright` user and the `ai_cmd_rl` / `ai_draft_rl`
// rate-limit counters, so parallel execution will race on the counters
// and may produce false failures in the 409 script's "no consumption"
// assertion. Different seed dates prevent DB conflicts; the shared
// counters do not.
//
// ⚠️  WARNING — LOCAL DEVELOPMENT ONLY.

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

const SCHEDULE_DATE = "2027-03-22" // Monday → weekday slot
const SCHEDULE_DATE_PARTS = [2027, 3, 22]

const REPO_ROOT = resolve(process.cwd(), "..")

console.log("→ Pre-flight: confirming playwright user exists…")
try {
  const preflight = execSync(
    `uv run python backend/manage.py shell -c "
from django.contrib.auth.models import User
print('EXISTS', User.objects.filter(username='${USERNAME}').exists())
"`,
    { cwd: REPO_ROOT, encoding: "utf8" },
  )
  if (!preflight.includes("EXISTS True")) {
    console.error("\n❌ playwright user is missing. Run:")
    console.error("   uv run python backend/manage.py createsuperuser")
    console.error(`   (use username '${USERNAME}' / password '${PASSWORD}')`)
    process.exit(2)
  }
} catch (err) {
  console.error("\n❌ Pre-flight shell failed:", err.message)
  process.exit(2)
}

console.log("→ Seeding empty draft schedule + weekday Template…")
try {
  execSync(
    `uv run python backend/manage.py shell -c "
from schedules.models import Schedule, TimeBlock
from templates_mgr.models import Template
from django.contrib.auth.models import User
import datetime
u = User.objects.get(username='${USERNAME}')
s, _ = Schedule.objects.update_or_create(
    user=u, date=datetime.date(${SCHEDULE_DATE_PARTS.join(', ')}), defaults={'status': 'draft'}
)
TimeBlock.objects.filter(schedule=s).delete()
Template.objects.update_or_create(
    user=u, type='weekday',
    defaults={'name': 'Playwright Weekday', 'blocks': [
        {'title': 'Morning routine', 'start_time': '07:00', 'end_time': '07:30', 'category': 'health'},
        {'title': 'Deep work', 'start_time': '09:00', 'end_time': '12:00', 'category': 'work'},
        {'title': 'Lunch', 'start_time': '12:00', 'end_time': '13:00', 'category': 'personal'},
        {'title': 'Afternoon work', 'start_time': '13:00', 'end_time': '17:00', 'category': 'work'},
    ]},
)
print('seeded empty schedule', s.id, 'with weekday template')
"`,
    { stdio: "inherit", cwd: REPO_ROOT },
  )
} catch (err) {
  console.error("\n❌ Seed failed. Is Django running?")
  console.error(err.message)
  process.exit(2)
}

const browser = await chromium.launch({ headless: true })
const context = await browser.newContext({
  viewport: { width: 1280, height: 800 },
})
const page = await context.newPage()

const draftCalls = []
page.on("response", async (resp) => {
  const url = resp.url()
  if (/\/api\/ai\/schedules\/[^/]+\/generate-draft\/$/.test(url)) {
    let bodyText = ""
    try {
      bodyText = await resp.text()
    } catch {
      bodyText = "(could not read body)"
    }
    let requestBody = ""
    try {
      requestBody = resp.request().postData() || ""
    } catch {
      requestBody = "(could not read request body)"
    }
    draftCalls.push({
      url,
      status: resp.status(),
      requestBody,
      responseBody: bodyText,
    })
  }
})

const failures = []
function fail(msg) {
  failures.push(msg)
}

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

  console.log("→ Waiting for .regen-btn to be visible and enabled…")
  const regenBtn = page.locator(".regen-btn")
  await regenBtn.waitFor({ state: "visible", timeout: 5000 })
  const initiallyDisabled = await regenBtn.isDisabled()
  if (initiallyDisabled) {
    fail("regen-btn was disabled — template not configured or API unhealthy?")
  }

  console.log("→ Clicking .regen-btn and awaiting /generate-draft/ response…")
  await Promise.all([
    page.waitForResponse(
      (resp) => /\/api\/ai\/schedules\/[^/]+\/generate-draft\/$/.test(resp.url()),
      { timeout: 60_000 }, // draft model is heavier; allow more time
    ),
    regenBtn.click(),
  ])
  // Give Inertia partial reload time to settle and the overlay to dismiss.
  await page.waitForTimeout(1200)

  console.log("→ Wire-level assertions…")
  if (draftCalls.length !== 1) {
    fail(`expected exactly 1 /generate-draft/ call, got ${draftCalls.length}`)
  }
  const call = draftCalls[0]
  if (!call) {
    // Skip the rest of the wire-level block if no call was captured;
    // the count assertion above already recorded the failure, and
    // dereferencing `call.*` would crash the aggregator before the
    // verdict line runs.
  } else {
    if (call.responseBody && call.responseBody.includes("SynchronousOnlyOperation")) {
      fail(
        "ASYNC REGRESSION: response body contains 'SynchronousOnlyOperation' — " +
          "missed await request.auser() or sync ORM call in async path",
      )
    }
    if (call.status !== 200) {
      fail(`response expected 200, got ${call.status}; body=${call.responseBody.slice(0, 400)}`)
    } else {
      let parsedResp = null
      try {
        parsedResp = JSON.parse(call.responseBody)
      } catch {
        fail("response body is not JSON")
      }
      if (parsedResp) {
        if (!Array.isArray(parsedResp.blocks) || parsedResp.blocks.length < 1) {
          fail(`response.blocks expected array with ≥1 entry, got ${JSON.stringify(parsedResp.blocks).slice(0, 200)}`)
        }
        if (typeof parsedResp.explanation !== "string") {
          fail(`response.explanation expected string, got ${typeof parsedResp.explanation}`)
        }
      }
    }
  }

  console.log("→ DB assertions…")
  const dbStateOut = execSync(
    `uv run python backend/manage.py shell -c "
from schedules.models import Schedule, TimeBlock
from ai.models import AIInteraction
s = Schedule.objects.get(date='${SCHEDULE_DATE}', user__username='${USERNAME}')
print('STATUS', s.status)
print('BLOCKS', TimeBlock.objects.filter(schedule=s).count())
r = AIInteraction.objects.filter(schedule=s).order_by('-created_at').first()
if r is None:
    print('NO_AI_ROW')
else:
    print('KIND', r.kind)
    print('SUCCESS', r.success)
    print('USER_COMMAND', r.user_command)
    print('ACTIONS_LEN', len(r.actions_json))
"`,
    { cwd: REPO_ROOT, encoding: "utf8" },
  )

  const dbLines = dbStateOut.trim().split("\n").filter((l) => l.trim() !== "")
  const dbMap = {}
  for (const line of dbLines) {
    const idx = line.indexOf(" ")
    if (idx === -1) {
      dbMap[line] = ""
    } else {
      dbMap[line.slice(0, idx)] = line.slice(idx + 1)
    }
  }

  if (dbMap.STATUS !== "draft") {
    fail(
      `NON-PROMOTION REGRESSION: schedule.status expected to stay "draft" ` +
        `after a successful draft generation (drafts NEVER promote to ` +
        `active — only /command/ does, gated on non-empty actions), got ` +
        `${JSON.stringify(dbMap.STATUS)}.`,
    )
  }
  const blockCount = Number(dbMap.BLOCKS || "0")
  if (blockCount < 1) {
    fail(`expected ≥1 TimeBlock after draft, got ${blockCount}`)
  }
  if ("NO_AI_ROW" in dbMap) {
    fail("no AIInteraction row created for this schedule")
  } else {
    if (dbMap.KIND !== "draft") {
      fail(`AIInteraction.kind expected "draft", got ${JSON.stringify(dbMap.KIND)}`)
    }
    if (dbMap.SUCCESS !== "True") {
      fail(`AIInteraction.success expected True, got ${JSON.stringify(dbMap.SUCCESS)}`)
    }
    if (dbMap.USER_COMMAND !== "[DRAFT]") {
      fail(`AIInteraction.user_command expected "[DRAFT]", got ${JSON.stringify(dbMap.USER_COMMAND)}`)
    }
    if (Number(dbMap.ACTIONS_LEN || "0") < 1) {
      fail(`AIInteraction.actions_json expected ≥1 entry, got ${dbMap.ACTIONS_LEN}`)
    }
  }

  // TODO: N+1 sanity for analytics_dailyreview — requires capturing
  // Django SQL log mid-request. Skipped here to keep the script
  // dependency-free; would need either DEBUG=True + SQL log capture
  // or a separate connection-instrumented harness. The select_related
  // is verified by unit tests instead.

  console.log("\n=== Captured /generate-draft/ call ===")
  if (call) {
    console.log(`  status=${call.status}`)
    console.log(`  Response body: ${call.responseBody.slice(0, 500)}`)
  }
  console.log("\n=== DB after ===")
  console.log(dbStateOut.trim())

  console.log("\n=== Verdict ===")
  if (failures.length === 0) {
    console.log("✅ PASS — /generate-draft/ happy path: blocks generated, status stays draft, audit row correct")
    process.exitCode = 0
  } else {
    console.log("❌ FAIL —")
    for (const r of failures) console.log(`    • ${r}`)
    process.exitCode = 1
  }
} catch (err) {
  console.error("\nScript error:")
  console.error(err)
  process.exitCode = 2
} finally {
  await browser.close()
}
