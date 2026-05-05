// Reproduction script for the TemplateEditor blocks-table layout bug.
//
// What it does: logs in as the ``playwright`` test user, opens
// ``/settings/``, creates a weekday template, adds one block, then
// measures the rendered widths of the Title input vs Start / End /
// Category controls. The bug from the manual Phase 5 test:
//
//   * Side-by-side weekday/weekend cards halve the page width.
//   * The blocks ``<table>`` defaults to ``table-layout: auto``, which
//     distributes by intrinsic content width.
//   * ``<input type="time">`` and ``<select>`` carry built-in
//     picker/dropdown controls (~80-110px intrinsic), so the empty
//     ``<input type="text">`` for Title gets squeezed to padding.
//
// Run from repo root:
//
//   cd frontend && node scripts/playwright/template-editor-layout.mjs
//
// Pre-reqs:
//   * Django running on :8006 (``make run``)
//   * Vite running on :5173 (``make frontend-dev``)
//   * Test user ``playwright`` created via the snippet below.
//
// ⚠️  WARNING — LOCAL DEVELOPMENT ONLY
// The snippet below creates a Django SUPERUSER with a known weak
// password (``playwright-pw-do-not-use-in-prod``). Running it against
// a production database creates a backdoor admin account anyone with
// network access to the app can log into. Never paste it into a
// production manage.py shell. Only run against your local SQLite dev
// DB (``db/day_forge.db``):
//
//       uv run python backend/manage.py shell -c "
//       from django.contrib.auth.models import User
//       u, _ = User.objects.get_or_create(username='playwright', defaults={'is_staff': True, 'is_superuser': True})
//       u.set_password('playwright-pw-do-not-use-in-prod'); u.save()"

import { chromium } from "@playwright/test"
import { mkdirSync } from "node:fs"
import { dirname, resolve } from "node:path"
import { fileURLToPath } from "node:url"

const BASE = "http://localhost:5173"
const USERNAME = "playwright"
const PASSWORD = "playwright-pw-do-not-use-in-prod"

// All artefacts (screenshots) land in the same dir as the script.
const HERE = dirname(fileURLToPath(import.meta.url))
mkdirSync(HERE, { recursive: true })

// Threshold for what counts as "Title is too narrow to be usable".
// 80px is the rough lower bound where you can still type a couple of
// characters and see them. The bug renders Title at ~25-35px.
const TITLE_MIN_USABLE_PX = 80

// A few viewport widths spanning the relevant breakpoints:
//   * 600 — narrow desktop / split-screen, 1-column layout
//   * 900 — laptop-narrow, just above the old 720px breakpoint
//   * 1280 — typical laptop, 2-column layout active
//   * 1920 — wide desktop, 2-column with extra room
const VIEWPORTS = [
  { label: "narrow-600", width: 600 },
  { label: "laptop-900", width: 900 },
  { label: "desktop-1280", width: 1280 },
  { label: "wide-1920", width: 1920 },
]

const browser = await chromium.launch({ headless: true })

async function login(page) {
  await page.goto(`${BASE}/accounts/login/`, { waitUntil: "networkidle" })
  await page.fill("#username", USERNAME)
  await page.fill("#password", PASSWORD)
  await Promise.all([
    page.waitForURL(/\/schedule\//),
    page.click('button[type="submit"]'),
  ])
}

async function openSettingsAndAddBlock(page) {
  await page.goto(`${BASE}/settings/`, { waitUntil: "networkidle" })
  // Click "Create template" under the weekday slot (first one — the
  // template-grid renders weekday on the left).
  await page.locator('button:has-text("Create template")').first().click()
  // Wait for the editor form to render.
  await page.waitForSelector('input[maxlength="100"]')
  // Add one block.
  await page.click('button:has-text("+ Add block")')
  // Wait for the table row.
  await page.waitForSelector("table.blocks-table tbody tr")
}

async function measureLayout(page) {
  return await page.evaluate(() => {
    const round = (n) => Math.round(n * 10) / 10
    const editor = document.querySelector(".template-editor")
    const table = document.querySelector("table.blocks-table")
    const headers = Array.from(
      document.querySelectorAll("table.blocks-table thead th"),
    )
    const cells = Array.from(
      document.querySelectorAll(
        "table.blocks-table tbody tr:first-child td",
      ),
    )
    return {
      cardWidthPx: round(editor?.getBoundingClientRect().width ?? 0),
      tableWidthPx: round(table?.getBoundingClientRect().width ?? 0),
      columns: headers.map((h, i) => {
        const cell = cells[i]
        const input = cell?.querySelector("input, select")
        return {
          header: h.textContent?.trim() || "(empty)",
          cellWidthPx: round(cell?.getBoundingClientRect().width ?? 0),
          inputWidthPx: input
            ? round(input.getBoundingClientRect().width)
            : null,
          inputType: input?.tagName.toLowerCase(),
          inputAttrType: input?.getAttribute("type"),
        }
      }),
    }
  })
}

function diagnose(measurements) {
  const titleCol = measurements.columns.find((c) => c.header === "Title")
  if (!titleCol || titleCol.inputWidthPx === null) {
    return { ok: false, reason: "Title column not found in measurements" }
  }
  if (titleCol.inputWidthPx < TITLE_MIN_USABLE_PX) {
    return {
      ok: false,
      reason: `Title input is ${titleCol.inputWidthPx}px wide (< ${TITLE_MIN_USABLE_PX}px usable threshold)`,
      titleWidth: titleCol.inputWidthPx,
    }
  }
  return { ok: true, titleWidth: titleCol.inputWidthPx }
}

async function runOneViewport({ label, width }) {
  const context = await browser.newContext({
    viewport: { width, height: 800 },
  })
  const page = await context.newPage()
  try {
    await login(page)
    await openSettingsAndAddBlock(page)
    const measurements = await measureLayout(page)
    const screenshotPath = resolve(
      HERE,
      `template-editor-layout-${label}.png`,
    )
    await page.screenshot({ path: screenshotPath, fullPage: false })
    const verdict = diagnose(measurements)
    return { label, width, measurements, screenshotPath, verdict }
  } finally {
    await context.close()
  }
}

const results = []
try {
  for (const vp of VIEWPORTS) {
    console.log(`\n→ Viewport ${vp.label} (${vp.width}px)…`)
    const result = await runOneViewport(vp)
    results.push(result)
    const m = result.measurements
    console.log(
      `  Card ${m.cardWidthPx}px, Title input ${m.columns.find((c) => c.header === "Title")?.inputWidthPx ?? "?"}px → ${result.verdict.ok ? "✅ PASS" : "❌ FAIL: " + result.verdict.reason}`,
    )
  }
} catch (err) {
  console.error("\nFAILED with error:")
  console.error(err)
  process.exitCode = 2
} finally {
  await browser.close()
}

console.log("\n=== Summary ===")
let allPassed = true
for (const r of results) {
  const titleW =
    r.measurements.columns.find((c) => c.header === "Title")?.inputWidthPx ??
    0
  const status = r.verdict.ok ? "✅" : "❌"
  console.log(
    `${status} ${r.label.padEnd(15)} viewport=${String(r.width).padStart(4)}px  card=${String(r.measurements.cardWidthPx).padStart(6)}px  title=${String(titleW).padStart(6)}px`,
  )
  if (!r.verdict.ok) allPassed = false
}
console.log("")
process.exitCode = allPassed ? 0 : 1
