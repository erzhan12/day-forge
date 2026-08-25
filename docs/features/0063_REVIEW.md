# Feature 0063 — External code review trail

Plan: `docs/features/0063_PLAN.md` · Issue #170 (user-customizable time-block categories).

Reviewers: OpenAI **codex** (`gpt-5.6-sol`, read-only) + **cursor** agent (`--mode ask`), run
independently each round. Every finding verified against the code before accept/reject.

## Iteration 1

### Accepted → fixed

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | P2 | `create_block` in-txn `validate_slug` raises `ValueError`, but the enclosing `try` caught only `ValidationError` → **500** on a slug deleted mid-request (`schedules/api.py`). | Added `except ValueError` → clean 400. |
| 2 | P2 | `create_block_from_event` — same in-txn `ValueError`→500. | Same `except ValueError` → 400. |
| 3 | P2 | Concurrent same-slug/label `create_category` → `Category.create` `IntegrityError` uncaught (endpoint catches only `ValueError`) → **500** (`schedules/categories.py`, `category_api.py`). | Bounded 3-attempt retry (re-reads rows → next free slug suffix / re-triggers dup-label check) → else clean `ValueError` (400). |
| 4 | P2 | `restore_blocks` folded categories only *before* the write transaction; a category deleted in between could be resurrected on `bulk_create` (`schedules/api.py`). | Re-fold each instance's category against a fresh catalog **inside** the write `transaction.atomic()` (reuses the existing lenient `unknown_to_sink` fold). |
| 5 | P1 (cursor) / regression | `schedules/http.py:149` `except ValueError, TypeError:` — the feature diff had **de-parenthesized** the previously-correct `except (ValueError, TypeError):`. | Reverted to the parenthesized tuple. NB: the "invalid Python 3 / import fails" characterization is **false on this interpreter** — Python 3.14 (PEP 758) parses the un-parenthesized form and catches both types; the full suite (1143 tests) imports and passes either way. Reverted anyway: it is gratuitous, breaks on <3.14, and reads as a bug to every reviewer. |

Regression tests added to `backend/tests/test_categories.py`: omitted-`create_block`-category → user default (`work`); in-txn deleted-slug → 400 not 500; concurrent-create `IntegrityError` → clean error (service + HTTP).

### Rejected (verified false / severity downgraded, with evidence)

- **Travel-rule create/PATCH TOCTOU (codex P2 / cursor P2):** rejected as P2, recorded as an **accepted P3 gap**. The only outcome of the narrow SQLite-serialized window is a *dangling category slug* on a rule, which the system **explicitly tolerates** — unknown stored slugs fold to the sink at read/analytics time (an acceptance criterion of the feature). This is the same class as the **already-documented accepted concurrency gap** in `travel_rules.py:218` (the row-cap race). Not worth wrapping create/PATCH in an atomic revalidation for a benign, self-healing condition.
- **`seed_templates` writes hardcoded seed slugs without sink resolution (codex P2 / cursor P3):** rejected as P2, recorded as **accepted P3**. The seeded templates use the four standard seed slugs, which every freshly-seeded catalog contains; the only way to produce a stale slug is to delete a standard category *and then* re-seed templates, and the result is again a tolerated dangling slug → sink. The plan itself scoped sink-resolution here as "defensive fallback only."
- **`except ValueError, TypeError` = "SyntaxError / module fails to import" (cursor P1):** factually false on the pinned Python 3.14 (PEP 758) — proven empirically (the module imports; 1143 tests pass). The line was still reverted for robustness (see accepted #5), but the stated severity/mechanism was incorrect.

### P3 noted, not fixed (non-blocking)

- Leftover `VALID_CATEGORIES` export in `schedules/http.py` + stale `RULES.md` notes + `admin.py` `list_filter` on `category` (plan REFACTOR cleanup — deferred; removing the export risks import breakage for no correctness gain).
- Slug-keyed color maps remain; `categoryColors4a` not rekeyed by `color_id` (cosmetic; 4a map currently unused by the hex resolver).
- Settings panel: `swap()` refreshes unconditionally without surfacing a failed reorder; one-line compressed Vue/TS vs sibling panels; no per-row busy state.
- `create_category` uses DB `iexact` vs the create path's `casefold()` (Unicode-equivalence edge, e.g. `Straße`/`STRASSE`).
- `delete_category` `bulk_update`s all of a user's `DailyReview` rows rather than only those containing the deleted slug (minor write amplification).
- `_SLUG_RE` present but unused (slug format is generator-controlled; no negative tests).

### Verification after fixes
Backend `pytest`: **1143 passed**. `ruff check backend/`: clean.

## Iteration 2

Both engines confirmed the iteration-1 fixes present and correct. Two new P2s (codex), both accepted and fixed; cursor: NO P1/P2.

| # | Severity | Finding | Fix |
|---|---|---|---|
| 1 | P2 | `category_api.category_detail` DELETE/PATCH: the service re-fetches the row under its transaction (`select_for_update().get()`); a concurrent delete → `Category.DoesNotExist` (not `ValueError`) → **500** instead of 404. | Catch `Category.DoesNotExist` → 404 in both DELETE and PATCH. Also catch `IntegrityError` on PATCH (concurrent same-label race on the CI-unique constraint) → clean 400 — covers cursor's P3 on `update_category`. |
| 2 | P2 | `AddToScheduleDialog` initialised the category from a matched rule's slug without catalog-membership; a dangling slug has no `<select>` option and Confirm submits it → backend 400 instead of a graceful sink. | Resolve the rule override through `orderedCategories(props.categories)` (same source as the `<select>` options); unknown/empty → `sinkCategory`. |

Regression tests added: concurrent-delete-races-DELETE → 404, concurrent-delete-races-PATCH → 404, same-label PATCH `IntegrityError` → 400.

### Verification after iteration 2
Backend `pytest`: **1146 passed**. Frontend `vitest`: **963 passed**. `vue-tsc`: clean. `ruff`: clean.

## Iteration 3 — SUCCESS

Both engines returned **NO P1/P2 FINDINGS** and confirmed the iteration-2 fixes correct. No new P3s. Convergence reached.

```
ext-code-review trace
  scope: ~72 files (feature 0063)
  engines: codex + cursor
  iterations: 3/10
  findings: raised ~24, accepted 7 (fixed 7), rejected 3 (with evidence), P3-ignored ~11
  verification: backend 1146 passed, frontend 963 passed, vue-tsc clean, ruff clean
  result: SUCCESS
```
