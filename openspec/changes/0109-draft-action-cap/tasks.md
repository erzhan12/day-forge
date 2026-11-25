# 0109 — draft action cap tasks

## 1. Caps
- [x] Red: validator, service and endpoint tests at and one over the draft cap; chat cap regression
- [x] Green: `templates_mgr/limits.py`, `MAX_DRAFT_ACTIONS`, explicit `max_actions` in `validate_response_envelope`
- [x] Draft prompt rule 8 states the cap

## 2. Timeout
- [x] Estimate output tokens for a 60-add draft
- [x] Add `LLM_DRAFT_REQUEST_TIMEOUT` (default 60, positive) and use it in `run_draft`

## 3. Apply and templates
- [x] 60-add apply in one revision; overlapping 60-add draft writes nothing
- [x] Template POST/PUT boundary and one-over tests

## 4. Finish
- [x] Update `RULES.md`, `docs/api.md`, `.claude/rules/project.md`, `README.md`, `.env.example`
- [x] Run `make lint`, the backend suite and `make spec-check`
- [ ] Archive the change on the feature branch before merge
