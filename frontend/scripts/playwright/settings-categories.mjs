// Feature 0063 — Settings → Categories panel smoke.
// Covers: topic navigation, seed rows, sink marker, add / rename / reorder /
// delete a throwaway category, 8-cap guard, idempotent pre-clean.

import { chromium } from "@playwright/test"
import {
  BASE,
  login,
  preflight,
  WAIT_FOR_SHORT_SETTLE_MS,
  WAIT_FOR_INERTIA_SETTLE_MS,
  PANEL_TIMEOUT_MS,
} from "./test-utils.mjs"

await preflight()

const SEED_SLUGS = new Set(["work", "personal", "health", "other"])

async function apiGet(page) {
  return page.evaluate(async () => {
    const csrf = document.cookie.match(/XSRF-TOKEN=([^;]+)/)
    const token = csrf ? decodeURIComponent(csrf[1]) : ""
    const r = await fetch("/api/user/categories/", {
      credentials: "include",
      headers: { "x-xsrf-token": token },
    })
    const data = await r.json()
    return data.categories ?? []
  })
}

async function apiDelete(page, id) {
  return page.evaluate(async (catId) => {
    const csrf = document.cookie.match(/XSRF-TOKEN=([^;]+)/)
    const token = csrf ? decodeURIComponent(csrf[1]) : ""
    const r = await fetch(`/api/user/categories/${catId}/`, {
      method: "DELETE",
      credentials: "include",
      headers: { "x-xsrf-token": token },
    })
    return r.status
  }, id)
}

// Re-locates the first category row whose label input contains `text`.
async function findRow(panel, text) {
  const rows = panel.locator(".category-row")
  const count = await rows.count()
  for (let i = 0; i < count; i++) {
    const val = await rows.nth(i).locator("input").inputValue()
    if (val.includes(text)) return { row: rows.nth(i), index: i, count }
  }
  return null
}

const browser = await chromium.launch({ headless: true })

try {
  const ctx = await browser.newContext({ viewport: { width: 1280, height: 800 } })
  const page = await ctx.newPage()
  await login(page)

  // ── Navigate to Settings → Categories ──────────────────────────────────
  await page.goto(`${BASE}/settings/`, { waitUntil: "networkidle" })
  const nav = page.locator('nav[aria-label="Settings topics"]')
  await nav.waitFor({ state: "visible" })
  await nav.locator('a[href="#categories"]').click()
  await page.waitForURL(/#categories$/)

  const panel = page.locator('[data-settings-topic="categories"]')
  await panel.waitFor({ state: "visible", timeout: PANEL_TIMEOUT_MS })

  // ── Pre-clean: remove leftover smoke rows from prior runs ───────────────
  const existing = await apiGet(page)
  const extras = existing.filter((c) => !SEED_SLUGS.has(c.slug) && !c.is_sink)
  for (const cat of extras) {
    await apiDelete(page, cat.id)
  }
  if (extras.length > 0) {
    await page.reload({ waitUntil: "networkidle" })
    await nav.locator('a[href="#categories"]').click()
    await panel.waitFor({ state: "visible", timeout: PANEL_TIMEOUT_MS })
  }

  const rows = panel.locator(".category-row")

  // ── 1. Assert 4 seed rows ───────────────────────────────────────────────
  const seedCount = await rows.count()
  if (seedCount !== 4) {
    throw new Error(`Expected 4 seed rows, got ${seedCount}`)
  }

  // ── 2. Sink row has "Sink" label and no Delete button ──────────────────
  // Other (sink) is last by sort_order.
  let sinkRow = null
  for (let i = 0; i < 4; i++) {
    const r = rows.nth(i)
    if (await r.locator("text=Sink").isVisible()) {
      sinkRow = r
      break
    }
  }
  if (!sinkRow) throw new Error("Sink marker not visible on any seed row")
  const sinkDeletes = sinkRow.locator("button", { hasText: "Delete" })
  if ((await sinkDeletes.count()) !== 0) {
    throw new Error("Sink row must not have a Delete button")
  }

  // ── 3. Add "Smoke Test" category ───────────────────────────────────────
  const newLabelInput = panel.locator('input[placeholder="New category"]')
  const newColorSelect = panel.locator('select[aria-label="New category color"]')
  const addBtn = panel.locator("button", { hasText: "Add" })

  if (await addBtn.isDisabled()) throw new Error("Add button disabled at 4 rows (cap bug)")

  await newLabelInput.fill("Smoke Test")
  await newColorSelect.selectOption("amber")
  await Promise.all([
    page.waitForResponse((r) =>
      r.url().includes("/api/user/categories/") && r.request().method() === "POST",
    ),
    addBtn.click(),
  ])
  await page.waitForTimeout(WAIT_FOR_INERTIA_SETTLE_MS)

  const afterAdd = await rows.count()
  if (afterAdd !== 5) throw new Error(`Expected 5 rows after add, got ${afterAdd}`)

  const found = await findRow(panel, "Smoke Test")
  if (!found) throw new Error("Smoke Test row not found after add")

  // ── 4. Rename ──────────────────────────────────────────────────────────
  const rowInput = found.row.locator("input")
  await rowInput.fill("Smoke Test Renamed")
  await Promise.all([
    page.waitForResponse((r) =>
      r.url().includes("/api/user/categories/") && r.request().method() === "PATCH",
    ),
    rowInput.press("Tab"),
  ])
  await page.waitForTimeout(WAIT_FOR_INERTIA_SETTLE_MS)

  const afterRename = await findRow(panel, "Smoke Test Renamed")
  if (!afterRename) throw new Error("Row not found as 'Smoke Test Renamed' after rename")

  // ── 5. Reorder (↑) ────────────────────────────────────────────────────
  const indexBefore = afterRename.index
  const upBtn = afterRename.row.locator("button", { hasText: "↑" })
  if (!(await upBtn.isDisabled())) {
    await Promise.all([
      page.waitForResponse((r) =>
        r.url().includes("/api/user/categories/swap/") && r.request().method() === "POST",
      ),
      upBtn.click(),
    ])
    await page.waitForTimeout(WAIT_FOR_INERTIA_SETTLE_MS)

    const afterSwap = await findRow(panel, "Smoke Test Renamed")
    if (!afterSwap) throw new Error("Row missing after reorder")
    if (afterSwap.index >= indexBefore) {
      throw new Error(
        `Row did not move up: was ${indexBefore}, now ${afterSwap.index}`,
      )
    }
  }

  // ── 6. Delete ─────────────────────────────────────────────────────────
  page.on("dialog", (dialog) => dialog.accept())

  const beforeDelete = await findRow(panel, "Smoke Test Renamed")
  if (!beforeDelete) throw new Error("Smoke Test Renamed row not found for delete step")

  const deleteBtn = beforeDelete.row.locator("button", { hasText: "Delete" })
  await Promise.all([
    page.waitForResponse((r) =>
      r.url().includes("/api/user/categories/") && r.request().method() === "DELETE",
    ),
    deleteBtn.click(),
  ])
  await page.waitForTimeout(WAIT_FOR_INERTIA_SETTLE_MS)

  const afterDelete = await rows.count()
  if (afterDelete !== 4) throw new Error(`Expected 4 rows after delete, got ${afterDelete}`)

  if (await findRow(panel, "Smoke Test")) {
    throw new Error("Smoke Test row still present after delete")
  }

  // ── 7. 8-cap guard: Add still visible and not disabled at 4 rows ───────
  const capAddBtn = panel.locator("button", { hasText: "Add" })
  if (await capAddBtn.isDisabled()) {
    throw new Error("Add button disabled at 4 rows — cap enforced too early")
  }

  await ctx.close()
  console.log("\n✅ Settings categories smoke passed.")
} catch (error) {
  console.error("\n❌ Settings categories smoke failed.")
  console.error(error.message)
  process.exitCode = 1
} finally {
  await browser.close()
}
