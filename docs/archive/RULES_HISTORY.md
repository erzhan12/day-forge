# Rules history through R11

This is a preserved snapshot of the former `RULES.md`, moved during R12. It records feature decisions, incidents, workarounds, and older implementation details. It is historical evidence, not a current implementation contract. Check `RULES.md` and the code before reusing a statement here. The focused R04–R11 reports in `docs/` record the later refactors and their verification.

---

# RULES.md

Project-specific patterns, pitfalls, and conventions discovered during development.
This is a living document — update it as new patterns emerge.

## Secrets & Environment Files

- Never commit `.env` files. `.gitignore` excludes `.env` and `.env.*`, with `!.env.example` carved out so a sanitized template can be committed.
- Secrets belong in env vars, not code or fixtures. See `backend/day_forge/settings.py` and the env var list in `CLAUDE.md` (`LLM_API_KEY`, `DJANGO_SECRET_KEY`, etc.).
- Before committing, sanity-check with `git ls-files | grep -E '(^|/)\.env'` — should return nothing except `.env.example` if one exists.
- User chat turns are logged verbatim to `AIInteraction` (capped at 2 KB). Treat this table as sensitive; don't paste real secrets into the command bar while testing.

## CI: frontend prod-audit gate (feature 0102)

- `.github/workflows/ci.yml` runs on pull requests and is called by the `test` job in `.github/workflows/deploy.yml`. It runs `npm audit --omit=dev --audit-level=high` after `npm ci`; a high/critical advisory blocks PR validation and deployment.
- **Emergency bypass** (a backend-only hotfix blocked by an unresolvable frontend advisory): trigger a manual `workflow_dispatch` run with `skip_prod_audit=true`. It leaves an Actions audit trail and re-engages automatically on the next push. Full usage is in the inline comment above the audit step. Open a follow-up to patch the dep afterward.
- The audit bypass requires `workflow_dispatch` in both the caller and the shared workflow. PRs and pushes cannot skip the audit. Keep lint, type-check, tests, build, audit and SSH pinning in the shared workflow so PR and deployment checks stay aligned.

## CI: GitHub Actions SHA pinning (feature 0060, issue #140)

- **Every external `uses:` in `.github/workflows/*.yml` MUST be pinned to a full 40-hex commit SHA**, never a movable tag (`@v4`), with a trailing `# vX.Y.Z` comment recording the human-readable version. Local reusable workflows use `./.github/workflows/<file>.yml` without a ref and resolve to the caller's commit. Movable tags are a supply-chain risk (upstream can repoint the tag to malicious code). `anthropics/claude-code-action` has repo-write and secrets access, so its pin needs particular care.
- **Resolve a pin** with the GitHub API, then verify the SHA is real before writing it:
  ```bash
  sha=$(gh api "repos/<owner>/<repo>/commits/<tag>" --jq .sha)
  [[ "$sha" =~ ^[0-9a-f]{40}$ ]] || { echo "resolve failed"; exit 1; }
  ```
  For a floating major (e.g. `@v1`) with no precise `vX.Y.Z` tag peeling to `$sha`, pin the SHA anyway and comment `# v1 (no precise release tag at this SHA)`.
- **Repeated actions share ONE identical SHA+comment** — all `actions/checkout` occurrences, both `anthropics/claude-code-action`. A divergent pin is a review-fail.
- **Full verifier** (identity multiset guard, diff-scope, YAML) lives in `docs/features/0060_PLAN.md` §1. When touching workflow pins, re-run it against external references: it must end `uses=N pinned=N status=0`. Count local workflow references separately and verify that each resolves to a tracked repository workflow.
- **Dependabot** (`.github/dependabot.yml`) auto-bumps pins weekly and preserves the SHA+comment format. `anthropics/*` is isolated into its own group so a privileged-action bump can't be rubber-stamped alongside routine `actions/*`/`docker/*` updates.
- **Dependabot `groups.<name>` accepts only** `patterns` / `exclude-patterns` / `dependency-type` / `update-types`. `labels` and `reviewers` are **update-block-level** keys, NOT group keys — the claude-review bot mis-suggested them as per-group; both were rejected (and `reviewers` is deprecated in favour of CODEOWNERS).

## Unified External Tasks Sidebar

- `ExternalTasksSidebar` is the single left task rail. It renders one static section per connected source, emits source-specific retry/complete events, and has one global silent Refresh button. Do not route a Habitica task through Todoist handlers.
- `useExternalSourcePoll` is source-agnostic: while `externalPollActive` (task rail open with a connected task source, and/or a visible connected calendar panel), it fans out to each connected source's silent refresh (`refreshTasks` / `refreshEvents`). It is controlled by `EXTERNAL_TASKS_POLL_INTERVAL_SECONDS` (`0` disables).
- Habitica API gotchas: list dailies with `type=dailys`; send `x-client: {HABITICA_CLIENT_ID}-DayForge`; fetch dailies only for today in the saved user timezone and only keep `isDue` tasks. Habitica undated todos show today only, and overdue todos carry to today in that timezone. Sidebar order follows the pre-sorted `GET .../tasks/user?type=…` array (Habitica applies `tasksOrder` server-side; task JSON has no `position` field) — Day Forge stores that index as an internal sort key (dailies block, then todos block), not due date or title.
- External task text from Todoist/Habitica is display-only and must not be added to draft/chat prompts.

## Dev Server Restart Modes

- `make run` keeps Django's default autoreloader enabled. Use `make run-manual` when code edits should not restart the backend automatically; it passes `--noreload` to `manage.py runserver`.

## XSS / Output Escaping

- Block titles flow user → DB → Vue. Vue's `{{ ... }}` text interpolation auto-escapes, and there is **no `v-html` usage** in `frontend/src/`. Do **not** call `django.utils.html.escape()` on titles before saving — Vue would then render `&lt;` literally, mangling legitimate inputs containing `<`, `>`, or `&`. Escape at the render boundary, not the storage boundary, and only if `v-html` is ever introduced.
- LLM-supplied strings are shape/length-validated in `backend/ai/schemas.py`. Control chars below 0x20 (excluding `\t\n\r`) are rejected to keep titles safe for downstream CSV exports and log scrapers.

## AI Undo Registration

- A successful AI interaction can return an ask or an empty action list without changing the schedule. AI and draft register history through `registerMutationUndo` only when the mutation owner confirms an actual block diff.
- Undo uses the owner's snapshot before the accepted write, its previous revision, and the expected revision after the write. Missing mutation metadata, a no-op, rejection, or reconciliation without a confirmed snapshot creates no history. Partial AI application records the accepted subset.
- `UndoAction.silent?: boolean` controls the toast. Silent actions still enter the stack and support Cmd+Z. Manual operations and AI chat use silent entries; generated drafts show a toast. `performUndo` owns its success and error toasts.

## Completion checkbox optimistic sync (feature 0032, issue #104)

- A native checkbox changes before Vue updates its bound value. `TimeBlock.vue` binds both checkbox branches and completion classes to `displayedCompleted`, changes it optimistically, and restores the current canonical value after failure.
- The completed-value watcher updates the local display while no completion write is pending. The block-ID watcher resets the controller and display when Vue reuses a row for another block.
- Capture block ID, title, and date with each completion intent. Rapid changes run in order and each write captures the confirmed revision and snapshot when its turn starts. The Undo description uses the state that particular intent wrote.
- Both inputs honor the injected `scheduleDisabled` flag. An early return in the click handler alone cannot prevent the native checkbox from changing.
- Completion never repeats PATCH automatically. Permanent errors, conflicts, network errors, and unknown results end the pending intent chain. The schedule owner reconciles uncertain results before accepting another write. Reset and unmount discard unsent intents; they do not imply rollback of a request already sent.

## Schedule.status flip rules

Full transition matrix (post-Phase 6):

```
draft  ──user edits any block──▶  active  ──Mark reviewed click──▶  reviewed
                                  ▲ │                                    │
                                  │ └────────────────────────────────────┘
                                  └── any subsequent edit on reviewed ────┘
                                       (mark_active_on_edit)
```

- Accepted forward changes flip `Schedule.status` from `draft` or `reviewed` to `active`: manual create, from-event create, PATCH, DELETE, reorder, and an AI chat plan with a non-empty accepted diff. These writers call `Schedule.mark_active_on_edit()` inside `execute_schedule_mutation`. Rejected operations and unchanged block payloads leave status and revision unchanged.
- `Schedule.mark_reviewed_if_active()` flips `active → reviewed` (forward direction). Refuses on `draft` — a never-edited day cannot be reviewed (analytics would be meaningless on auto-draft data the user never touched).
- `restore_blocks` (the undo target) does **not** flip status. Calling it with the previous block list shouldn't pretend the user just made a fresh edit. Concretely: undoing a freshly auto-generated draft (`restore_blocks([])`) leaves `status="draft"`, so the regenerate button reappears.
- `ai_generate_draft` does **not** flip status. The badge stays "Draft" until the user actually edits.
- AI chat returning `actions: []` is a no-op after revision and context checks pass. It preserves status and revision; a stale context still returns 409.

### `mark_active_on_edit` MUST use a DB-conditional UPDATE, not a Python `self.status` check

Critical: the helper is implemented as

```python
type(self).objects.filter(
    pk=self.pk,
    status__in=[self.Status.DRAFT, self.Status.REVIEWED],
).update(status=self.Status.ACTIVE)
```

The conditional UPDATE uses the persisted status and recovers from stale model instances. `TestMarkActiveOnEdit::test_stale_instance_recovery` in `backend/tests/test_status_flow.py` pins that behavior. Supported writers call the helper inside the common executor, which owns lock acquisition, expected-version validation, and the revision bump. The helper itself only performs the status transition.

Both helpers also sync `self.status` after a successful UPDATE so callers that re-read the in-memory copy see the new value without a refetch.

## Analytics: current statistics and reviewed snapshots (R10)

- `GET /analytics/<date>/` computes current statistics without creating or updating `DailyReview`. A steady-state visit performs no INSERT, UPDATE or DELETE. First-use settings, categories and preferences may still create their own defaults before the read transaction.
- `is_review_snapshot_current(schedule, review)` is the shared authority for analytics, streak and AI draft history: schedule status is `reviewed`, the review exists, and its non-null `reviewed_revision` equals `schedule.revision`.
- The read transaction captures schedule, ordered blocks, review and streak together. A SELECT lock on User coordinates PostgreSQL writers; SQLite uses one transaction snapshot. GET does not take the SQLite write reservation.
- `mark_reviewed` freezes aggregates inside the R04 User → Schedule → TimeBlock transaction and tags them with the resulting revision. A forward edit makes statistics current again. Restore and category maintenance retain their status policies; a changed revision invalidates the old snapshot even if status stays reviewed.
- Notes use `PATCH /api/analytics/schedules/<date>/notes/`. The first save lazily creates a review row, including for a draft day. Notes alone do not change the day revision or snapshot tag. Row existence does not establish aggregate freshness. The review-ID notes route remains compatible.
- Migration `analytics.0003` tags existing reviewed rows with their current schedule revision without changing aggregates, notes or timestamps. Active/draft rows remain untagged. A missing or stale reviewed snapshot is served as current statistics; an explicit repeat `mark-reviewed` POST repairs it under the write lock without advancing the day revision or changing notes. GET never performs repair.
- See `docs/REFACTORING_R10.md` for migration and verification details.

## `mark_reviewed` checks status before parsing the body or revision

1. Reject an oversized body (413).
2. Parse the URL date (400) and find the user's schedule (404).
3. Enter the common executor and acquire User, Schedule, then TimeBlock locks.
4. REVIEWED returns the current frozen snapshot, or repairs a missing/stale snapshot at the existing revision. DRAFT returns the existing refusal. Neither path parses the body.
5. ACTIVE parses JSON, validates `expected_revision` and optional notes, freezes aggregates and flips status. The executor advances revision once and captures the response before commit.

A valid reviewed retry leaves timestamps and revision unchanged, including with malformed JSON or an obsolete revision. Retry notes are ignored; PATCH edits notes after review. Explicit empty notes clear the saved text on the active path. Notes writes use the same User → Schedule lock and preserve aggregates.

## Streak walker semantics

- `compute_streak(user)` walks dates backward from yesterday, bounded by `ANALYTICS_STREAK_WINDOW_DAYS` (default 30).
- A missing schedule breaks the streak. A zero-block schedule skips the day without counting or breaking it.
- A day with blocks uses frozen completion only when `is_review_snapshot_current` succeeds. Otherwise it computes from current blocks without writing to the database. AI draft history uses the same predicate; draft days remain excluded from draft history.
- Completion at or above `ANALYTICS_STREAK_THRESHOLD` (default 0.8) counts; below it breaks the streak. Eager loading keeps the history and streak queries bounded.

## Skipped-tasks semantics (today vs past)

`SkippedTasks.vue` mirrors `compute_review_stats` exactly:

- **Past day** → every uncompleted block is shown.
- **Today** → only blocks whose `end_time < currentHHMM` are shown. Future-window uncompleted blocks aren't decided yet (still active).
- **Future day** → never shown (analytics_view rejects future dates anyway).

The frontend refreshes `currentHHMM` on a 1-minute interval (matches `Schedule.vue`'s `nowMinutes` cadence) so blocks transition into the list as their windows close. Without this, a block ending at 11:00 would still appear "active" at 11:30 until manual refresh.

## Templates / Rules ownership

- Both `Template` and `Rule` are owned by a `User` (FK). `Template` has a unique `(user, type)` constraint — at most one weekday and one weekend template per user.
- `seed_templates --user <username>` is **required**; there is no fallback to "first superuser". The `0002_user_fk` migration deletes orphan rows; rerun the seed per user post-migration.
- `make seed SEED_USER=<username>` passes the user explicitly and fails before running Django when the value is empty.
- All API queries are scoped by `request.user`. Cross-user PK access returns **404 (not 403)** to avoid id enumeration — same convention as `block_detail`.
- Template POST/PUT/DELETE and Rule mutations run through `run_user_maintenance`, which acquires the shared User write lock and retries the whole transaction on SQLite busy errors. Template category/window validation and refetch happen under that lock. Template uniqueness failures still return 409; exhausted busy retries return `code: schedule_changed`. `seed_templates --user` uses the same maintenance boundary.
- A Rule created without an explicit priority receives `max(existing) + 1`, then the user's priorities are compacted to `0..N-1` in canonical `-priority, id` order. Create and delete compact inside the User-locked maintenance callback; PATCH does not compact. Recompute the default priority on each transaction retry.
- Distinct-value Rule and TravelRule reorders use the atomic `POST /api/rules/swap/` and `POST /api/calendar/travel-rules/swap/` endpoints. Both delegate to `swap_ordering_field` in `schedules/http.py`, which locks the per-user row **and** both target rows (`select_for_update`) — the target-row lock serializes the swap against a concurrent `travel_rule_detail` DELETE, which does not take the user lock — then swaps both values with one `bulk_update`; do not reintroduce the two-PATCH swap gap from feature 0026. Both views also share request parsing via `parse_swap_body(request, *, noun)` (`schedules/http.py`) — oversize gate → JSON → dict-shape → distinct-plain-int-id, returning `(id_a, id_b)` or a 4xx `JsonResponse`; `noun` (`"rule"` / `"travel rule"`) customises the id-error wording. Keep the two views thin over these two shared helpers rather than re-inlining the parse.
- Keep the single-PATCH equal-value nudge branches for legacy duplicate rows: `RulesList.bumpPriority` uses `±1`, while `TravelRulesList.bumpOrder` uses `∓1` because lower `order` sorts first. An equal-value swap would be a no-op.

## Active Rules injection across both AI endpoints

- Chat (`POST /api/ai/schedules/<date>/chat/`) and the draft generator (`POST /api/ai/schedules/<date>/generate-draft/`) both inject the user's active Rules into their server-built prompt context so the model can fill omitted **duration** defaults instead of asking a clarifying question. **Feature 0067 (chat only):** omitted **start times and inter-block spacing are no longer model-computed** — an untimed chat `add` (both `start_time`/`end_time` omitted) is placed deterministically by the backend at the nearest free 5-min-grid slot forward from the current local time (today) or the schedule-window start (other dates), with a 25-min default duration (overridable via an optional `duration_minutes`, a positive multiple of 5) and 10-min gaps around neighbours; if nothing fits, the create is skipped with `reason_code="no_slot"` and a server-owned `ask`. Placement lives in `plan_mutations(..., earliest_start=...)` (reusing `ai/free_slot.py:find_slot`); the fresh apply-time `timezone.localtime()` and the pure `ai/views.py:_earliest_start` helper compute the floor under the apply lock. Rules may still inform `duration_minutes`. **Draft is unchanged: draft `add` still requires explicit HH:MM start/end for every block (no auto-placement).**
- Active/user-owned rule filtering belongs to the view/query layer. `_load_ai_context_sync` captures both endpoints' prompt context under the User lock and orders rules by `-priority, id`. Prompt builders render those rows through `_format_rules_section`; they do not query or re-filter the database.
- Caller orders rules by `-priority` before passing them in; the formatter preserves caller order, so a future "filter inactive at the prompt layer" refactor would silently break the priority-desc invariant.
- **Rule precedence on conflict (feature 0074).** Both system prompts tell the model that rules are listed **highest-priority first** (`Active rules (priority desc)`) and that on a **conflict** the **higher-priority (earlier-listed)** rule wins — a high-priority *default* rule (e.g. DURATION → "default 25 min") overrides a lower-priority *ask/clarify* rule. Draft: `build_system_prompt_draft` ("Higher-priority rules take precedence on conflict."); chat: `build_system_prompt_chat` Hard rule 2. **Do not drop or contradict this clause when editing either prompt** — without it the model can follow a lower-priority "ask" rule and prompt the user instead of applying the default. Note the two numbering surfaces are independent: the **prompt** renders `1.`=highest; the Settings badge (feature 0073) shows `0`=highest.
- Chat-specific: rules render into the **trusted** schedule-context message (the first user-role message), not the untrusted prior-transcript flatten. A tampered client must not be able to impersonate or shadow the user's defaults — see `backend/ai/service.py:run_chat`.

## Chat replay guard (feature 0083, issue #219)

- **Bug signature:** turn 1 "add Momentum (Personal)" adds Momentum; turn 2 "Notes" replayed turn 1's title+category and emitted `Momentum[2]` (the active "same name → add `[N]`" Rule's suffix, applied to the wrong title) instead of adding "Notes". The prompt's untrusted-transcript caveat alone wasn't a strong enough deterrent, so `backend/ai/replay_guard.py` is a deterministic server-side backstop the view enforces regardless of the model's behaviour.
- **Add-only, all-or-nothing.** The replay guard checks `add` actions lexically. If any add is flagged, it skips the whole turn and prepares a server-owned ask. Before returning 200, the view still verifies revision and the prompt-context fingerprint under the common executor. A changed schedule or policy returns 409 even when the guard prevented all mutations.
- **Algorithm:** strip a trailing `[N]` suffix (mirrors the user-Rule convention observed in #219, not a product-wide naming scheme — word-style duplicates like "... copy" or "... II" are NOT covered, an accepted false negative), casefold, collapse whitespace. Step A: the title is allowed if traceable to the LATEST user turn via **any-token overlap** (not all-tokens) — this deliberately keeps rule-driven naming (`add gym` → `Gym Session`) and translations out of the guard, at the cost of a known false negative (`Notes` → `Momentum Notes[2]` passes, accepted because it at least carries the user's own word). Step B (only for titles that fail Step A): the title is flagged as a replay if it (or all its significant tokens) appear as evidence in the PRIOR transcript text.
- **Token match tolerates simple inflection, not derivation:** two tokens match if equal, or both ≥ 4 chars with a common prefix `p` where `len(p) ≥ max(4, len(shorter) − 2)` and each token extends past `p` by ≤ 2 chars. This lets `meeting`↔`meetings` and `обед`↔`обеда` match while rejecting `work`↔`workout`/`workshop` and `notes`↔`notebook`. Tokens < 4 chars only match exactly (documented false positive: `gym`↔`gyms` doesn't bridge Step A).
- **Stopword filter:** a small English+Russian function-word set (articles, prepositions, pronouns, chat verbs) is excluded from tokens on both sides before matching (`Plan for Friday[2]` vs. `add notes for later` doesn't false-positive on `for`/`add`). **Stopword-only titles (`IT`, `On`) are NOT permissive** — for that title only, the guard falls back to UNFILTERED letter tokens on every side (the title, the latest turn, the ask text, and the prior text) so a real replay is still caught. A title with zero letter tokens at all (emoji/number-only) IS permissive — cannot be judged, so it's never flagged.
- **`is_ask` / `is_error` wire markers are UX/correctness gates, not a security boundary.** The client marks an assistant turn `is_ask: true` when its `ask` was non-null, and `is_error: true` on a synthetic failure bubble (`useChat.ts`'s `ask ?? explanation` conflation on `content` is exactly why a separate structural flag exists — content alone can't distinguish an ask turn from an explanation turn, and "ends with `?`" fails because server asks are often not questions, e.g. the `no_slot` copy). A client that forges either flag only disables the guard for its own turn — no more than it could already do by typing the replayed title directly.
- **Recover misplaced provider questions before returning them.** When the LLM-bound latest turn starts with `add` or a Russian `добав` form (including the implicit `add ` rewrite for a bare activity name), a fresh model response with `actions: []`, explicit `ask: null`, and a standalone question in `explanation` is normalized in `run_chat`: the trimmed explanation becomes `ask` before envelope validation. Standalone questions end in `?` or `？`, contain no earlier sentence-ending punctuation, and do not end in a generic conversational closer such as `Anything else?`. This lets short answers such as `past` retain the pending request through both the implicit-add rewrite and replay guard. Other commands, conversational replies, read-only requests, explicit asks, action-bearing responses, and ordinary no-op statements keep their existing behavior. The raw response remains unchanged in the audit log, and the recovered ask must satisfy the usual length limit. This is a conservative fallback for question-shaped explanations, not a general intent classifier. Never infer `is_ask` from client transcript text; structural markers remain authoritative there.
- `is_ask: True` on the immediately preceding assistant turn excludes the contiguous pending user/ask chain from replay evidence, but still checks older handled turns. `is_error: True` walks back the contiguous `(user, is_error assistant)` failure chain and excludes those failed turns plus any contiguous pending ask chain before them. Both paths preserve already-applied siblings as replay evidence through `applied_add_block_ids` and current block IDs. If any ask lacks that list, existing titles are used conservatively. An explicit repeat named in the latest answer remains allowed. After an error, only the immediately preceding ask can supply permissive title evidence; older asks may mention completed tasks as context. If any ask in the pending chain is the guard's own, ask text supplies no such permission because it quotes a rejected title. R11 regression: two asks, a failed answer, and `try again` must retry a never-applied add without repeating a partially applied sibling.
- For a pending ask, the client includes IDs of blocks added during that assistant turn. The guard compares those IDs with current blocks and rejects a same-title add that the latest reply did not name. This prevents a partially applied `add Gym plus Vocal` request from adding `Gym[2]` when the user answers Vocal's time. It still permits `Gym[2]` after a clarification for `add Gym after Vocal` when Gym existed before that request. If a client lacks the IDs, the guard conservatively checks all current block titles. These client markers aid correctness; they are not a security boundary.
- **`is_error` is permissive-only and covers every failure bubble** (400/409/429/5xx/network), not just retryable ones — do not narrow it to 409, it would break a legitimate 5xx retry. A lost-response network failure after the server already committed is the one case where this is actually unsafe (a "try again" can double-apply) — no worse than pre-0083 behaviour, since the guard is silent there either way.
- R11 retains `implicit_add`, replay guard and category resolution. The fixed SDK corpus measures application behavior, not live prompt quality. Known gaps include wrong model output on a refusal, a lost response after commit, and replay after client transcript loss. Durable `request_id` and server-owned `pending_intent` in `docs/REFACTORING_R11_DESIGN.md` are proposals, not implemented guarantees.
- **English-only server strings:** the guard `ask` ("I did not change the schedule: ...") and its `explanation` ("Nothing was changed.") are server-owned English, like every `_build_resolution_ask` string, regardless of the user's language — the third such string for any future i18n pass; the feature 0084 category ask (`Which category should…`) below is the fourth.
- The three "(other than asking what to add)" qualifiers — Hard rule 11 (which phrases its own carve-out inline), the bare-name paragraph, and Hard rule 2 exception (iii) in `backend/ai/prompts.py` — must stay aligned: they resolve the collision between the guard's own "What would you like to add?" ask and the rule that would otherwise resolve a bare-name answer by coreference to an existing block. **Append new Hard rules, never renumber** — tests pin rule numbers by cross-reference.
- **Category label/slug resolution (feature 0084, issue #209).** AI category values are resolved to slugs in `ai/category_resolution.py` **before** schema validation, shared by chat and draft. Resolution: exact slug → case-insensitive slug/label match (first catalog entry wins on a tie) → otherwise unresolved. Unresolved values fall back to the sink slug on `add` (Hard rule 4's existing "default to `other` if unclear", never recorded); on `update`, an unresolved `category` is dropped from `changes` (keeping the rest of the update) or drops the whole action if `category` was the only change — **never quietly recategorised**. Either drop is paired with the server-owned category ask (Hard rule 12, feature 0084, answers it by coreference) unless a competing resolution ask or a replay-guard trip takes precedence; the audit row's `unresolved_categories` payload records it in every case. A genuine schema-validation failure (`AIParseError`, e.g. bad JSON or an unknown key) still returns `502`, but the client-facing `detail` is now the fixed `AI_PARSE_ERROR_DETAIL` string — the real validation message (which can echo model-supplied text) survives only in the chat audit row's `error_detail` or the draft server log at `DEBUG`.
- **Addendum D — implicit "add" rewrite (live-test follow-up).** Even with Hard rule 11, the model can still misread a command-less turn like `Notes` as referring to an earlier turn; the replay guard blocks the resulting replay but the user then gets a clarifying ask instead of the add they meant. `backend/ai/implicit_add.py` (pure, stdlib-only, same design as `replay_guard.py`) rewrites the copy of the LATEST turn sent to the provider — never the stored transcript, the audit `user_command`, the transcript hash, or the replay guard's own evaluation, all of which keep reading the original `messages` — prefixing it with `add ` (`добавь ` when the text contains Cyrillic) whenever the turn carries **no** explicit instruction. It is skipped (text sent unchanged) when: the immediately preceding assistant turn has `is_ask: true` (the turn answers a pending question) or `is_error: true` (a retry after a failure bubble — otherwise `try again` would become `add try again`); the text already contains an English command verb (`add, move, remove, delete, make, resize, rename, shift, extend, shorten, cancel, clear, schedule, put, set, change, swap, split, merge, undo, retry, try, repeat, reschedule, postpone, delay, push, pull, bump, replace, update, edit, create, insert, plan, fill, organize, reorganize, rearrange, optimize, free, skip, drop, complete, finish, list, show, tell, explain, summarize, describe` — `check`/`review` deliberately excluded since they start common block titles, matched whole-word with simple `-s`/`-ed`(`-d`)/`-ing` inflections) or a Russian command stem matched as a word PREFIX (`добав, перенес, перенос, сдвин, удал, убер, убр, сдел, измен, переимен, продл, сократ, отмен, очист, постав, поменя, запланир, повтор, спланир, распланир, планир, отлож, передвин, заполн, освобод, пропуст, заверш, созда, покаж, расскаж, объясн, напомн`); the text is a question (ends `?`, or its leading letter run — so `What's` → `what` — is one of a fixed EN/RU question-starter list); the whole text, casefolded with edge punctuation stripped (`thanks!` → `thanks`), is a short reply / greeting / retry token (`ok, thanks, yes, good morning, again, да, спасибо, доброе утро, ещё раз, ...`); or the text is empty after trimming. Called from `ai/service.py:run_chat` right where `latest_user_turn` is read off `messages[-1]`; `run_chat` builds the outgoing provider message from the rewritten copy but leaves every other use of the original `messages` list untouched.

## AI duration resize ownership (feature 0068)

- Chat-only `resize` accepts exactly one intent mode: explicit boundary time(s), an absolute `duration_minutes`, or a signed `duration_delta_minutes`. Duration modes omit both boundaries; `duration_minutes` remains valid for an untimed chat add, while `duration_delta_minutes` is resize-only.
- The mutation planner, not the LLM or view, computes duration-derived ends in integer minutes. It preserves the effective start, rejects a derived end outside the configured day window or past midnight instead of clamping it, and retains the normal overlap-resolution flow. Keep duration arithmetic out of `compute_move_resize_times()` and persistence code.
- A duration end below the five-minute floor is `interval`; an out-of-window derived end is `out_of_window`. The planner carries explicit provenance so a duration resize always reports `end_time` as applied or skipped rather than a silent successful no-op.

## AI batch mutations (feature 0030, issue #38)

- Chat retains AI-specific intent normalization and partial outcomes in `backend/ai/mutation_planner.py`. Shared snapshots, interval/final-state validation and diff live in `schedules/commands.py` and `schedules/planning.py`. Manual API and draft use the same domain core. `schedules/persistence.py` writes the accepted diff inside `execute_schedule_mutation`. Move order does not determine the result.
- Both endpoints require `expected_revision` before the provider call. They capture blocks, active rules, categories, the day window, and timezone under the User lock. Draft also fingerprints its template. The provider runs after that transaction releases its locks.
- After the provider returns, apply checks revision and re-reads the fingerprint context under User → Schedule → TimeBlock locks. A mismatch returns 409 with `code: schedule_changed` and a refresh message in `errors.detail`. It writes no schedule changes and leaves the audit interaction unsuccessful.
- Clarifying questions, empty action lists, and replay-guard responses perform the same context check. They retain `blocks: null` and return coherent schedule/revision metadata. Draft rechecks both the expected state and day emptiness inside its apply transaction.
- Revision covers block and status changes; it does not replace the policy fingerprint. Settings, rules, templates, and category writers must hold the same User lock. SQLite transaction retries do not call the provider again or automatically resubmit stale intent.

## Schedule mutation executor and revision (R04)

- `backend/schedules/mutations.py` owns the supported write boundary. Manual create/from-event, PATCH, DELETE, reorder, restore, AI chat/draft, and mark-reviewed use `execute_schedule_mutation`. A missing, invalid, or stale `expected_revision` returns controlled 409; the server never supplies the current version for an old client.
- Revision increases once when block fields, block membership/order, or day status change. A no-op preserves revision. Notes and AI audit writes do not increase it. Restore preserves status; an identical restored state also preserves block IDs.
- R07 source policies are explicit: manual/AI grid checks apply to new boundaries, imports and Undo allow off-grid values, Undo bypasses the current window, and draft rejects outside-window values. AI explicitly supplied edges retain intent-based validation. Empty actual diffs preserve status as well as revision, including same-value AI requests on draft/reviewed days.
- R08 integration resource replies carry `meta.account_state` and `meta.resource_state`. A network failure or bare HTTP status cannot establish account existence. Provider credentials 401 requires the explicit `integration_credentials_error` contract; other 401 responses remain session errors.
- `useDatedResource` owns external resource date/context validity, cancellation, account-read arbitration and disposal. Provider adapters own URLs, decoding and error text. Same-date refresh failures preserve rows, and panels display those rows alongside the error. Date/context changes and disconnect invalidate pending task completions as well as GET requests.
- Fernet keys remain independent per provider. Shared crypto helpers must preserve existing ciphertext and safe diagnostics. Cache keys retain provider namespace, Google account ID, timezone and task filter scope. Async Google cache access runs outside the event loop.
- Supported mutation paths validate candidate fields and the complete final schedule before persistence; they do not call `TimeBlock.full_clean()` per row. The DB constraint `timeblock_start_lt_end` protects interval order. Keep `OperationalError` unwrapped so SQLite busy/locked reaches the executor's retry/conflict handling. Migration 0009 refuses invalid legacy rows without modifying them.
- Lock order is User → Schedule → TimeBlock. Multi-day maintenance processes schedules in stable ID order. Category deletion uses the maintenance executor for each changed day, so reassigned blocks increase that day's revision.
- The transaction starts with a User write reservation, then checks revision with a conditional UPDATE before reading mutable state. Callback errors roll back blocks, status, and revision together. SQLite busy/locked retries the whole transaction up to three times, then returns a controlled conflict. Callbacks must contain only database work that can be rolled back.
- Capture `schedule`, `blocks`, and `revision` inside the accepted transaction. Never fetch blocks after commit and attach the previous operation's revision. Schedule and analytics GET captures also use the shared lock to keep revision and blocks consistent.
- Admin views for schedules, blocks, settings, rules, and templates are inspection-only. Seed/reset/cleanup use explicit maintenance callbacks under the same lock; clearing a day preserves its Schedule row and monotonic revision. New application writers must use these boundaries. Fixtures and migrations may use direct ORM writes.
- See `docs/REFACTORING_R04.md` for the writer inventory and deployment sequence. Apply the additive migration with old backend writers stopped, then deploy matching backend/frontend. Do not restore a compatibility path that accepts writes without revision.

## Locking an empty child queryset locks nothing

- On databases with row locks, `SELECT ... FOR UPDATE` over an empty child set locks no rows. Draft must lock the Schedule parent and recheck emptiness under the common User-first write boundary.
- SQLite ignores `FOR UPDATE`. A parent-row SELECT plus a revision comparison cannot serialize its writers. The executor's initial User UPDATE reserves the write transaction, and the conditional revision UPDATE rejects stale requests.
- Manager lock spies check lock intent only. Concurrency and retry tests must also use independent SQLite connections and a real competing write reservation. Keep these tests when changing transaction or locking behavior.

## Shared request and block boundaries (R03)

- Use `common.http.parse_json_object` for JSON request bodies. Its defaults preserve the 100 KB cap and `errors.body` envelope; integration account endpoints retain empty-body handling and `errors.detail`. Settings/preferences pass their response factory to retain private cache headers.
- Keep size, date, ownership and status checks in their established order. `mark_reviewed` checks size first; its under-lock REVIEWED path bypasses JSON parsing and revision validation, including malformed bodies. Only ACTIVE proceeds to request parsing and the expected-version check.
- Use `schedules.serialization.serialize_block` for schedule API, Inertia, analytics and AI response blocks. Keep its wire fields consistent with the frontend Block type.
- `schedules.time_validation` contains pure time parsing and validation. HTTP wrappers map `TimeValidationError` to responses; `schedules.validators` translates it to Django model validation errors.

## Rate-limit consumption order

- For `ai_generate_draft`, common pre-LLM rejections (422 no template, 409 non-empty schedule, 413 oversized body, 400 invalid date) **must not** consume the small (default 10/hr) draft budget — a stale page or a misconfigured account would otherwise exhaust the budget without any LLM call. Chat likewise consumes its counter only after request validation.
- Pattern: drop the decorator, increment the counter inline via `_consume_rate_limit(...)` after every precondition guard and before the LLM call. Provider failures (502/503/504) do still consume the budget — they represent a real LLM call attempt and unlimited retries on a flapping provider would bypass the limit.

## Rate-limit increment: sync `cache.incr`, not async `aincr` (feature 0015)

- AI `_consume_rate_limit` calls `schedules.ratelimit.consume_rate_limit` through `sync_to_async(..., thread_sensitive=True)`. The shared implementation uses synchronous `cache.add` and `cache.incr`; Django's inherited `cache.aincr` performs a non-atomic read/modify/write and resets the TTL. Keep the 3600-second window anchored by the first successful add.
- On a missing-key `ValueError`, retry `add` then `incr` with a bounded attempt count. Never reseed with unconditional `set`/`aset`, which lets concurrent callers reset each other's count. Exhausted retries deny the request. All limiter consumers use `rate_limited_response()` with `Retry-After: 3600`.
- The counter must live in a shared, atomic backend. `ai.E001` (`backend/ai/checks.py`) blocks startup when `LLM_API_KEY` is set and `CACHES['default']` is LocMem / FileBased / Dummy — set `REDIS_URL` (→ `RedisCache`) whenever AI is enabled. FileBased is rejected because its `incr` is not atomic across workers (file locks ≠ Redis `INCR`), not because it is per-process (only LocMem / Dummy are per-process).

## Draft prompt: current time is context, never a filter (feature 0082, issue #202)

- **The bug this prevents.** `build_draft_user_message` renders the current local time into the draft context, and Rule 2 grants permission to drop routinely-skipped blocks. With nothing protecting already-started blocks, the model combined the two and self-censored any template block starting before "now" — generating a draft at 12:00 produced a day with no `Gym 07:30`, so there was nothing to mark complete and the day contributed no completion data, breaking streak/analytics. There was never a Python filter; the loss was purely LLM inference.
- **The user-message line is date-bearing and prefix-preserving.** It renders as `Current local time: HH:MM on YYYY-MM-DD (context only — not a cutoff)`. The date is `now.date()` — the **current local date**, never `schedule.date`; `ai_generate_draft` accepts any ISO date and the frontend drafts non-today days, so without it the model cannot tell today from a future or backfilled day and a bare clock comparison is meaningless. The date and annotation are appended **after** the `HH:MM` on purpose: `backend/tests/test_ai_prompts_draft.py` asserts the substring `"Current local time: 07:30"`, which only survives a prefix-preserving format. Do not reorder that line.
- **Rule 2 invariants.** Past template blocks that are otherwise valid must stay in the draft so the user can record them afterwards. That retention **overrides Rule 2's own skip-drop permission**, but never **Rule 3's** active user rules. History-based shifting of a past block is still allowed — the prompt forbids moving a block *solely* because its time has passed, which is not the same as pinning it to its template time. Window and non-overlap remain hard constraints.
- **Three wording bans on the draft system prompt, each pinned by a test:**
  - no `auto` / `automatic` substring (`test_draft_add_schema_unchanged_requires_explicit_times`) — chat's auto-placement vocabulary must not leak into draft, which still requires explicit HH:MM;
  - no `complet` substring — `_ADD_ALLOWED_KEYS` (`backend/ai/schemas.py`) has no `completed` key and an unknown key fails the **whole** draft as a parse error → 502. Never motivate the rule with "completion analytics"; say "so the user can record them afterwards". The persisted value needs no model cooperation: `TimeBlock.is_completed` defaults `False` and `_apply_add` never sets it;
  - no **line-start** `3. ` marker inside Rule 2 — tests slice Rule 2 with the `"\n2. "` / `"\n3. "` anchors, so only a marker at the start of a line truncates the slice (a mid-line `3.` is harmless). Refer to active user rules in prose rather than opening a new numbered line.
- **Prompt assertions must normalise whitespace.** The system prompt is hard-wrapped at ~72 columns with 3-space continuation indents, so a multi-word phrase is not a contiguous substring. Use the `_squash` helper in `backend/tests/test_ai_prompts_draft.py` (`" ".join(text.split())`); slice on the **raw** prompt first so rule-locality is still pinned, then normalise the slice. A phrase assertion written against the raw text passes only by luck and breaks on the next re-wrap.
- **Bounded by the action cap.** Templates allow up to 50 blocks (`MAX_TEMPLATE_BLOCKS`) while a draft response is rejected above 20 actions (`MAX_ACTIONS_PER_COMMAND`). "Always include every past block" is therefore bounded by that cap. The conflict is pre-existing — Rule 1 already calls the template the day's baseline shape — and 0082 deliberately did not resolve it.
- **Prompt-only, and deliberately so.** Option B (reconciling the returned draft against the template in Python and re-adding dropped blocks) was specified and **rejected for now**: it needs a template-to-action identity notion, a ruling on whether a history-shifted block is still "the same" block, and collision handling. Escalate to it only if a real-model run shows blocks still dropped after this prompt change.

## Auto-draft trigger

- `schedule_view` returns two related Inertia props:
  - `auto_draft_pending`: one-shot signal, true only on the request that *created* the `Schedule` row, AND a template exists, AND `LLM_API_KEY` is set.
  - `has_template_for_type`: ongoing capability flag that drives `RegenerateDraftButton`'s enable/disable state. `auto_draft_pending` flips false after the first paint and can't be reused as a capability signal.
- The frontend uses a `watch(...)` on `[date, auto_draft_pending, blocks.length]` with `immediate: true` and a per-component-instance `attemptedAutoDraftDates: Set<string>` to fire `generateDraft` exactly once per `(component instance, date)` pair. Don't move this to `onMounted` — Inertia's partial reloads (used by every mutation) explicitly do not remount, so `onMounted` would miss new dates reached via partial reload.

## Inertia partial reload props

- A complete accepted mutation response updates the canonical blocks, schedule, and revision directly. AI, draft, manual changes, drag, and Undo do not require a reload to display that snapshot.
- Reconciliation reloads `blocks`, `schedule`, and `auth_user_id` together and awaits Inertia callbacks. Analytics also refreshes review and streak data. Failure to refresh after a successful write reports a display error and never resubmits the write.
- `auto_draft_pending` is a separate Inertia prop. Canonical responses and schedule partial reloads do not reset the component's `attemptedAutoDraftDates` set.

## Frontend mutation owner and Undo (R05)

- `useScheduleRevision` owns the canonical blocks, status, revision, and writer lifecycle for one page. Every mutation captures date, revision, generation, user identity, and the previous blocks together. Its `saving`, `synchronizing`, and conflict phases prevent another write from starting with stale state.
- Accepted complete responses replace the snapshot atomically. Older props cannot lower its revision or replace newer canonical blocks. Missing response state, conflicts, and unknown outcomes require reconciliation; POST and PATCH are never retried automatically.
- Each Undo entry keeps its historical previous and expected revisions. Restore sends that expected revision. After a successful Undo, only a directly preceding entry in the confirmed continuous chain receives the new expected revision. A GET never rebinds all historical entries.
- External edits, conflicts, unknown outcomes, and departed writes invalidate unsafe history. A stale response cannot update another date, a new user's chat, or the current Undo toast. Restore preserves the existing day-status policy; mark-reviewed increases revision and prevents an older restore.
- Shared `auth_user_id` scopes the owner and AI state. Logout, user changes, and invalid sessions clear blocks, history, transcript, pending asks, input, and draft state. Schedule writes send `X-Schedule-User` from their capture; the server rejects an account mismatch with `401` and `code: session_invalid` before any write. A login redirect is also an invalid session; an ordinary 403 remains a rejected request.
- Notes remain outside the schedule revision. Their debounce captures date, user identity and text. Date navigation flushes the outgoing day; user and session changes discard pending drafts and stale error responses. Per-day notes writes are serialized with mark-reviewed so an older payload cannot replace a newer edit.
- See `docs/REFACTORING_R05.md` for the snapshot protocol and regression scenarios. The earlier R04 props gate is replaced by this canonical owner.

## Schedule composition and bootstrap (R09)

- `useSchedulePageController` owns the page's R05 revision controller, Undo and AI lifecycle. Chat and draft state are keyed by this owner. Dock and sidebar share one state; a different page owner has a separate transcript and pending requests.
- Use typed keys from `scheduleContext.ts` for disabled, Undo, drag and schedule-container injection. Mutation helpers consume the same canonical owner.
- `integration_bootstrap` is lazy Inertia data tagged with snapshot ID, user ID, date and saved timezone. A fresh full visit applies account verdicts and travel rules; retained partial-reload props must not restore an obsolete verdict. Explicit null identity clears sources and import state without fallback requests.
- `useExternalSources` loads only confirmed connected sources and owns visibility-based polling. `useEventImport` owns rule readiness and the import dialog; abort and generation guards cover context changes and disposal.
- `useTimelinePresentation` supplies common Classic/4a geometry. Drag freezes origin, bounds, scale, window and time-dependent gaps. Context/size changes and scope disposal cancel it, release pointer capture and remove listeners. The page uses one saved-zone clock for presentation and notifications; PiP remains root-owned.

## PR review iteration loop (AI-driven changes)

For PRs the AI assistant authors in this repo, run the full review-iterate loop autonomously, then **stop at the merge boundary**.

### The loop

1. Open the PR (push branch + `gh pr create`).
2. Wait for `claude-review` (and any other CI) to land. Use the Monitor tool to be notified — don't poll, don't sleep.
3. Read review comments end-to-end before reacting.
4. Triage every finding by **severity AND validity** — not just severity:
   - **Real P0 / P1** (genuine bugs, missed test gaps, real security holes) → fix.
   - **False-positive P0 / P1** (see patterns below) → reject in writing on the PR (a short comment explaining the rationale) rather than silently ignoring. Do not change code to satisfy a misclassified finding.
   - **P2 / P3** → apply the cheap ones inline; otherwise add to `tasks/todo.md` "Follow-ups" section.
5. Push the fixes as one or more follow-up commits. Force-push only when amending the still-pending top commit on a one-commit PR; otherwise stack.
6. Loop back to step 2 until either no findings remain or only P2/P3 are left.

### The merge step is NOT in the loop

When the loop terminates, **report status** (passing CI, no/only-low findings) and **wait for an explicit `merge` / `ok merge` / equivalent from the user** before running `gh pr merge`. Phrases like "fix it", "address the review", "apply suggestions" authorize the code changes only — not the merge. The user retains the merge decision regardless of how confident the automation, the CI, or the auto-reviewer is. Longer-form rationale: `~/.claude/projects/-Users-erzhan-DATA-PROJ-day-forge/memory/feedback_pr_merge.md`.

### Reviewer false-positive patterns observed (don't auto-comply)

These have shown up repeatedly from `claude-review` and were rejected with the user's agreement; recognise the pattern and push back instead of complying:

- **Demanding env vars for credentials in local-dev test fixtures** whose password is clearly marked `do-not-use-in-prod` and whose target is `localhost`. The "credentials" are a fixture, not real secrets; env-var indirection adds friction without changing the threat model.
- **Asking for runtime "production-detection" guards** (e.g. "refuse to run if DB > 50MB") that don't model the actual threat — a dev script's reach is constrained by network / Django settings, not by file sizes. The threshold is also arbitrary and false-positives on real dev DBs after enough use.
- **Suggesting `createsuperuser` (interactive) replace an idempotent Django shell snippet** on "security" grounds. The interactive command breaks automation; the snippet's idempotency IS the point.
- **Adding `refresh_from_db()` after `select_for_update().get()`** "for safety". The `SELECT ... FOR UPDATE` IS the synchronization point — there is no fresher state to fetch.
- **Adding indexes that already exist by Django default** (e.g. on a `OneToOneField`'s implicit unique index, or an `UniqueConstraint(fields=['a', 'b'])`'s composite index). Verify with `sqlite_master` / `pg_indexes` before agreeing.

When in doubt: **a written rejection on the PR > silent ignoring > complying with bad advice**. The conversation log of "here's why we rejected this" is itself useful context for the next reviewer pass.

## New authenticated Inertia page checklist (feature 0010)

Any new authenticated Inertia page MUST do both of:

1. **Backend**: the view passes `ui_preferences=ui_preferences_payload(prefs)` in its Inertia props AND `template_data={"initial_theme": prefs.theme}` to `inertia_render`. Resolve `prefs` exactly once per request via `templates_mgr.preferences.get_user_preferences(request.user)`. Omitting `chat_suggestions` silently makes that page's client resolver fall back to defaults; omitting `template_data` makes `base.html` fall back to the `'classic'` default and Strategic users see a Classic-light flash on the first paint.
2. **Frontend**: the page component calls `useThemeFromProps()` (`frontend/src/composables/useThemeFromProps.ts`) once in its `setup()` block. Without it, partial Inertia reloads that include `ui_preferences` do not propagate to `<html data-theme>`.

### Concrete wiring example

```python
# backend/<app>/views.py
from inertia import render as inertia_render
from templates_mgr.preferences import get_user_preferences, ui_preferences_payload

@login_required
def my_new_page_view(request):
    # Resolve once — both the prop and the SSR template_data use the same value.
    prefs = get_user_preferences(request.user)
    return inertia_render(
        request,
        "MyNewPage",
        {
            # ...your page's own props...
            # Use the canonical serializer so new UiPreferences fields flow
            # automatically — never hand-build this dict.
            "ui_preferences": ui_preferences_payload(prefs),
        },
        template_data={"initial_theme": prefs.theme},
    )
```

```vue
<!-- frontend/src/pages/MyNewPage.vue -->
<script setup lang="ts">
import { useThemeFromProps } from "../composables/useThemeFromProps"
import "../app.css"

// One line, in setup(). Without this, the SSR data-theme is correct on
// first paint but won't follow user theme changes via partial reload.
useThemeFromProps()
// ...rest of your script setup...
</script>
```

If the page renders TimeBlock / SkippedTasks / CategoryBreakdown (or any future component that needs `getCategoryColor()`), also import `useActiveTheme()` from `../composables/useActiveTheme` and pass its computed value into `getCategoryColor(category, activeTheme)`. The category color resolver is non-reactive otherwise.

The P7 SSR first-paint test and the static-scan test enforce (1) and (2) at CI; the rule is documented here so the convention survives session boundaries.

## CalDAV / Apple Calendar (feature 0011)

### Service-boundary owns the secret
`backend/calendar_sync/service.py:fetch_events_for_date` is the **only**
function that calls `account.get_password()`. Views pass the
`CalDAVAccount` instance through; they never touch the plaintext. If a
new code path needs the password, add it inside `service.py` rather than
in the view, otherwise the "credentials never logged" regression test
(`test_calendar_sync_service.py::TestCredentialsNeverLogged`) becomes a
liar.

### Versioned cache keys + the `auto_now` footgun
`backend/calendar_sync/cache.py` keys events by
`account.updated_at.isoformat()` (microsecond precision). Any mutating
call site **must** either call plain `account.save()` (no `update_fields`)
or include `"updated_at"` in the `update_fields` list — a partial save
that omits it bypasses `auto_now=True` and the cache version doesn't
rotate, serving stale events to every worker. The docstring on
`CalDAVAccount.set_password` calls this out at review time;
`test_cache_invalidates_on_account_update` catches the runtime symptom.

### `event.icalendar_instance` is the pinned parse accessor
The Phase 0 spike (`backend/tests/test_caldav_parse_spike.py`) pinned
`event.icalendar_instance` (returns an `icalendar.Calendar`) as the
canonical accessor for `recurring_ical_events.of(...).between(start, end)`.
Don't switch to `icalendar.Calendar.from_ical(event.data)` — it re-parses
on every call and duplicates the work the lib already did.

### `requestJson` cancellation contract
`frontend/src/composables/useHttp.ts:requestJson` accepts an optional
fourth `{ signal }` arg. `AbortError` propagates as a thrown rejection
(unlike normal network failures, which map to `{ok: false, errors: {...}}`).
Stale-response-guard consumers (`useCalendar`, `useCalendarAccount`)
catch and swallow `AbortError` so the superseded op doesn't flip their
`loading` / `error` state. GET-call shape footgun: pass `undefined` as
the third positional arg — `requestJson(url, "GET", { signal })` would
serialise the options object as the JSON body.

### Stale-response guard requires BOTH date and seq tokens
`useCalendar.fetchEvents` uses two commit tokens
(`latestRequestedEventDate` + `eventsRequestSeq`) — date alone is
insufficient because two fetches for the same date can interleave (retry,
`onMounted` + `watch` double-trigger). `useCalendarAccount` splits reads
and writes onto separate seqs and adds `writeCompletionTick` so a read
can never supersede a write. See `useCalendarAccount.ts` header comment
for the full design and the scenario that motivates each guard.

## Google Calendar / OAuth (feature 0022)

`backend/gcal_sync/` mirrors the `calendar_sync` skeleton (crypto / models /
service / cache / checks / views) but for OAuth, multi-account, and an async
events path. Key divergences and footguns:

### Multi-row account model + upsert
`GoogleCalendarAccount` is **`ForeignKey`** (multi-row per user), not the
`OneToOne` of CalDAV/Todoist, with `UniqueConstraint(user,
google_account_id)`. The callback upserts via
`get_or_create(user=…, google_account_id=…)` under
`select_for_update()`, so reconnecting the same Google account **updates** the
row (idempotent). Cache keys therefore embed `account.id` (a user has many
accounts) — `gcal_events:{user_id}:{account_id}:{updated_at}:{date}`.

### Partial success — never blank the panel
The events view (`async def`) fans out with
`asyncio.gather(..., return_exceptions=True)`; a single account's
`GoogleCalAuthError` becomes an `account_errors[]` entry
(`reconnect_required`) while healthy accounts' events still return (HTTP 200).
Only `ImproperlyConfigured` (key rotation, server-wide) short-circuits to a
config-500. The response is the composite `{"events": [...], "account_errors":
[...]}` (the latter always present). The frontend mirrors this: provider
errors are **non-suppressing banners**, never the single suppressing `error`
prop that `ExternalEventsPanel` used pre-0022 — a Google failure must not blank
healthy Apple events. Per-provider retry is routed separately
(`retry(provider)`), Apple ≠ Google.

**Panel placement (wide-only):** `ExternalEventsPanel` lives inside the left
`ExternalTasksSidebar` (default slot, stacked under external task sections) — **not** the
main column. Users can switch back to the legacy center-column placement in
**Settings → External Calendars → Event panel placement** (`externalCalendarPlacementStorage.ts`, device-local). The sidebar shows on wide viewports (`isWide`) when **either**
an external-task source or a calendar is connected (`Schedule.vue:leftSidebarVisible`), with
per-source task gates / `showExtra` gating each section. Center placement renders the
panel above `AddBlockForm` on all viewports (legacy behavior). On narrow/mobile
with sidebar placement there is **no** external-calendar panel by design. Note: `useCalendar`/`useGoogleCalendar` still
fetch on every date regardless of viewport, so on narrow the events are fetched
but not displayed — a deliberate simplicity trade-off (gate the fetch on
`isWide` if that egress ever matters).

### Token refresh concurrency (the P1/P2 design)
`_ensure_access_token` (async) is the only refresh-token decrypt site. The
`select_for_update` lock is acquired in the sync `_persist_refreshed_tokens`
**after** the network refresh, NOT held across it (holding a row lock across an
external HTTP call is an anti-pattern — P2). So two callers can both refresh
against Google before either locks; the guarantee under test is
**persisted-token correctness, not call count**. Double-check: a caller that
finds the row already fresh **and** has no rotated refresh token skips the
write; but a caller holding a **rotated** refresh token persists it even when
the access token is fresh (Google may invalidate the old refresh token on
rotation — P1). All persists are full `save()` (no `update_fields`) so
`auto_now` rotates the cache version (same footgun as CalDAV/Todoist).
`_persist_refreshed_tokens` returns `(token, updated_at)` and
`_ensure_access_token` copies the post-refresh `updated_at` back onto the
**in-memory** account — otherwise a refresh-during-request bumps the DB
version while the view's stale `acc` writes the post-fetch cache under the
dead pre-refresh key (next read misses it; perf-only but wasteful).

### Async-safety gotchas
- The events view does `user = await request.auser()` FIRST; touching the sync
  `request.user` proxy in an `async def` body raises `SynchronousOnlyOperation`
  (the 0009 AI-view pattern). Use the `auser()` result everywhere downstream.
- Parse the `<date>` route string to `datetime.date.fromisoformat(date)` and
  pass the **`date` object** (never the raw string) to the cache + service —
  the cache key calls `target_date.isoformat()`.
- `gcal_sync/cache.py` helpers are `async` (`cache.aget`/`aset`) because the
  only caller is the async view; sync `cache.get/set` under `RedisCache` would
  block the event loop. (The `aincr` non-atomic-RMW footgun is rate-limiter
  specific and does NOT apply to these idempotent versioned get/set.)
- The sync refresh transport runs via `asyncio.to_thread`; the sync ORM persist
  via `sync_to_async(..., thread_sensitive=True)`. `_refresh_sync` is
  **pure-network** (no ORM write) so no sync `.save()` is smuggled into a
  worker thread.

### OAuth correctness
- Scopes are **`.split()`** from the space-separated `GOOGLE_OAUTH_SCOPE` and
  requested as **canonical** strings (`…/auth/userinfo.email`, not the `email`
  alias) so the returned scope set matches and oauthlib doesn't raise "Scope
  has changed". `build_authorization_url` does **not** pass
  `include_granted_scopes` (incremental auth would let Google merge a user's
  other grants on the same client into a superset that trips the scope-equality
  check on `fetch_token`); `service.py` also `os.environ.setdefault`s
  `OAUTHLIB_RELAX_TOKEN_SCOPE=1` as belt-and-suspenders.
- Calendar ids are **`urllib.parse.quote(cal_id, safe="")`**-encoded in the
  events path — Google ids routinely contain `@`/`#` (shared
  `…@group.calendar.google.com`); unescaped they break into extra path
  segments and silently fail shared-calendar fetches.
- **PKCE is disabled** (`_build_flow` sets `flow.autogenerate_code_verifier =
  False`). google-auth-oauthlib defaults it True, so `authorization_url` emits
  a `code_challenge` and stashes the `code_verifier` on the Flow instance — but
  we rebuild a fresh, stateless Flow at callback time, so the verifier is gone
  at token exchange → Google `invalid_grant: Missing code verifier`. We're a
  confidential Web client (client_secret), so PKCE is optional. While PKCE
  provides defense-in-depth even for confidential clients (RFC 7636), the
  marginal benefit is outweighed by the session-persistence complexity in this
  stateless Flow-rebuild architecture; the existing protections (client_secret,
  CSRF state, server-controlled redirect_uri, HTTPS) remain robust. If you ever
  want PKCE back, persist the verifier in the session next to `state`. See
  RFC 7636 for the PKCE spec.
- `connect`/`callback`/`accounts` are sync; only `events` is async. The CSRF
  `state` lives in the session and is `pop`ed in the callback (no replay).
- `exchange_code` (sync) uses `httpx.Client`; the events path uses
  `httpx.AsyncClient`. Don't cross them.

### Shared `NormalizedEvent` (cross-app, intentional)
`gcal_sync` imports `NormalizedEvent` / `normalized_event_to_dict` from
`calendar_sync.schemas` — single source of truth, **deliberate**, not a
layering violation. 0022 added a trailing `account_label: str = ""` field (the
default keeps every existing CalDAV positional constructor + test compiling);
Apple leaves it `""`, Google fills the account email. The frontend
`NormalizedEvent` type + the CalDAV/Google API docs all carry the field.

### Prod boot dependency (divergence from CalDAV)
`gcal_sync.E001` blocks `DEBUG=False` startup if **any** of the four
`GOOGLE_OAUTH_*` vars (client id/secret, redirect uri, token key) is
unset/malformed — **even when no user has connected Google**, unlike
`calendar_sync.E001` (encryption key only). A Google-less staging env must set
all four or stay `DEBUG=True`.

### Tests without pytest-asyncio
Async service functions are driven from sync tests via `asyncio.run(...)`. The
account fixture carries a **fresh cached access token** so
`_ensure_access_token` returns early (no refresh, no `sync_to_async` persist,
no cross-thread DB connection). The refresh/rotation guards are tested directly
against the sync `_persist_refreshed_tokens`. The async events view is driven
through Django's test `Client` with `views.service.fetch_events_for_account`
patched.

## Todoist (features 0020, 0021)

`todoist_sync` mirrors `calendar_sync` one-for-one (new app, same error
hierarchy, versioned cache, system checks, admin, frontend composables +
panel). Differences: a single secret (personal API token, not
apple_id+password+base_url), an HTTP REST client (`requests`, not a DAV
library), and a date→filter algorithm. The same four rules apply:

### Service-boundary owns the secret
`backend/todoist_sync/service.py:fetch_tasks_for_date` **and**
`complete_task` (feature 0021) are the **only two** functions that call
`account.get_token()` (each `del token` in a `finally`). Views pass the
`TodoistAccount` instance through; they never touch the plaintext. New
token-using code goes in `service.py`, or the "token never logged"
regression test (`test_todoist_sync_service.py`, locked across both call
sites by `TestTokenBoundary`) becomes a liar.

### Versioned cache keys + the `auto_now` footgun
`backend/todoist_sync/cache.py` keys tasks by
`account.updated_at.isoformat()`. Any mutating call site **must** call
plain `account.save()` (no `update_fields`) or include `"updated_at"` —
a partial save bypasses `auto_now` and serves stale tasks. The
`TodoistAccount.set_token` docstring calls this out. Cache invalidation on
task complete (feature 0021) is **not** key-deletion: `cache.invalidate_tasks(account)`
just does a plain `account.save()` to bump `updated_at` (rotates every
`todoist_tasks:*` key at once, no key enumeration) — so it is governed by
the **same** footgun. Keep it a plain `save()`.

### Date→filter algorithm + nullable `due_date`
`service.py` maps the selected date to a Todoist filter query and hits the
**dedicated filter endpoint** `GET /api/v1/tasks/filter` (required param
`query`; cursor-paginated `{results, next_cursor}`, `limit` max 200 — loop
until `next_cursor` is null). `selected_date == today` → `query =
"today | overdue"`; else the bare literal-date token `query =
"<YYYY-MM-DD>"` (`due:` semantics; **not** the `date:` keyword). Sort
with a **null-safe** key — `due_date` is nullable (`due == null` → `None`),
so use `key=lambda t: (-t.priority, t.due_date or "", t.title.casefold(),
t.id)`; a bare tuple raises `TypeError` the moment a no-due task appears.
Tasks with no due date never match a date-scoped query, so they never
appear in the panel (by design — empty-state copy must not imply zero
tasks). The `due.date` field is **polymorphic** (full-day `"YYYY-MM-DD"`
vs. timed `"...T..."`); normalise via the `"T"`-in-`raw` branch, time
component dropped. The wire field for the task name is `title` (never
`content`).

### `requestJson` GET footgun + dual-token stale guard (frontend)
Same as CalDAV: `useTodoist.fetchTasks` passes `undefined` as the 3rd
positional arg and `{ signal }` as the 4th; it guards with two commit
tokens (`latestRequestedTaskDate` + `tasksRequestSeq`).
**Connected-state divergence from `useCalendar`**: `GET
/api/todoist/tasks/<date>/` returns `503` **only** on
`TodoistAccount.DoesNotExist`, so a non-503 error (401/500/502/504)
*proves* the account exists — `fetchTasks` sets `connected = true` on
those (not just `503`/`ok`), so the panel's `!connected` gate doesn't hide
the error on first load before `fetchAccountStatus()` resolves.

### Two-way sync (feature 0021): complete + live refresh
- **Optimistic complete with *surgical* rollback** —
  `useTodoist.completeTask` captures **only** the removed task + its index
  (`idx`/`removed`), **never** a whole-list snapshot. On failure it
  re-inserts only that task into the **current** list (and only if absent);
  on success it idempotently re-filters the current list. A whole-list
  `state.tasks = previous` restore would clobber a concurrent `refreshTasks`
  commit (e.g. complete A from `[A,B]`, refresh commits `[B,C]`, A fails →
  a whole-list restore drops C and resurrects A). Always operate on the
  *current* `state.tasks` at success/failure time, not a call-time snapshot.
- **`refresh=1` cache-bypass** — `GET /api/todoist/tasks/<date>/?refresh=1`
  skips the read cache but still re-warms it (additive; no regression to the
  cached read-only flow). Today and overdue scope are determined by the saved user timezone; `carry_overdue` is obsolete and ignored.
- **Silent refresh (no skeleton flash)** — `fetchTasks` delegates to an
  internal `_fetchTasks(date, { force, silent })`. `refreshTasks` passes
  `{ force: true, silent: true }`: `silent` **skips** the `loading=true`
  flip so existing rows stay visible (the panel renders the skeleton on
  `loading`). The initial `fetchTasks` keeps `silent: false`. If you add a
  new fetch entry point, decide `silent` deliberately — a stray
  `loading=true` on a background refresh regresses the no-flash UX.
- **Background polling (#71/#73)** — `EXTERNAL_TASKS_POLL_INTERVAL_SECONDS`
  (default `60`, `0` disables; **do not lower without re-checking provider
  rate limits** — the poll forces `?refresh=1` and Habitica costs two upstream
  calls per tick, so the interval divides its ~30 req/min budget across open
  tabs) is passed to Schedule as
  `external_tasks_poll_interval`. When `> 0` and `externalPollActive` (task
  rail open with a connected task source, and/or a visible connected calendar
  panel), `useExternalSourcePoll` fans out to each connected source's silent
  refresh (`refreshTasks` / `refreshEvents`, `?refresh=1`). Polling pauses
  while `document.hidden`; one refresh fires when the tab becomes visible again.
- **Complete view parses no body** — `POST .../complete/` takes the id in
  the URL path and reads **no** `request.body`, so it has **no**
  `reject_oversized_body` guard (unlike `POST /account/`). Precedence is
  just `503` (no account) → `2xx`/service-error.

## External tasks panel (issue #73)

**UX decision:** one **left-side panel** on Schedule, grouped by integration
(Todoist, Habitica, future apps) — not a separate sidebar per provider.
`ExternalTasksSidebar.vue` is a source-agnostic shell with per-source
sections (`TodoistTasksPanel`, `HabiticaTasksSection`, ...). Each integration keeps
its own backend app (`*_sync`) and composable (`useTodoist`, `useHabitica`);
the shell owns collapse/expand, width, and global refresh. Panel shows when
**any** connected source is present. New integrations add a section +
composable only — no duplicate sidebar chrome.

**Polling decision (#73 / #0031):** one shared **`EXTERNAL_TASKS_POLL_INTERVAL_SECONDS`**
(default **`60`**, `0` = off) for external tasks **and** calendars — replaces
the old Todoist-only poll. While `externalPollActive`,
`useExternalSourcePoll` silently calls `refreshTasks` / `refreshEvents` on
each connected composable every 60s (`?refresh=1`); pauses when
`document.hidden`. Task and calendar fan-outs are gated separately so a
calendar-only tick never polls rail-closed Habitica.

**4a session counter (`ExternalRail4a`):** an empty successful load stores
baseline `∅` (label `0 completed this session / 0`), not `null`. Replace
`∅` when rows later appear. A non-empty baseline never shrinks (completing
the last row can show `1/1`) but **unions newly seen ids** — a task added
in Todoist after a `1/1` session must become `1/2`, not stay `1/1` with
the new row visible. Progress remaining follows the live task list while
`loading` is false (freeze only during an in-flight fetch).

## Production deploy (feature 0016)

The production deploy lives in `deployment/` and targets
`dayforge.habitreward.org` behind the shared habit_reward Caddy. See
`deployment/README.md` for the one-time manual ops checklist.

- **`SECURE_PROXY_SSL_HEADER` is mandatory behind Caddy.** TLS terminates
  at the proxy; the app gets plain HTTP. Without
  `SECURE_PROXY_SSL_HEADER = ("HTTP_X_FORWARDED_PROTO", "https")`
  (settings.py, `if not DEBUG`), `SECURE_SSL_REDIRECT` sees every request
  as insecure and `DEBUG=0` 301-**infinite-loops**.
- **Health probes to `http://localhost:8006/...` need two headers** under
  `DEBUG=0`: `X-Forwarded-Proto: https` (or `SECURE_SSL_REDIRECT` 301s it)
  **and** `Host: dayforge.habitreward.org` (or `ALLOWED_HOSTS` rejects
  `localhost` with 400). The Dockerfile + compose healthchecks send both;
  the pre-flight uses `ALLOWED_HOSTS=localhost` so only the proto header.
- **Two stacks.** Prod is the `deployment/` stack (multi-stage Dockerfile,
  uvicorn ASGI `--workers 1`, `DEBUG=0`). The root `Dockerfile` /
  `docker-compose.yml` stay **dev-only** (`runserver`, `DEBUG=1`, mounts).
- **Static path chain:** Vite `frontend/dist` → `STATICFILES_DIRS` →
  `collectstatic` → WhiteNoise serves it (no Caddy `file_server`).
- **SQLite** lives at `/app/db/day_forge.db`; bind-mount `./data:/app/db`,
  host dir owned by **uid 1000** (the container's `app` user).
- **`:8006` must be locked down via DOCKER-USER iptables** — `ufw deny`
  alone does not block Docker-published ports. Allow Docker-private
  **source** CIDRs (`172.16.0.0/12`), not `-i docker0` (Caddy uses Compose
  `br-*` bridges). Caddy reaches the app via `host.docker.internal:8006`
  on the bridge — do **not** switch to a `127.0.0.1:8006` bind.
- **First deploy:** wire the central Caddy block before expecting the CI
  HTTPS health-check to pass (it probes Caddy, not the app port).

## Sound notifications (feature 0019, issue #56)

Opt-in chime at block start/end. Frontend-only; `useSoundNotifications.ts`
piggybacks the existing 60s `useNowMinutes` sampler — **never add a second
interval** (it would drift out of phase with the now-line). Setting persists
in localStorage (`soundNotificationStorage.ts`, strict-only-on-**true** so
the safe failure mode is silence — inverse of `chatSidebarStorage`).

- **Time-trigger dedup keys MUST include the time, not just the entity id.**
  The fired-Set keys `start:${block.id}:${date}:${minutes}`. A re-timed block
  keeps its `id` across the `router.reload({only:["blocks","schedule"]})`
  re-flow, so an id-only key would suppress the new boundary's chime after
  the old one fired. Any future "fire once per X" guard over re-flowable
  rows has the same footgun.
- **The `AudioContext` is a module-level singleton (`utils/audioContext.ts`)
  that is never closed.** It must survive the Settings→Schedule Inertia
  navigation: the opt-in toggle click is the autoplay-unlock gesture, and it
  has to unlock the *same* context the Schedule detector later plays through.
  A per-instance or refcount-to-0-close context would re-suspend on every
  navigation and drop the first chime. Do **not** close it on component
  unmount.
- **Detection is crossed-since-last-sample `(prev, now]`, not exact equality**
  — a background-tab tick is throttled/coalesced and can skip the exact
  boundary minute. First sample for a cursor (including registration with
  pre-populated `nowMinutes` via `{ immediate: true }` on the shared detector
  watch — issue #113 / feature 0029) fires exact-`now` only (no same-day
  back-fill); a backward clock step (DST / manual) fires nothing. That
  registration-time prime closes the open-at-boundary miss when Schedule's
  `useNowMinutes` samples wall clock before the notification composables mount.
- **Suspension-gap clamp (feature 0033 / issue #112):**
  `MAX_COALESCE_GAP_MINUTES = 5` in `useBlockBoundaryDetector.ts`. On a
  same-day forward jump above the horizon, `inWindow` uses
  `effectivePrev = max(prev, now - 5)` so only `(now - 5, now]` fires —
  multi-hour device-sleep / lunch resumes do not replay every stale
  boundary. Modest coalescing (`now - prev ≤ 5`, including the 4-minute
  test #7 jump) and normal cadence stay on the full `(prev, now]` path.
  The shared sampler resynchronizes on `visibilitychange`; the same bounded
  gap rule still prevents stale notification replay.
- **Saved timezone and midnight (R06):** `useNowMinutes` reads date and minutes
  from one instant in `schedule_window.time_zone`. Its single 60s timer stays
  armed off-today so tomorrow can become today without navigation. Today
  labels, notifications, PiP, and external event fading use that clock.

## Desktop notifications (feature 0028, issue #100)

Opt-in browser desktop notification at block start/end, **independent** of the
sound toggle (both may fire on the same boundary). Frontend-only, default off,
persisted per-device (`desktopNotificationStorage.ts`, same strict-only-on-**true**
silence-safe default as sound). Only fires while the Schedule page is mounted —
no Service Worker, no closed-tab alerts.

- **Shared detector, not a copy.** The crossed-since-last-sample state machine
  now lives in `useBlockBoundaryDetector.ts`; both `useSoundNotifications` and
  `useDesktopNotifications` call it with their own `enabled` ref + `onBoundary`
  callback. Each keeps an **independent** `lastSeenMinute`/`fired` cursor, so
  disabling one channel does not advance the other's. Two `watch(nowMinutes)`
  on the same ref is intentional and cheap — **still never add a second interval**.
  The detector's `{ immediate: true }` registration-time evaluation (feature
  0029) applies to both channels equally: open-at-boundary fires once with
  exact-`now` matching; earlier same-day boundaries are not back-filled.
- **Persist `true` only after permission is `granted`.** `setEnabled(true)`
  calls `Notification.requestPermission()` from the checkbox `@change` user
  gesture, wrapped in try/catch (a throw == denied). Denied/default ⇒ off +
  `permissionDenied` hint; never persists `true`.
- **Stale-request guard is a mandatory, standalone early return.** Each
  `setEnabled` bumps a `requestSeq` token; after the awaited
  `requestPermission` (and after normalising a throw), `if (token !== requestSeq) return`
  BEFORE the granted/denied branches — a late grant arriving after the user
  toggled off must leave the exact `setEnabled(false)` off-state
  (`permissionDenied === false`), never resurrect `true` or stamp a spurious hint.
- **`notSupported` is a distinct flag from `permissionDenied`**, initialised
  unconditionally at setup (`typeof Notification === "undefined"`) so an
  unsupported browser shows the disabled switch + "doesn't support" copy on
  first render — never the "allow in site settings" copy. Mount also clears a
  stale storage `true` on both the unsupported and revoked-permission paths.
- **The component `@change` handler MUST resync the DOM after the await:**
  `el.checked = enabled.value`. `:checked` is a one-way bind, so a **repeated**
  denied click (neither `enabled` nor `permissionDenied` changes) would leave
  the box visually ON without it. Covered by `DesktopNotificationToggle.test.ts`.
- **OS tag embeds `boundaryMinutes`** (`day-forge:${type}:${id}:${date}:${minutes}`)
  to stay aligned with the detector's minute-in-`fired`-key — a re-timed block
  re-fires, so its tag must differ or the OS coalesces the new alert.
- **No AI/provider egress.** Notification title/body are display-only English
  strings in `desktopNotificationCopy.ts` (single place for a future i18n pass);
  never sent to any LLM prompt.

## Timeline trailing stub (features 0017 + 0023)

- **`computeTrailingAnchor` in `frontend/src/utils/scheduleTime.ts` is the
  single source of truth for the trailing anchor** shared by
  `computeRenderBounds` and `buildBaseDisplayItems` (via `pushTrailingGap`).
  Never hand-inline the `min(DAY_END, max(floor, now))` math at a call site —
  the two must produce identical anchors or flow layout desyncs from the stub
  height.
- **`nowMinutes: number | null` param contract:** non-null unambiguously means
  "today" — callers pass `nowDate.value === null ? null : nowMinutes.value`
  (`todayNowMinutes` computed in `Schedule.vue`). The pure helpers never call
  `new Date()`.
- **The now-marker lands at the idle/tail seam, not inside the idle gap.** The
  trailing split boundary equals `now`, so by the half-open `[start,end)` rule
  the idle segment `[lastEnd, now)` excludes `now`; `spliceNowMarker` upgrades
  the compressed tail to `gap-with-now` at `nowOffsetPercent === "0%"` — the
  pixel seam directly under the full-scale idle gap. Correct by construction;
  don't "fix" it to mark the idle segment.
- **Every geometry input to `displayList` must be frozen during drag.**
  `frozenRenderBounds` AND `frozenNowMinutes` (both set in `startDrag`, cleared
  in `resetState` in `useDrag.ts`) feed `buildBaseDisplayItems` while dragging;
  only `spliceNowMarker` reads live now (marker may move, layout may not).
  `displayList` reads `renderBounds.value` only on the non-drag path — an
  unconditional read would re-layout mid-drag on each 60s tick because
  `renderBounds` now depends on `nowMinutes`.
- **4a uses the same vertical scale as classic / Light Premium** (`2` px/min,
  a 60-minute block is 120px). Feature 0055 originally used `1.6` for 4a;
  that made every 4a block 20% shorter than Light Premium. `pxPerMinuteForLayout`
  still exists so drag can freeze the scale, but both profiles return `2`.
- **4a shares the 0017 origin-shift axis, not a full-window uncompressed
  canvas.** `Schedule.vue` sets `timelineOriginMinutes` / `timelineEndMinutes`
  from `renderBounds` (which already unions out-of-window blocks). `Timeline4a`
  sizes compact edge gaps with `render_minutes`, pins a leading stub's visual
  start at the origin so `top` stays non-negative, and places a pre-origin
  now-line proportionally inside that stub. Do not revert the 4a origin to
  `min(window.start, earliest block)` — that restores the empty morning/evening
  dead space. Drag still maps through `getTimelineOriginMinutes` (frozen at
  `startDrag`), which is this compact origin.
- Accepted cosmetic edges (documented in `docs/features/0023_PLAN.md`):
  empty-day pre-06:00 stub labeled "earlier" by `GapSlot`, and trailing-extent
  desync while dragging the last block past frozen-now.

## Static assets / favicon (feature 0025)

- **`frontend/public/` is the home for un-hashed static assets** (favicons,
  logos). It is Vite's default `publicDir` (never overridden in
  `vite.config.ts`), so its contents are copied verbatim into the `dist/`
  root on build. Everything placed there is published **unauthenticated**
  at `/static/<name>`.
- **Full production chain — all four links required:** `frontend/public/`
  → `npm run build` → `frontend/dist/` (the `STATICFILES_DIRS` entry, i.e.
  the *collectstatic source*) → `collectstatic` → `STATIC_ROOT`
  (`staticfiles/`) → served by `WhiteNoiseMiddleware`. `STATICFILES_DIRS`
  alone is **not** a production serving path: with `DEBUG=False` WhiteNoise
  reads only from `STATIC_ROOT` (no `WHITENOISE_USE_FINDERS`), so skipping
  either `npm run build` or `collectstatic` yields silent 404s. The Docker
  deploy does both (`deployment/docker/Dockerfile`,
  `deployment/scripts/entrypoint.sh`).
- Storage is Django's default `StaticFilesStorage` (no `STORAGES` /
  `STATICFILES_STORAGE` override), **not** a manifest storage — `{% static %}`
  is a plain string join that cannot fail on a missing file. A renamed or
  deleted asset surfaces only as a runtime 404.
- **Dual href pattern in `backend/templates/base.html`:** the Vite dev proxy
  does NOT forward `/static/` to Django (see the `server.proxy` list in
  `vite.config.ts`), so icon links live inside the existing
  `{% if vite_dev_mode %}` split — absolute `http://localhost:5173/...` in
  dev, `{% static %}` in prod. Dev hrefs are **absolute, matching the
  adjacent `@vite/client` script tags**: root-relative hrefs would 404 when
  the document is loaded from Django's `:8006` origin directly, which is a
  working dev path precisely because those script tags are absolute.
- **Any public asset *referenced from `base.html`* must be added to BOTH
  branches** (assets that ship without a link — `icon-192/512`,
  `logo-full` — need no template entry). `backend/tests/
  test_base_template_icons.py` enforces this, since nothing else does: dev/prod
  branch parity, each declared `sizes` against the PNG's actual IHDR pixel
  dimensions (stdlib `struct`, no Pillow), on-disk existence in `public/`, and
  the per-branch href convention. Its parse helper asserts the expected link
  count so a template or regex drift fails loudly instead of passing vacuously.
- Logo master (with wordmark) came from Midjourney; the icon-only crop
  (anvil mark, no text) is the favicon source. **Neither master is in the
  repo** — regenerating the icon set means re-exporting from the original
  Midjourney artwork. Committed derivatives: 16/32/48 favicons, 180
  apple-touch-icon, 192/512 PWA-ready icons, and 1024×1024 `logo-full.png`
  (full lockup, currently unused in UI — available for a login-page header).
  All seven were dimension-checked once by hand at commit time; only the
  four linked from `base.html` are **continuously** enforced by the test
  above — the unlinked 192/512/1024 files can drift silently.
- The 192/512 icons are named "PWA-ready" but there is **no web app
  manifest** in the repo and `base.html` links neither; they ship to
  `staticfiles/` as deploy weight only, with zero page-load cost.

## External event → timeline + travel rules (feature 0026)

- **Off-grid times are sanctioned only via `POST .../blocks/from-event/`.**
  Manual `create_block` still enforces 5-minute granularity. Any path that
  re-runs grid validation on *unchanged* times will 400 off-grid blocks.
  Use the shared source policy and changed-boundary validation in
  `schedules/planning.py`; restore uses the Undo policy. Explicitly supplied
  AI boundaries retain their existing intent-based checks. See `docs/features/0026_PLAN.md` critical
  constraint #1.
- **`create_block` and `create_block_from_event` share the HTTP adapter**
  (R07): oversized-body 413, non-object body 400, and
  `isinstance(..., str)` checks for times/title/category keep the same messages.
  Non-string title/category used to 500
  (`AttributeError` / unhashable `TypeError`).
- **`restore_blocks` / `block_detail` share the same category-type pitfall**
  (features 0034 / issue #119): always `isinstance(..., str)` *before*
  checking membership in the category catalog. Set membership hashes the operand, so a
  `list`/`dict` category raises `TypeError` → HTTP 500. Restore uses the
  per-block `(block {i})` suffix. Also defer `Schedule.objects.get_or_create`
  until after validation (same class as #103) so a 400 on a new date does
  not orphan an empty `Schedule` row.
- **Saved timezone controls calendar mapping (R06).** Provider requests span
  the saved-zone local day converted to UTC, including 23/25-hour DST days.
  Timed events remain UTC ISO; all-day events also carry calendar
  `start_date`/exclusive `end_date`. TimeBlock times remain naive `HH:MM`.
  Compute final times in
  `frontend/src/utils/travelRules.ts` (`computeEventBlockTimes` anchors to the
  *viewed* day in the saved user timezone) before POST. Calendar cache keys
  include timezone and representation version. On timezone change, frontend
  external loads discard their prior snapshots and ignore late responses.
- **Travel rules live in `calendar_sync.TravelRule`** (provider-agnostic).
  Matching is two-pass: keyword rules (case-insensitive title substring, with
  optional exact case-insensitive calendar constraint) win first in ascending
  `order`; calendar-only exact-name rules run second in ascending `order`.
  Empty calendar name means any calendar only for keyword rules, never for the
  calendar-only pass. Settings UI: `TravelRulesList.vue` — "up" *decreases*
  `order` (top row wins within a rule class; opposite of `RulesList` priority
  bump).
- **Drag/AI normalize-on-move:** round preserved duration **up** to the next
  5-minute multiple (`roundUpDuration` in `useDrag.ts`; AI bare-move in
  `_compute_move_resize_times`). Drag geometry must use the display-clamped
  span (`[06:00, 23:00)`), not raw block times.

## Playwright smoke harness (feature 0039)

- The 19 browser smoke scripts live in `frontend/scripts/playwright/` and share
  `test-utils.mjs`. Every script calls its GET-based `preflight()` before DB
  setup; a HEAD probe is invalid because Django's login view only permits GET
  and POST. Reuse `login`, the appropriate failure helper, named wait constants,
  `postWithCsrf`, and `seed` instead of copying them into a scenario.
- Database setup belongs in importable `backend/scripts/seed_*.py` modules,
  covered by `backend/tests/test_seed_scripts.py`. Invoke them only through
  `seed()`, which runs `manage.py shell -c "import runpy;
  runpy.run_path(..., run_name='__main__')"`. Pass scenario data as `SEED_*`
  environment variables and spread `process.env`; never interpolate Python
  source into a JavaScript shell string or feed a file to the interactive shell.
- `make e2e` is the all-script entrypoint; `make e2e-chat` and `e2e-draft` are
  focused groups. Runs are serial because scripts share AI
  rate-limit counters and some dates. Several make real provider calls; review
  `frontend/scripts/playwright/README.md` before running them.
- `--cleanup` is opt-in and default-off. Schedule-seeding scripts call
  `cleanupSchedules()` from `finally`; without the flag, seeded rows remain for
  post-mortem inspection. Scripts that seed no schedules have no cleanup call.
  New scenarios must register every seeded date and avoid `process.exit()` after
  browser launch, since it skips `finally`.

## Focus indicator — Document PiP (feature 0049, issue #131)

- **Shared completion controller — never re-inline.** `useBlockCompletion.ts`
  owns the block-completion intent queue, request lifecycle, generation
  guards, and silent Undo registration. The timeline checkbox (`TimeBlock.vue`) routes through it. It is
  a **per-call-site factory, NOT a singleton**: each call returns its own
  `{ saving, errorState, setCompleted, complete, reset, dispose }`. `TimeBlock`
  creates one per row (N rows → N instances). The PiP indicator is
  display-only (active-block progress + remaining minutes, or an idle-gap
  next-block title + countdown — see the PiP privacy invariant below) and
  does **not** complete blocks. A singleton would collapse per-row `saving`/`generation` and regress
  the abort-on-list-reshape invariant (issue #21). `TimeBlock` keeps its own
  optimistic `displayedCompleted` + local `errorMessage` string ("Failed to
  update" copy, pinned by `TimeBlock.test.ts`). `setCompleted` resolves
  `"success" | "failure" | "superseded"`; revert the optimistic flip only on
  `"failure"`, never `"superseded"`. `reset()` (identity change) aborts +
  clears `saving`/`errorState`; `dispose()` (unmount) aborts + bumps
  generation only. Composables guard `onUnmounted` with `getCurrentInstance()`
  so they're unit-testable by direct call.
- **PiP privacy invariant (narrowed by feature 0079).** The active state now
  shows the current block's **title** and its **category colour** — 0079
  deliberately reversed the 0066 rule so "in a block" and "in a pause" are
  distinguishable without reading the text. Still prohibited everywhere, in
  every state: the **date**, **wall-clock times**, the raw category **slug**
  (only the resolved colour ships), unrelated block identities, and any of the
  above in `document.title` (the generic constant `"Focus"`), `aria-*`,
  `data-testid` or error copy. Derived countdowns are allowed and use the
  timeline badge's own `formatRemainingMinutes` copy (`"18m left"`,
  `"1h 30m left"`) — a `mm:ss` countdown was tried in 0079 and rejected.
  There is no settings toggle for this always-on-top/screen-share tradeoff.
  `FocusIndicatorView.vue` props are `active/progressPercent/errorState/`
  `blockTitle/categoryColor/remainingMinutes/nextBlockTitle/`
  `nextBlockRemainingMinutes/pausePercent/dayFinished`. The isolated-view
  privacy test is necessary-but-not-sufficient; the load-bearing integration
  test (`scheduleFocusIndicator.test.ts`) must cover active, pause and
  day-finished states separately against the REAL mounted PiP `document.body`
  + `document.title`.
- **PiP two-state visual contract (feature 0079).** Both states render exactly
  **two `.fi-row`s and one `.fi-track`**, so a block boundary never changes the
  window height. Active: category-coloured `.fi-rail` + solid `.fi-track` fill,
  `#ECEAE6` ink. Pause: everything `#8E9299`, a two-bar `.fi-pause-glyph`
  (CSS bars mirroring the active rail — never a literal `||`, which reads as
  two pipes and is nonsense to a screen reader) with an `.fi-sr-only` "Pause",
  dashed track
  (`repeating-linear-gradient`, not a border style) — **no category colour and
  no `#ECEAE6` anywhere**. `pausePercent === null` means the pause has no
  measurable origin (nothing has ended yet today): the dashed track then
  renders decoratively, with **no `progressbar` role and no fill**. Copy in
  this window is English (`· day finished`) like the rest of the app — the 5a
  mock's Russian labels were deliberately not carried over.
- **The PiP body carries no control of its own (0079).** The view renders no
  button and emits nothing; `useFocusIndicator` mounts it with plain
  `config.props()`. Dismissal is either the PiP chrome's own close button
  (`pagehide` → non-intent, restorable with one Show click) or the header Hide
  (explicit, clears the device flag). This **narrows the explicit-close list**
  below: the in-PiP X is gone, so header Hide and a definite `Login`
  transition are the only explicit closes left. Re-adding a control means
  re-adding `onClose` wiring in `useFocusIndicator`, not just a button.
- **`isDayFinished` fails closed.** `Pause · day finished` requires a
  non-empty day where every block parses, no block is inverted (`end < start`),
  and every block has ended. Malformed times, an empty day, or a still-running
  (even completed) block all fall back to the neutral `—` state rather than
  claiming a finished day. "No block starts after now" alone is NOT sufficient.
- **PiP view CSS must be injected into the PiP document.** Document
  Picture-in-Picture is a separate `Document`. Vue SFC `<style scoped>` is
  injected into the opener by Vite and does not apply inside the PiP. Any
  widget mounted with `createApp(…).mount()` in `pipWindow.document` must
  include its visual rules in the `<style>` string injected into
  `pipWindow.document.head` (`PIP_STYLES` in `useFocusIndicator.ts`). Do not
  clone `app.css`.
- **Persistent PiP ownership and close semantics.** `FocusIndicatorHost` is
  the application-root owner around Inertia `<App>`; pages only publish copied
  schedule snapshots to its controller, so swaps and idle gaps never unmount
  the PiP. Since 0079 dropped the in-PiP X, only the header Hide and a definite
  `Login` component transition are **explicit** closes (via `cleanup()`): they
  clear retained data and the device flag. Browser PiP chrome dismissal (Chrome's "Back to tab" /
  window-close → `pagehide`) and root disposal are **non-intent**: the window
  closes but the flag is preserved, so the dismissal is restorable with one Show
  click (and survives a reload).
- **Gesture-gated restore intent.** `requestWindow()` must be called
  synchronously from a Show-button gesture (`useFocusIndicator.open()`); a
  `pendingOpen` flag and epoch guard protect races. The strict-only-true,
  safe-storage device key `day-forge:focus-indicator:should-be-open` is set
  only after successful open and is never an auto-open trigger. After reload it
  only exposes a restore affordance; the next Show click performs the sole
  request. `window.documentPictureInPicture` is not in TS DOM libs → ambient
  declaration in `frontend/src/types/document-pip.d.ts`.
- **Reactive bridge.** The PiP is a separate `Document`; the view is a **second
  `createApp` with a render function** (`createApp({ render: () => h(view,
  props()) })`, mirroring `app.ts:29`) whose `props()` re-reads the shared refs'
  `.value` each render, so `nowMinutes` ticks repaint it live. Teardown calls
  `app.unmount()` before `window.close()`.
- **One clock: `useNowMinutes`, 60s.** 0079 briefly added a second-resolution
  `useNowSeconds` for a `mm:ss` countdown and then removed it with the format.
  Do not reintroduce a second timer beside `useNowMinutes`: block selection on
  one clock and a countdown on another drift by up to 59s at a boundary and
  show a live block with a spent countdown. With a minute-granularity label a
  1Hz tick buys nothing visually either — one second moves a progress fill by
  well under a tenth of a percent.
- **Just-completed suppression.** On a `"success"` PiP completion, `Schedule`
  sets `justCompletedId` so the indicator goes neutral immediately (bridging the
  gap before the async `router.reload` lands). It is cleared on the next
  `props.blocks` update (success reload OR a competing undo restore) — NOT on
  `is_completed === true` — so a Cmd+Z undo strictly within the reload gap
  re-activates the block. The controller `reset()` watch keys on the **raw**
  (pre-suppression) `activeUnfinishedBlock` id, never the display-active value.
- **Vitest fake-PiP.** Stub `window.documentPictureInPicture.requestWindow` to
  resolve a fake window whose `document` is a real
  `document.implementation.createHTMLDocument("")` (so Vue can mount into it and
  `querySelector` works) with `addEventListener`/`close`/`_emit`. Do not depend
  on real browser PiP. macOS-Chrome always-on-top + minimized-app behavior is
  manual-smoke only (`docs/features/0049_PLAN.md` § Browser smoke).

## Per-user schedule window (feature 0053)

- Resolve scheduling bounds through `schedules.window.get_schedule_window(user)`.
  `DEFAULT_WINDOW` is only a default/test helper; it is not runtime policy.
- New manual/from-event intervals clamp to the window and return the top-level
  `422 outside_window` skip envelope when entirely outside. PATCH/reorder clamp
  only boundaries the client changed; AI and templates reject rather than clamp.
- `UserScheduleSettings.save()` calls `full_clean()` to enforce the five-minute
  grid. Do not use `update`, `bulk_create`, or `bulk_update` for it: those bypass
  Python validation (the DB check constraint protects ordering only).
