# 0034 — Code Review Trail

Feature: `restore_blocks` category-type hardening (issue #121) — `isinstance(str)`
guard before the `VALID_CATEGORIES` set check (unhashable `list`/`dict` category
→ 400 not 500), plus deferring `Schedule.objects.get_or_create` past validation
so a 400 on a new date does not orphan an empty `Schedule` row (same class as #103).

## External review trail — iteration 1

**Engines:** codex (`gpt-5.6-sol`, read-only) + cursor (`--mode ask`), run in parallel.
**Scope:** `backend/schedules/api.py`, `backend/tests/test_restore.py`, `docs/api.md`,
`RULES.md`, `tasks/todo.md` + untracked `docs/features/0034_PLAN.md`.

**Verdict:** both engines returned **NO P1/P2 FINDINGS**. Plan conformance,
guard placement/style, test coverage, docs, and frontend data-alignment
(undo client still sends string `category`) all verified MATCH.

### Findings

| # | Engine | Sev | Location | Verdict |
|---|--------|-----|----------|---------|
| 1 | codex | P3 | `api.py` get_or_create precedes `full_clean()` | ACCEPTED (comment) |
| 2 | cursor | P3 | `api.py` "…400s before we touch the DB" comment now contradicts the deferral | ACCEPTED (comment) — same root as #1 |

Both P3s share one root: after moving `get_or_create` below the manual
validation loop, the pre-existing "if any block is invalid the whole request
400s before we touch the DB" comment became inaccurate, and the `full_clean()`
pre-pass runs *after* `get_or_create` (it must — `full_clean` validates each
instance's `schedule` FK, which is not excluded).

**Reachability check (why comment-only, not a restructure):** `full_clean`
cannot reject a block that already passed the manual per-field loop —
`TimeBlock.clean()` only enforces `start_time < end_time` (already caught by
`_validate_block_times`; cf. `test_restore_start_not_before_end_rejected`),
category `choices` are the same enum that backs `VALID_CATEGORIES`, title
`MaxLengthValidator(255)` is manually checked, and `sort_order` has no model
validator. So the `full_clean`-triggered-400 orphan path is **structurally
unreachable**; moving `get_or_create` later (past `full_clean`) would only
break the FK validation. Resolution: reword the comment to state the ordering
and the belt-and-suspenders nature of `full_clean` accurately.

**Fix applied:** `backend/schedules/api.py` — reworded the apply-block comment
to (a) put the "DB untouched on the 400 path" rationale on `get_or_create`
itself, and (b) note `full_clean` runs after `get_or_create` (needs the FK) and
cannot reject a manually-validated block. No behavioural change.

**Rejected:** none.

**Verification:** `uv run pytest backend/tests/test_restore.py -q` → 22 passed;
`uv run pytest backend/tests/ -q` → 852 passed (pre-fix full run);
`uv run ruff check backend/schedules/api.py` → clean.

**Result:** SUCCESS — zero valid P1/P2, tests + lint green.
