---
name: "0014 ai_command non-dict JSON body - implementation review"
description: Code review against docs/features/0014_PLAN.md
date: 2026-05-27
---

# Feature 0014 — Code Review

Review of the `ai_command` non-dict JSON body guard (PR #37 parity fix) against `docs/features/0014_PLAN.md`.

## Verdict

**Approve — ready to merge.** Implementation matches the plan exactly. Prior review follow-ups (inline comment + test docstring) are addressed. Targeted and full `test_ai_views.py` suites pass; ruff is clean. No blocking or important issues.

---

## Findings

### No blocking or important issues

No bugs, data-shape mismatches, or missing core functionality were found. The guard runs before any DB or LLM work, so malformed bodies fail fast with 400 as intended.

### Resolved since first review

| ID | Area | Resolution |
|----|------|------------|
| M1 | Comment parity | `ai_command` now carries the same four-line guard comment as `ai_chat` (~lines 538–541 in `backend/ai/views.py`). |
| M2 | Test docstring | `test_non_dict_json_body` includes a contract docstring mirroring `test_ai_views_chat.py::test_non_object_json_root_returns_400`, with an explicit cross-reference to the chat test. |

### Informational (plan scope only)

| ID | Area | Note |
|----|------|------|
| I1 | Literal coverage | Plan parametrizes five non-dict roots; `false` would hit the same guard but is omitted. Consistent with the plan’s explicit list; no implementation gap. |

---

## Plan compliance

| Plan requirement | Status |
|------------------|--------|
| Add `isinstance(data, dict)` guard in `async def ai_command` immediately after `json.loads` try/except | ✅ |
| Return 400 with `{"errors": {"body": "Request body must be a JSON object."}}` | ✅ |
| Match `ai_chat` precedent for envelope and status | ✅ |
| No changes to other functions in `views.py` | ✅ |
| Parametrized regression test in existing `ai_command` test class | ✅ |
| Five cases: `[]`, `"x"`, `123`, `null`, `true` | ✅ |
| Each case asserts HTTP 400 and exact error string | ✅ |
| `ai_generate_draft` unaffected (no JSON body parse) | ✅ (confirmed by inspection) |

---

## Confirmed good

### Fix correctness

- **Guard placement:** Runs after `json.JSONDecodeError` handling and before `data.get("command")`, preventing the `AttributeError` → 500 path described in the plan.
- **Error envelope:** Uses the same `errors.body` key and message as `ai_chat`, `schedules/api.py`, `analytics/views.py`, and the adjacent `"Invalid JSON."` response in the same function — no snake_case / nesting drift.
- **Scope:** Guard + shared comment block only; no refactor or unrelated edits.

### Parity with `ai_chat`

- **View comment:** Word-for-word match with the `ai_chat` guard comment (lines 952–955), adapted only by placement after the compact `"Invalid JSON."` response in `ai_command`.
- **Test docstring:** Same contract language as the chat test; additionally documents the cross-endpoint mirror and asserts the exact error string (stricter than chat’s `"errors" in payload` check).

### Code style

- JsonResponse formatting in `ai_command` matches the compact style of the `"Invalid JSON."` line directly above it (multi-line formatting remains in `ai_chat` only — pre-existing, not introduced here).
- Test follows existing `TestRouting` patterns: `@pytest.mark.django_db`, raw POST with `content_type="application/json"`, no unnecessary fixtures.

---

## Tests review

### Coverage map

| File | What it proves |
|------|----------------|
| `backend/tests/test_ai_views.py::TestRouting::test_non_dict_json_body` | All five non-dict JSON roots return 400 with exact `errors.body` message; no LLM/DB side effects on invalid input. |

### Test quality

- **Isolation:** Validation fails before `run_command` or schedule lookup; no monkeypatch needed — appropriate for this layer.
- **Naming:** `test_non_dict_json_body` is clear and aligned with sibling routing tests (`test_invalid_json_body`, `test_non_string_command`).
- **Documentation:** Contract docstring explains the 500 → 400 regression and links to the chat equivalent.
- **Speed:** Lightweight HTTP posts only; parametrization adds five fast cases.
- **Strictness:** Asserts exact error string, which is stronger than the parallel chat test (`test_non_object_json_root_returns_400` only checks `"errors" in payload`).

### Pre-existing gap (out of scope)

- `test_invalid_json_body` asserts status 400 only, not the `"Invalid JSON."` message — unchanged by this feature.

---

## Verification run

Commands executed during this re-review:

```bash
uv run pytest backend/tests/test_ai_views.py::TestRouting::test_non_dict_json_body -q
uv run pytest backend/tests/test_ai_views.py -q
uv run ruff check backend/ai/views.py backend/tests/test_ai_views.py
```

Results:

- Parametrized non-dict cases: **5 passed**
- Full `test_ai_views.py`: **35 passed**
- Ruff: **All checks passed**

---

## Manual verification

Not required for this backend-only input-validation fix; automated tests cover the contract. Optional smoke: `curl -X POST …/command/ -d '[]' -H 'Content-Type: application/json'` with auth should return 400, not 500.
