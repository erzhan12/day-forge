# Phase 4 — AI Command Bar Manual Test Plan

Scope: the natural-language command bar at the bottom of the schedule page, the `POST /api/ai/schedules/<date>/command/` endpoint, server-side validation, error envelopes, rate limiting, the `AIInteraction` audit row, and undo integration.

---

## Setup

Two terminals (from **project root**):

```bash
# Terminal 1 — Django (:8006)
# Set LLM_API_KEY (and optionally LLM_MODEL) in .env before starting.
# Loaded automatically via python-dotenv.
make run

# Terminal 2 — Vite (:5173)
make frontend-dev
```

1. Open http://localhost:5173/ and log in.
2. Pick a day with **3–5 existing blocks** spread across 09:00–18:00. Add some manually if empty.
3. DevTools → **Network** (filter `Fetch/XHR`) and **Console**. Keep visible.
4. Open a third terminal for inspecting the audit table (no dedicated `make` target; must use `manage.py shell -c`):
   ```bash
   uv run python backend/manage.py shell -c "from ai.models import AIInteraction; [print(i.id, i.success, i.user_command[:60], len(i.ai_response)) for i in AIInteraction.objects.order_by('-id')[:10]]"
   ```

Endpoint to watch: `POST /api/ai/schedules/<date>/command/`.

Expected response shape on 200: `{ "blocks": [...], "explanation": "..." }`.

---

## 1. Status dot — healthy

- [X] Status dot left of the `›` prompt is **green** with a soft glow.
- [X] Hover tooltip reads "AI online".

## 2. Status dot — unavailable (503)

- [X] Stop Django, blank out `LLM_API_KEY` in `.env`, restart:
      `make run`
- [X] Submit any command (e.g. `add lunch at 13:00 for 30 min`).
- [X] Expect: 503 in Network; status dot turns **red**, tooltip "AI unavailable"; error row reads *"AI is unavailable — manual editing still works."*
- [X] Manually add/edit a block via the existing UI — still works (degraded mode).
- [X] Restore `LLM_API_KEY` in `.env` and restart Django before the next test.

## 3. `/` to focus

- [X] Click anywhere on the page outside an input. Press **`/`**.
- [X] Expect: command bar gains focus; the `/` character does **not** appear in the input.
- [X] Click into a regular `<input>` (e.g. AddBlockForm title), press `/` — typed normally, command bar does NOT steal focus.

## 4. Esc to clear

- [X] Type a command, press **Esc** before submitting.
- [X] Input clears and loses focus; no network call fires.
- [X] If an error row was visible, it disappears.

## 5. Placeholder rotation

- [X] Wait ~12 seconds with the input empty and unfocused.
- [X] Placeholder cycles through 3 examples (English, Russian, English) every ~4 s.

---

## 6. Add — happy path

- [X] Type `add deep work at 09:00 for 90 minutes` and press Enter.
- [X] Expect: spinner appears, then disappears (~1–4 s typical). New 09:00–10:30 block renders. Explanation row shows a one-sentence summary.
- [X] Reload page — block persists.

## 7. Move — preserve duration

- [X] Existing block: 1h "gym" at e.g. 17:00–18:00. Type `move gym to 18:30`.
- [X] Expect: gym now 18:30–19:30 (duration preserved). One 200 response.

## 8. Resize

- [X] Type `make standup 30 minutes`.
- [X] Expect: existing standup block's end_time shifts to start_time + 30 min, or returns a clarification if no standup exists.

## 9. Remove

- [X] Type `delete the lunch block` (assuming a "lunch" block exists).
- [X] Expect: block disappears; audit row created.

## 10. Russian command

- [X] Type `добавь звонок с клиентом в 14:00 на 30 минут`.
- [X] Expect: 200; block "звонок с клиентом" added at 14:00–14:30; explanation also in Russian.

## 11. Ambiguous command — zero actions

- [X] Type `make tomorrow better` (intentionally vague).
- [X] Expect: 200, no schedule change, explanation row shows a clarification request (e.g. "Could you specify which block?"). No AIInteraction row marked `success=False` for this case — it's a successful interaction with zero actions.

---

## 12. Validation — overlap

- [X] Block exists at 10:00–11:00. Type `add a meeting at 10:30 for 30 min`.
- [X] Expect: model may either (a) refuse and explain, or (b) propose the action and the server rejects with `action_index: 0, detail: "block would overlap existing block"`. Either is acceptable; what is **not** acceptable is the overlapping block actually getting created.

## 13. Validation — day window

- [X] Type `add late-night coding at 23:30 for 1 hour`.
- [X] Expect: server rejects with `end_time must be <= 23:00` (working day window). Schedule unchanged.

## 14. Validation — 5-minute granularity

- [X] Type `add review at 09:07 for 20 min`.
- [X] Expect: model should snap to 09:05 / 09:10. If it doesn't, the server rejects with the granularity message.

## 15. Validation — midnight wrap on move

- [X] Block at 22:00–23:00 (only possible if you bypass UI guards by editing directly). Type `move it to 23:00`.
- [X] Expect: 400 with `moved block would extend past midnight`. Schedule unchanged.

## 16. Validation — referenced block deleted between LLM call and apply

Race regression check.

- [X] Type a command referencing a specific block (e.g. `move standup to 11:00`) and **before pressing Enter**, in a second tab on the same day, delete the standup block.
- [X] Submit the command in the first tab.
- [X] Expect: 400 with detail *"Referenced block no longer exists; it may have been deleted. Please retry."* — not a 500 / not a phantom block.

---

## 17. Empty command guard

- [X] Press Enter with the input empty (just whitespace).
- [X] Expect: no network call (client-side guard); spinner does not appear.

## 18. Oversized command

- [X] Paste a 600-character string (over `LLM_MAX_COMMAND_CHARS=500`).
- [X] Expect: 400 with `command too long (max 500 chars)`. Audit row IS created with the full pre-trim string up to 2 000 chars (preserves evidence the cap was exceeded).

## 19. Malformed body — defensive only

- [ ] In DevTools console, run:
      `fetch('/api/ai/schedules/2026-04-22/command/', {method:'POST', headers:{'X-CSRFToken': document.cookie.match(/csrftoken=([^;]+)/)[1]}, body: 'not json'})`
- [ ] Expect: 400 `{"errors":{"body":"Invalid JSON."}}`.

---

## 20. Rate limit (429)

Simulate fast — set the limit low in `.env`, restart Django.

- [X] Set `LLM_RATE_LIMIT_PER_HOUR=3` in `.env`, then `make run`
- [X] Submit 4 commands in a row (any text).
- [X] Expect: requests 1–3 succeed (or fail per-command); request 4 returns **429** with `Rate limit exceeded. Try again later.`
- [X] Server log shows `AI rate limit exceeded for user <id>`.
- [X] Wait 60 minutes OR restart Django (LocMem cache resets) — counter clears.
- [X] Restore `LLM_RATE_LIMIT_PER_HOUR` to the default in `.env` before subsequent tests.

## 21. Provider timeout (504)

- [X] Set `LLM_REQUEST_TIMEOUT=0.001` in `.env`, then `make run`
- [X] Submit any command.
- [X] Expect: 504 with `AI provider timed out`; status dot turns red; server log shows `AI timeout: ...`.
- [X] Restore `LLM_REQUEST_TIMEOUT=15` in `.env`.

## 22. Provider auth failure (502)

- [X] Set `LLM_API_KEY=sk-obviously-wrong` in `.env`, then `make run`
- [X] Submit any command.
- [X] Expect: 502 with the **generic** `AI service error` (no provider URL, no auth detail leaked). Server log shows `AI provider error: ...` with the real reason.
- [X] Status dot turns red.

## 23. Garbage response (502 parse)

Hard to reproduce against a real provider. If you have a self-hosted proxy, point `LLM_BASE_URL` at one that returns non-JSON. Otherwise rely on parsing coverage in `backend/tests/test_ai_service.py::TestParsing`: run narrowed with `uv run pytest backend/tests/test_ai_service.py::TestParsing -v`, or the full backend suite via `make test-backend` (Make has no pytest-args shortcut). Flag if parsing tests start failing.

---

## 24. Audit log — success row

- [X] Submit a clean `add` command, wait for success.
- [X] Run the inspector command from Setup. Most recent row:
  - `success=True`
  - `user_command` = exactly what you typed (≤2 000 chars)
  - `ai_response` length > 0 (raw JSON the model returned)
- [X] In Django admin (`/admin/ai/aiinteraction/`), the row's `actions_json` matches what got applied.

## 25. Audit log — failure row

- [X] Trigger any 4xx/5xx (e.g. test 13's day-window failure).
- [X] Newest AIInteraction row has `success=False`. The row was written **before** the failed apply step — confirm that.

## 26. Audit log — rollback survives

- [X] Construct a multi-action command that partially succeeds, e.g. `add focus 09:00–10:00 and add another at 23:30 for 1 hour` (second action fails day-window).
- [X] Expect: 400; **neither** block exists in the schedule (whole batch rolled back); the AIInteraction row IS persisted with `success=False`.

---

## 27. Undo after AI command

- [X] Submit `add coffee at 15:00 for 15 min`. Wait for success.
- [X] Press **Ctrl/⌘+Z**.
- [X] Expect: schedule reverts to the pre-AI snapshot (the new coffee block disappears, all other blocks restored to their pre-AI state). One `restore/` request returns 200.
- [X] Toast text references the AI explanation, not a generic "AI command".

## 28. Undo after multi-action AI command

- [X] Submit `move standup to 11:00 and add lunch at 13:00 for 45 min`.
- [X] Press Ctrl/⌘+Z once.
- [X] Expect: **both** changes reverted in one undo (AI command is one undo unit, not one per action).

## 29. Undo NOT registered on AI failure

- [X] Trigger a failing AI command (e.g. the day-window violation from test 13).
- [X] Press Ctrl/⌘+Z.
- [X] Expect: undo pops the **previous** action (or no-ops if stack empty) — the failed AI attempt was never pushed onto the undo stack.

---

## 30. Concurrency — two AI commands in flight

- [X] Submit a command, and **before** the spinner clears, attempt to submit another.
- [X] Expect: input is `disabled` while `isProcessing` is true; second submit is a no-op until the first completes.

## 31. Spinner cleared on error

- [X] Trigger any error (503/504/429).
- [X] Spinner disappears; input is editable again; status dot reflects new state.

---

## What to watch for

- **Network**: every successful AI command emits exactly one `command/` POST and one Inertia `?only=blocks` reload. No duplicate POSTs.
- **Console**: no errors. CSRF failures (403) indicate a missing `csrftoken` cookie — check `useHttp.ts`.
- **Status dot**: only goes red on 502/503/504 or network failure. A 400 (validation, bad input) keeps the dot green — the AI service itself is healthy, the user's command was just invalid.
- **Audit table**: every submitted command produces exactly one row, regardless of outcome. Missing rows = bug.
- **Privacy**: do NOT paste real API keys / passwords into the command bar — they get logged verbatim into `AIInteraction.user_command` (capped at 2 KB but still readable).

---

## Failure template

If a step fails, capture:
1. Step number.
2. Expected vs. actual.
3. Console errors (full text).
4. Failing request: method, path, status, response body.
5. Most recent AIInteraction row (id, success, ai_response first 500 chars).
6. Relevant Django log lines (the `ai` logger).
