// Mass-edit smoke test — verifies the AI command bar can shift N blocks
// in a single command (e.g. "move all blocks at/after 1pm one hour later").
//
// Motivation: the per-action overlap check in
// backend/ai/views.py:_apply_move_or_resize runs sequentially against
// the in-memory blocks_by_id. For a forward shift, moves must arrive in
// REVERSE chronological order or the first move collides with the
// next-block's current slot. SYSTEM_PROMPT does not hint at this, so
// success depends on the LLM figuring out the ordering on its own.
//
// 💸 COST WARNING — one real LLM call per run. Same constraints as
// ai-command-add-block.mjs: run SERIALLY with other ai-*.mjs scripts
// (shared playwright user + ai_cmd_rl rate-limit counter).
//
// Scenario:
//   1. Seed an ACTIVE schedule on 2027-01-22 with 5 blocks:
//      - 08:00-09:00 morning             (control, must NOT move)
//      - 12:30-13:00 pre-noon            (control, must NOT move)
//      - 13:15-14:00 post-13 target #1   (expect 14:15-15:00)
//      - 14:15-15:00 post-13 target #2   (expect 15:15-16:00) -- gap
//      - 15:30-16:30 post-13 target #3   (expect 16:30-17:30)
//      Target durations are mismatched on purpose so a literal "+1h to
//      start_time" works whether the LLM sends start-only or start+end.
//   2. UI login → navigate to the seeded date.
//   3. Direct-POST /command/ with the mass-move prompt.
//   4. Wire-level assertions: status 200, {blocks, explanation} shape.
//   5. DB assertions:
//      - controls unchanged
//      - each target block shifted +60 min on start_time (duration
//        preservation, end_time also +60)
//      - AIInteraction.actions_json has ≥3 move actions
//      - schedule.status still "active"
//
// Run from frontend/:
//   node scripts/playwright/ai-command-mass-move.mjs
//
// Pre-reqs:
//   * Django :8006, Vite :5173
//   * Test user `playwright`
//   * `LLM_API_KEY` set
//
// ⚠️  WARNING — LOCAL DEVELOPMENT ONLY. The seed step truncates the
// target schedule's blocks.

import { chromium } from "@playwright/test"
import { execSync } from "node:child_process"
import { resolve } from "node:path"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

const SCHEDULE_DATE = "2027-01-22"
const SCHEDULE_DATE_PARTS = [2027, 1, 22]
const PROMPT = "move all blocks starting at or after 1pm one hour later"

// Each seed is [title, start HH:MM, end HH:MM, category, should_move].
// "expected_after" is computed by shifting +60 min when should_move.
const SEED_BLOCKS = [
  ["morning run",    "08:00", "09:00", "health",   false],
  ["pre-noon admin", "12:30", "13:00", "work",     false],
  ["deep work A",    "13:15", "14:00", "work",     true],
  ["deep work B",    "14:15", "15:00", "work",     true],
  ["errands",        "15:30", "16:30", "personal", true],
]

function shiftPlusOneHour(hhmm) {
  const [h, m] = hhmm.split(":").map(Number)
  return `${String(h + 1).padStart(2, "0")}:${String(m).padStart(2, "0")}`
}

const EXPECTED_AFTER = SEED_BLOCKS.map(([title, s, e, cat, move]) => ({
  title,
  category: cat,
  start_time: move ? shiftPlusOneHour(s) : s,
  end_time: move ? shiftPlusOneHour(e) : e,
  moved: move,
}))

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

console.log("→ Seeding schedule + 5 blocks via Django shell…")
try {
  const seedPython = `
from schedules.models import Schedule, TimeBlock
from django.contrib.auth.models import User
import datetime
u = User.objects.get(username='${USERNAME}')
s, _ = Schedule.objects.update_or_create(
    user=u, date=datetime.date(${SCHEDULE_DATE_PARTS.join(', ')}),
    defaults={'status': 'active'},
)
TimeBlock.objects.filter(schedule=s).delete()
seeds = ${JSON.stringify(SEED_BLOCKS.map(([t, s, e, c]) => [t, s, e, c]))}
for title, start, end, cat in seeds:
    sh, sm = map(int, start.split(':'))
    eh, em = map(int, end.split(':'))
    TimeBlock.objects.create(
        schedule=s, title=title,
        start_time=datetime.time(sh, sm),
        end_time=datetime.time(eh, em),
        category=cat,
    )
print('seeded', s.id, 'with', TimeBlock.objects.filter(schedule=s).count(), 'blocks')
`
  execSync(
    `uv run python backend/manage.py shell -c "${seedPython.replace(/"/g, '\\"')}"`,
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

  console.log(`→ Direct-POST /command/ with prompt: ${JSON.stringify(PROMPT)}`)
  const postResult = await page.evaluate(
    async ({ url, prompt }) => {
      const match = document.cookie.match(/XSRF-TOKEN=([^;]+)/)
      const csrf = match ? decodeURIComponent(match[1]) : ""
      if (!csrf) {
        return { error: "no XSRF-TOKEN cookie present" }
      }
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
      "ASYNC REGRESSION: response body contains 'SynchronousOnlyOperation'",
    )
  }
  if (commandCalls.length !== 1) {
    fail(`expected exactly 1 /command/ call, got ${commandCalls.length}`)
  }
  const call = commandCalls[0]
  let parsedResp = null
  if (call) {
    if (call.status !== 200) {
      fail(
        `response expected 200, got ${call.status}; body=${call.responseBody.slice(0, 400)}`,
      )
    } else {
      try {
        parsedResp = JSON.parse(call.responseBody)
      } catch {
        fail("response body is not JSON")
      }
      if (parsedResp) {
        if (!Array.isArray(parsedResp.blocks)) {
          fail(`response.blocks expected array, got ${typeof parsedResp.blocks}`)
        }
        if (typeof parsedResp.explanation !== "string") {
          fail(`response.explanation expected string`)
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
for b in TimeBlock.objects.filter(schedule=s).order_by('start_time'):
    print('BLOCK', b.start_time.strftime('%H:%M'), b.end_time.strftime('%H:%M'), b.category, '|', b.title)
r = AIInteraction.objects.filter(schedule=s).order_by('-created_at').first()
if r is None:
    print('NO_AI_ROW')
else:
    print('KIND', r.kind)
    print('SUCCESS', r.success)
    print('ACTIONS_LEN', len(r.actions_json))
    move_count = sum(1 for a in r.actions_json if a.get('type') == 'move')
    print('MOVE_COUNT', move_count)
    print('USER_COMMAND', r.user_command)
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
      // rest format: "HH:MM HH:MM category | title"
      const [start, end, category, , ...titleParts] = rest.split(" ")
      blockRows.push({
        start_time: start,
        end_time: end,
        category,
        title: titleParts.join(" "),
      })
    } else {
      dbMap[key] = rest
    }
  }

  if (dbMap.STATUS !== "active") {
    fail(`schedule.status expected "active", got ${JSON.stringify(dbMap.STATUS)}`)
  }
  const blockCount = Number(dbMap.BLOCKS || "0")
  if (blockCount !== SEED_BLOCKS.length) {
    fail(`expected ${SEED_BLOCKS.length} blocks after apply, got ${blockCount}`)
  }
  if ("NO_AI_ROW" in dbMap) {
    fail("no AIInteraction row created for this schedule")
  } else {
    if (dbMap.KIND !== "command") fail(`AIInteraction.kind expected "command", got ${dbMap.KIND}`)
    if (dbMap.SUCCESS !== "True") fail(`AIInteraction.success expected True, got ${dbMap.SUCCESS}`)
    const moveCount = Number(dbMap.MOVE_COUNT || "0")
    const expectedMoves = EXPECTED_AFTER.filter((b) => b.moved).length
    if (moveCount < expectedMoves) {
      fail(`AIInteraction.actions_json expected ≥${expectedMoves} move actions, got ${moveCount}`)
    }
  }

  // Per-block expectation match by title.
  console.log("\n=== Per-block check ===")
  for (const want of EXPECTED_AFTER) {
    const got = blockRows.find((b) => b.title === want.title)
    if (!got) {
      console.log(`  ❌ missing: ${want.title}`)
      fail(`block "${want.title}" missing after apply`)
      continue
    }
    const ok =
      got.start_time === want.start_time && got.end_time === want.end_time
    const marker = ok ? "✅" : "❌"
    const tag = want.moved ? "(should move)" : "(should NOT move)"
    console.log(
      `  ${marker} ${want.title.padEnd(18)} ${tag.padEnd(20)}  got=${got.start_time}-${got.end_time}  want=${want.start_time}-${want.end_time}`,
    )
    if (!ok) {
      fail(
        `block "${want.title}" expected ${want.start_time}-${want.end_time}, got ${got.start_time}-${got.end_time}`,
      )
    }
  }

  console.log("\n=== Captured /command/ call ===")
  if (call) {
    console.log(`  status=${call.status}`)
    console.log(`  Request body: ${call.requestBody.slice(0, 300)}`)
    console.log(`  Response body: ${call.responseBody.slice(0, 600)}`)
  }
  console.log("\n=== DB after ===")
  console.log(dbStateOut.trim())

  console.log("\n=== Verdict ===")
  if (failures.length === 0) {
    console.log("✅ PASS — mass move worked: all post-13:00 blocks shifted +1h, controls unchanged")
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
