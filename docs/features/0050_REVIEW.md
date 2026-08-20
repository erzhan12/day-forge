# Feature 0050 — Code Review Trail

Calendar-name matching in Travel Rules. Reviewed via `/ext-code-review`
(external engines: OpenAI codex `gpt-5.6-sol` + Cursor agent, read-only).

## External review trail

### Iteration 1 — both engines: NO P1/P2 FINDINGS

The change surface (16 tracked files + migration `0003_travelrule_calendar_name_alter_travelrule_keyword.py`)
had already been through 5 rounds of `/ext-plan-review` at the plan stage,
so the implementation landed clean.

**codex** — NO P1/P2. Three P3 test-coverage suggestions.
**cursor** — full verification log, every plan invariant MATCH end-to-end
(present-key gating, present-empty-not-400, `_parse_patch_payload(data, rule)`
merged-state, `_clean_calendar_name` isinstance guard, matcher pass-1
continue-on-miss / pass-2 empty-skip, case-insensitive both passes, snake_case
wire field end-to-end). Two P3 polish findings.

### P3 findings — triage

| # | Engine | Finding | Verdict |
|---|--------|---------|---------|
| 1 | cursor | `TravelRule.__str__` printed only `keyword`; calendar-only rows show `keyword=''` in admin | ACCEPTED — added `calendar_name` to `__str__` (`models.py`) |
| 2 | cursor | Add-form `.calendar-input` class had no CSS, unlike `.keyword-input` (`flex:1; min-width:160px`) | ACCEPTED — shared the selector (`TravelRulesList.vue`) |
| 3 | codex | No calendar-only `full_clean()` **success** test (only both-blank rejection) | ACCEPTED — `test_model_clean_allows_calendar_only_rule` |
| 4 | codex | Whitespace-keyword test returns in pass 1, can't catch a degenerate empty/empty rule matching in pass 2 | ACCEPTED — `skips a degenerate empty-keyword empty-calendar rule in pass 2` (expects `null`) |
| 5 | codex | Add-form test verifies the request but not the plan-mandated `calendar_name` reset after success | ACCEPTED — `resets the calendar-name input after a successful add` |

No findings rejected — all five were genuine, cheap, and clearly right.

### Verification after fixes

- `uv run pytest backend/tests/test_from_event.py -q` → **92 passed**
- `uv run ruff check backend/calendar_sync/` → **clean**
- `npx vitest run travelRules TravelRulesList` → **34 passed**
- `npx vue-tsc --noEmit` → **exit 0**

## Trace

```
ext-code-review trace
  scope: 16 files + 1 migration
  engines: both (codex gpt-5.6-sol + cursor agent)
  iterations: 1/10
  findings: raised 5, accepted 5 (fixed 5), rejected 0, P3-ignored 0
  verification: backend 92 + frontend 34 passed, ruff clean, tsc exit 0
  result: SUCCESS (iter1 zero P1/P2, tests+lint green)
```
