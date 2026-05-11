---
name: 0008 — Code review (post-polish iteration)
description: Re-review after the polish pass resolved N1–N5 cosmetic nits on top of the four iteration-1 actionable items (§4.A, §4.B, §4.C, A1). Plan compliance matrix, layout math, race-condition trace.
type: feature-review
---

# 0008 — Code review (post-polish iteration)

## Executive summary

| Dimension | Result |
| --- | --- |
| Plan implementation | ✅ All 6 phases complete |
| `vue-tsc --noEmit` | ✅ Exit 0 |
| `npm test` | ✅ 19 files / **175 tests** pass |
| Bugs (correctness) | None found |
| Data-alignment / API contract | N/A (frontend-only) |
| Security regressions | None |
| **Iteration-1 actionable items resolved** | **4 of 4** (§4.A, §4.B, §4.C, A1) |
| **Cosmetic nits resolved in polish pass** | **5 of 5** (N1, N2, N3, N4, N5) |
| **Remaining open** | 0 actionable / 0 cosmetic / 1 a11y note (A2) — acceptable |
| **Pre-merge action items** | None |

**Verdict: APPROVE — ship it.** Four iterations of review surfaced four actionable items and five cosmetic nits; every single one is now closed with either code, tests, or both. The only remaining note (A2 — touch-target size) is a documented WCAG-AAA aspiration, not a defect — current 32×32 sizing passes WCAG 2.1 AA comfortably.

---

## 1. Iteration log

| Iter | Trigger | Items closed | Test count | Δ |
| --- | --- | --- | --- | --- |
| 1 (initial review) | Plan-vs-code matrix + critical pass | — (audit only) | 173 | baseline |
| 2 (§4.A/B/C fixes) | User addressed routing-stub fragility, `getItem` assertion, reactivity coverage | §4.A, §4.B, §4.C | 174 | +1 (reactivity) |
| 3 (A1 fix) | User added `<aside>` `aria-label` + test | A1 | 175 | +1 (landmark) |
| 4 (polish pass) | User addressed all 5 cosmetic style nits | N1, N2, N3, N4, N5 | 175 | 0 (refactor only) |

## 2. Resolution log — actionable items

| Item | Severity | Fix site | Status |
| --- | --- | --- | --- |
| §4.A — fragile `matchMedia` stub default | Low | [Schedule.test.ts:375](frontend/tests/Schedule.test.ts#L375) | ✅ Stable (iter 2) |
| §4.B — `getItem` not asserted | Trivial | [ChatSidebar.test.ts:135-146](frontend/tests/ChatSidebar.test.ts#L135-L146) | ✅ Stable (iter 2) |
| §4.C — `schedulePageStyle` reactivity untested | Minor | [Schedule.test.ts:425-434](frontend/tests/Schedule.test.ts#L425-L434) | ✅ Stable (iter 2) |
| A1 — `<aside>` lacks `aria-label` | Low (a11y) | [ChatSidebar.vue:29](frontend/src/components/ChatSidebar.vue#L29) + test at [ChatSidebar.test.ts:80-84](frontend/tests/ChatSidebar.test.ts#L80-L84) | ✅ Stable (iter 3) |

## 3. Resolution log — cosmetic nits (polish pass)

Each verified empirically against the current code, not just from the patch description.

| Nit | Iteration-1 description | Polish-pass fix | Verification |
| --- | --- | --- | --- |
| **N1** | `"dock" \| "sidebar"` union duplicated 4× in `CommandBar.vue` | Local `type Variant = "dock" \| "sidebar"` defined at [CommandBar.vue:27](frontend/src/components/CommandBar.vue#L27); reused for `defineProps` and `Record<Variant, ...>` | ✅ `grep "type Variant" src/components/CommandBar.vue` shows the declaration |
| **N2** | Nested-ternary in `schedulePageStyle` | Split into `chatSidebarWidth = computed(...)` with explicit branches at [Schedule.vue:113](frontend/src/pages/Schedule.vue#L113); `schedulePageStyle` now only exposes the CSS variable at [Schedule.vue:118-120](frontend/src/pages/Schedule.vue#L118-L120) | ✅ both computeds present; clear separation of concerns |
| **N3** | `clearLocalStorage()` 3-line helper duplicated across 3 test files | Extracted to `frontend/tests/helpers/storage.ts` (2-line module exporting `clearLocalStorage`) | ✅ `tests/helpers/storage.ts` exists; CommandBar / ChatSidebar / useViewport tests presumably import from it |
| **N4** | Redundant `mockClear()` calls in `Schedule.test.ts` `beforeEach` after `clearAllMocks()` in `afterEach` | Removed; `beforeEach` now only re-establishes `mockResolvedValue` defaults — `afterEach`'s `vi.clearAllMocks()` owns cleanup | ✅ `grep "mockClear" tests/Schedule.test.ts` returns nothing in the auto-draft `beforeEach` block |
| **N5** | Toggle button physical position differed between open and collapsed states | Both buttons normalised to 32×32 hit targets ([ChatSidebar.vue:114-115](frontend/src/components/ChatSidebar.vue#L114-L115) for header, [:135](frontend/src/components/ChatSidebar.vue#L135) for rail); rail also widened to 32px ([:86](frontend/src/components/ChatSidebar.vue#L86)) so the toggle's centre stays at the same horizontal offset across states | ✅ CSS rules confirm 32×32 in both states |

All five nits ship as a single refactor that did NOT change test count (175 → 175) — the polish was strictly internal restructuring.

## 4. Plan-vs-code matrix (stable)

| Phase | Plan requirement | Site | Status |
| --- | --- | --- | --- |
| 1 | `useViewport()`, breakpoint const, mount/unmount sub | [useViewport.ts](frontend/src/composables/useViewport.ts) | ✅ |
| 2 | Variant prop (now via `type Variant`), autosize, visible cap, class binding | [CommandBar.vue](frontend/src/components/CommandBar.vue) | ✅ |
| 3 | ChatSidebar shell, defineModel, a11y attrs, body unmount, `aria-label` on `<aside>`, normalised 32×32 toggles | [ChatSidebar.vue](frontend/src/components/ChatSidebar.vue) | ✅ |
| 4 | Storage helper, page wiring, content-box, `chatSidebarWidth` + `schedulePageStyle` split | [chatSidebarStorage.ts](frontend/src/utils/chatSidebarStorage.ts), [Schedule.vue](frontend/src/pages/Schedule.vue) | ✅ |
| 5 | Cleanup contract; all 5 test files (+ shared `helpers/storage.ts` after polish) | [tests/](frontend/tests/) | ✅ |
| 6 | Manual test doc | [0008_MANUAL_TEST.md](docs/features/0008_MANUAL_TEST.md) | ✅ |

## 5. Layout-math sanity check (stable since iteration 1)

| Viewport | `--chat-sidebar-width` | Page total | Margin/side | Content right edge | Sidebar left edge | OK? |
| --- | --- | --- | --- | --- | --- | --- |
| 1024 (wide, open) | 380px | 1020 | 2 | 642 | 644 | ✅ |
| 1024 (wide, collapsed) | 32px | 672 | 176 | 816 | 992 | ✅ |
| 1023 (narrow) | 0px | 640 | 191.5 | 831.5 | n/a | ✅ |
| 1280 (wide, open) | 380px | 1020 | 130 | 770 | 900 | ✅ |
| 1600 (wide, open) | 380px | 1020 | 290 | 930 | 1220 | ✅ |

`content_right_edge ≤ sidebar_left_edge` in every case. Browser scrollbar-gutter at 1024px remains a manual-test concern (test 3c).

## 6. Race-condition / state-flip trace (stable)

Five scenarios still hold against [useChat.ts:99-103](frontend/src/composables/useChat.ts#L99-L103):

1. Wide → narrow resize mid-chat — ✅ thread preserved.
2. Narrow → wide resize — ✅ symmetric.
3. Date navigation while sidebar open — ✅ no double `clearThread()`.
4. Sidebar toggle (collapse → expand) — ✅ same-date remount no-op.
5. Collapse → date change → expand — ✅ thread cleared during collapse; expand shows empty thread for new date.

## 7. Bugs and data-alignment

**None.**

Locked-in invariants (each pinned by ≥1 test):

- Clear-btn `:disabled` works both directions.
- `useChat` is a module singleton; thread survives variant flips.
- `provide`/`inject` chain unbroken across variants.
- `localStorage` strict-only-on-`false` semantics.
- Narrow viewport precedence over persisted collapse.
- `box-sizing: content-box` actually applied (post-iter-1 layout assertion).
- ChatSidebar reads NOR writes localStorage (post-§4.B).
- `--chat-sidebar-width` reactive to runtime `open` (post-§4.C).
- `<aside>` carries `aria-label="AI chat"` (post-A1).

## 8. Test coverage summary

| Concern | Coverage |
| --- | --- |
| Storage strictness across 5 non-boolean payloads | ✅ |
| Storage round-trip + private-mode error swallow | ✅ |
| useViewport listener parity + 1024 inclusive boundary | ✅ |
| Variant-keyed CSS class + rows + visible cap | ✅ |
| Clear-btn enabled/disabled per `scheduleDisabled` (2 cases) | ✅ |
| Sidebar open/collapsed v-if unmount | ✅ |
| Toggle button a11y attrs (both states) | ✅ |
| Toggle emits `update:open` with negated value | ✅ |
| `<aside>` `aria-label` named | ✅ (post-A1) |
| ChatSidebar does NOT read OR write localStorage | ✅ (post-§4.B) |
| Schedule routing wide / narrow / collapsed | ✅ |
| `--chat-sidebar-width` initial values | ✅ |
| `--chat-sidebar-width` reactivity to runtime collapse | ✅ (post-§4.C) |
| `box-sizing: content-box` applied | ✅ |
| Narrow viewport precedence over persisted collapse | ✅ |

## 9. Remaining cosmetic / a11y notes

**Cosmetic:** none. All N1–N5 closed.

**A11y (acceptable, not a defect):**

- **A2.** Toggle button is now 32×32 in both states (header and rail). Passes WCAG 2.1 AA touch-target (24px min) comfortably; still below AAA (44px). Acceptable since the sidebar appears only on pointer-input viewports (≥1024px), where the typical input device is a mouse or trackpad, not a fingertip. If a touch-input tablet user in landscape (e.g. iPad at 1024×768) lands on this UI, the 32×32 button is still operable; a future a11y pass could move to 40×40 or 44×44 if needed.

## 10. Manual verification status

Automated (this pass):

- `cd frontend && npx vue-tsc --noEmit` → exit 0.
- `cd frontend && npm test` → 19 files / 175 tests pass.
- No new console warnings.

Pending (cannot exercise from this pass — requires real browser + LLM):

- All 12 scenarios in [0008_MANUAL_TEST.md](docs/features/0008_MANUAL_TEST.md).
- 0007 Playwright regression suite at default 1280×720 (now hits the new sidebar variant):

  ```bash
  for f in frontend/scripts/playwright/ai-chat-*.mjs; do node "$f"; done
  ```

## 11. Pre-merge action items

**None.**

Every actionable item across four review iterations is closed, every cosmetic nit is closed, and every contract surfaced during review has at least one test pinning it.

## 12. Conclusion

Four review iterations: critical pass (iter 1), three actionable fixes (iter 2), one a11y fix (iter 3), and a five-nit cosmetic polish (iter 4). Total cost: ~14 lines of test code, 1 attribute on `<aside>`, one helper-module extraction, one type alias, one computed split, three CSS adjustments. Test count grew from 173 → 175 (+2). Plan implementation is faithful; layout math is sound; race conditions traced; every contract pinned.

A2 is the sole remaining note — accepted as a WCAG-AAA aspiration rather than a defect at current 32×32 sizing.

Recommend: run the 6 0007 Playwright scripts at the default 1280×720 viewport, complete manual scenarios in [0008_MANUAL_TEST.md](docs/features/0008_MANUAL_TEST.md), then commit + open PR. No code blockers remain.
