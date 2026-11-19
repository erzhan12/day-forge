# 0104 — relative-add guard recovery tasks

## 1. Sequential idioms
- [x] Red: idiom unit tests and the reported command through the chat endpoint
- [x] Green: exclude relation matches inside idiom spans
- [x] Refactor

## 2. Recoverable server-owned scope
- [x] Red: fresh guard scope, multi-add, partial completion, re-ask, duration sources, structured sibling, untimed answer, security controls
- [x] Green: internal relative-guard marker, `relative_guard_add_items`, derived items in `finish`
- [x] Green: no-write probe behind the identity gate
- [x] Refactor

## 3. Natural clock answers
- [x] Red: clock answers, start clauses, multi-relation time question, negative controls
- [x] Green: clock-answer helper, start-clause skip, generic-question escape
- [x] Refactor

## 4. Finish
- [x] Frontend regression: pending intent retained after a scope rejection
- [x] Spec deltas with real `Enforced:` / `Tests:` anchors
- [x] Update `RULES.md`, `docs/api.md`, `docs/ARCHITECTURE.md`, `docs/AI_PENDING_INTENT.md`
- [x] Run `make check`, `make spec-check` and `make frontend-build`
- [ ] Archive the change on the feature branch before merge
