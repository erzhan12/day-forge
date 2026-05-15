// Feature 0009 follow-up — Playwright coverage for /command/ rollback path.
//
// 💸 COST WARNING — one real LLM call per run. The LLM is asked to add a
// block that overlaps a seeded existing block; the server must reject
// the action with 400 and roll back the partially-applied transaction.
//
// This is the CRITICAL async-boundary regression test for the feature
// 0009 async port. The _Rollback exception must propagate from
// _apply_actions_sync (running inside sync_to_async on Django's
// thread-pool executor) back into the async view body. A future
// refactor that returns the error instead of raising — or that
// swallows the exception at the sync_to_async boundary — would
// silently break rollback semantics. This script catches that.
//
// Scenario:
//   1. Seed schedule on 2027-02-18 with ONE existing 14:00–15:00 block.
//   2. UI login → navigate to date.
//   3. Direct-POST /command/ with a very directive prompt that
//      requests a block in the conflicting window.
//   4. Wire-level: 400, body {errors: {action_index, detail}},
//      detail contains "overlap".
//   5. DB: only the seeded block survives (rollback worked);
//      latest AIInteraction has success=False; schedule.status
//      remains "draft" (status flip is gated on successful apply).
//
// Run from frontend/:
//   node scripts/playwright/ai-command-rollback-on-overlap.mjs
//
// ⚠️  WARNING — LOCAL DEVELOPMENT ONLY.

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

const SCHEDULE_DATE = "2027-02-18"
const SCHEDULE_DATE_PARTS = [2027, 2, 18]
// Very directive prompt — leaves the LLM almost no room to reinterpret
// the time. The existing block is 14:00–15:00, so any add in 14:00–15:00
// must overlap.
const PROMPT = "Add a 30-minute work block titled 'Review' from 14:30 to 15:00."

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

console.log("→ Seeding draft schedule with ONE existing 14:00–15:00 block…")
try {
  execSync(
    `uv run python backend/manage.py shell -c "
from schedules.models import Schedule, TimeBlock
from django.contrib.auth.models import User
import datetime
u = User.objects.get(username='${USERNAME}')
s, _ = Schedule.objects.update_or_create(
    user=u, date=datetime.date(${SCHEDULE_DATE_PARTS.join(', ')}), defaults={'status': 'draft'}
)
TimeBlock.objects.filter(schedule=s).delete()
TimeBlock.objects.create(
    schedule=s,
    title='Existing meeting',
    start_time=datetime.time(14, 0),
    end_time=datetime.time(15, 0),
    category='work',
)
print('seeded one-block schedule', s.id)
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

const commandCalls = []
page.on("response", async (resp) => {
  const url = resp.url()
  if (/\/api\/ai\/schedules\/[^/]+\/command\/$/.test(url)) {
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
    commandCalls.push({
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

  console.log("→ Direct-POST /command/ with overlapping prompt…")
  const postResult = await page.evaluate(
    async ({ url, prompt }) => {
      const match = document.cookie.match(/XSRF-TOKEN=([^;]+)/)
      const csrf = match ? decodeURIComponent(match[1]) : ""
      if (!csrf) return { error: "no XSRF-TOKEN cookie present" }
      const r = await fetch(url, {
        method: "POST",
        credentials: "include",
        headers: {
          "content-type": "application/json",
          "x-xsrf-token": csrf,
        },
        body: JSON.stringify({ command: prompt }),
      })
      return { status: r.status, body: await r.text() }
    },
    {
      url: `${BASE}/api/ai/schedules/${SCHEDULE_DATE}/command/`,
      prompt: PROMPT,
    },
  )
  await page.waitForTimeout(400)

  console.log("→ Wire-level assertions…")
  if (postResult.error) {
    fail(`fetch precondition error: ${postResult.error}`)
  }
  if (postResult.body && postResult.body.includes("SynchronousOnlyOperation")) {
    fail(
      "ASYNC REGRESSION: response body contains 'SynchronousOnlyOperation' — " +
        "missed await request.auser() or sync ORM call in async path",
    )
  }
  if (commandCalls.length !== 1) {
    fail(`expected exactly 1 /command/ call, got ${commandCalls.length}`)
  }
  const call = commandCalls[0]
  let parsedResp = null
  if (!call) {
    // soft-fail short-circuit; see iter-3 review notes
  } else if (call.status === 200) {
    // The LLM did not produce an overlapping action. This means the
    // rollback path was not exercised. Surface this as a clear failure
    // with actionable diagnostics — not a silent pass.
    fail(
      `expected 400 with overlap rejection, got 200. LLM did not produce ` +
        `the overlapping action this test requires to exercise the ` +
        `_Rollback path. Inspect the response and tighten the prompt.`,
    )
  } else if (call.status !== 400) {
    fail(`expected 400, got ${call.status}; body=${call.responseBody.slice(0, 400)}`)
  } else {
    try {
      parsedResp = JSON.parse(call.responseBody)
    } catch {
      fail("400 response body is not JSON")
    }
    if (parsedResp) {
      if (!parsedResp.errors || typeof parsedResp.errors !== "object") {
        fail(`response.errors expected object, got ${JSON.stringify(parsedResp.errors)}`)
      } else {
        if (!Number.isInteger(parsedResp.errors.action_index)) {
          fail(`response.errors.action_index expected int, got ${JSON.stringify(parsedResp.errors.action_index)}`)
        }
        const detail = parsedResp.errors.detail
        if (typeof detail !== "string") {
          fail(`response.errors.detail expected string, got ${typeof detail}`)
        } else if (!detail.includes("overlap")) {
          fail(`response.errors.detail expected to contain "overlap", got ${JSON.stringify(detail)}`)
        }
      }
    }
  }

  console.log("→ DB assertions (rollback verification)…")
  const dbStateOut = execSync(
    `uv run python backend/manage.py shell -c "
from schedules.models import Schedule, TimeBlock
from ai.models import AIInteraction
s = Schedule.objects.get(date='${SCHEDULE_DATE}', user__username='${USERNAME}')
print('STATUS', s.status)
print('BLOCKS', TimeBlock.objects.filter(schedule=s).count())
for b in TimeBlock.objects.filter(schedule=s).order_by('start_time'):
    print('BLOCK', b.title, b.start_time, b.end_time)
r = AIInteraction.objects.filter(schedule=s).order_by('-created_at').first()
if r is None:
    print('NO_AI_ROW')
else:
    print('KIND', r.kind)
    print('SUCCESS', r.success)
    print('ACTIONS_LEN', len(r.actions_json))
"`,
    { cwd: REPO_ROOT, encoding: "utf8" },
  )

  const dbLines = dbStateOut.trim().split("\n").filter((l) => l.trim() !== "")
  const dbMap = {}
  const blockRows = []
  for (const line of dbLines) {
    const idx = line.indexOf(" ")
    const key = idx === -1 ? line : line.slice(0, idx)
    const rest = idx === -1 ? "" : line.slice(idx + 1)
    if (key === "BLOCK") {
      blockRows.push(rest)
    } else {
      dbMap[key] = rest
    }
  }

  // Critical: only the seeded block must remain. Any other count means
  // either the rollback failed (would-be 2) or the seed got wiped (0).
  const blockCount = Number(dbMap.BLOCKS || "-1")
  if (blockCount !== 1) {
    fail(
      `ROLLBACK REGRESSION: expected exactly 1 TimeBlock (the seeded one) ` +
        `after a rejected apply, got ${blockCount}. If >1, _Rollback did ` +
        `NOT propagate across the sync_to_async boundary. If 0, the seed ` +
        `was lost — also a regression.`,
    )
  }
  if (dbMap.STATUS !== "draft") {
    fail(
      `schedule.status expected "draft" after a rejected apply (status ` +
        `flip is gated on success), got ${JSON.stringify(dbMap.STATUS)}`,
    )
  }
  if ("NO_AI_ROW" in dbMap) {
    fail("no AIInteraction row created — _log_interaction did not run before apply")
  } else {
    if (dbMap.SUCCESS !== "False") {
      fail(`AIInteraction.success expected False on rejected apply, got ${JSON.stringify(dbMap.SUCCESS)}`)
    }
    if (dbMap.KIND !== "command") {
      fail(`AIInteraction.kind expected "command", got ${JSON.stringify(dbMap.KIND)}`)
    }
  }

  console.log("\n=== Captured /command/ call ===")
  if (call) {
    console.log(`  status=${call.status}`)
    console.log(`  Request body: ${call.requestBody.slice(0, 300)}`)
    console.log(`  Response body: ${call.responseBody.slice(0, 400)}`)
  }
  console.log("\n=== page.evaluate(fetch) result ===")
  console.log(`  status=${postResult.status} body=${(postResult.body || "").slice(0, 300)}`)
  console.log("\n=== DB after ===")
  console.log(dbStateOut.trim())

  console.log("\n=== Verdict ===")
  if (failures.length === 0) {
    console.log("✅ PASS — /command/ rollback: _Rollback propagated across sync_to_async, DB intact, status not flipped")
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
