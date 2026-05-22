# plan-review-loop Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a global `~/.claude/skills/plan-review-loop/` skill that runs an adversarial Reviewer↔Planner loop over an **existing** plan file, mirroring `plan-debate` but skipping plan creation.

**Architecture:** Three markdown files — `SKILL.md` (orchestrator instructions), `reviewer.md` (verbatim copy of `plan-debate/reviewer.md`), `planner.md` (Mode-B-only adaptation of `plan-debate/planner.md`). Two independent sub-agents communicate exclusively through structured JSON. Reviewer runs first in iter 1 (plan already exists). 10-iteration cap. α-history anti-bias discipline preserved.

**Tech Stack:** Markdown skill files for Claude Code's `Skill` tool. Sub-agents launched via the `Agent` tool with `subagent_type="general-purpose"`, `model="opus"`. State held in orchestrator conversation memory only — no on-disk per-iteration artifacts.

**Spec:** `docs/superpowers/specs/2026-05-22-plan-review-loop-design.md`

---

## File Structure

```
~/.claude/skills/plan-review-loop/
├── SKILL.md       # orchestrator (~140 lines, derived from plan-debate/SKILL.md with planning phase removed)
├── reviewer.md    # ~158 lines, byte-for-byte copy of plan-debate/reviewer.md
└── planner.md     # ~75 lines, Mode B only — derived from plan-debate/planner.md
```

All three files live outside the day-forge git repo (they are global Claude Code skills). No project-side code or config changes.

---

## Task 1: Create skill directory and skeleton files

**Files:**
- Create: `~/.claude/skills/plan-review-loop/SKILL.md` (skeleton with frontmatter only)
- Create: `~/.claude/skills/plan-review-loop/reviewer.md` (empty placeholder)
- Create: `~/.claude/skills/plan-review-loop/planner.md` (empty placeholder)

- [ ] **Step 1: Create the directory**

Run: `mkdir -p ~/.claude/skills/plan-review-loop`

Expected: directory created, no output.

- [ ] **Step 2: Write SKILL.md skeleton with frontmatter**

Write to `~/.claude/skills/plan-review-loop/SKILL.md`:

```markdown
---
name: plan-review-loop
description: Use when the user has an existing plan file and wants to iterate on it with an adversarial review loop, or says things like "review-loop this plan", "iterate on this existing plan with two agents", or "/plan-review-loop". Two independent sub-agents (Reviewer first, then Planner) iterate until zero open findings or 10 iterations. Operates on a user-supplied existing `docs/features/NNNN_PLAN.md` (or any markdown plan path).
---

# plan-review-loop

(orchestrator instructions to follow in Task 4)
```

- [ ] **Step 3: Write planner.md and reviewer.md as empty placeholders**

Write `~/.claude/skills/plan-review-loop/reviewer.md` with single line:
```
(reviewer sub-agent prompt — populated in Task 2)
```

Write `~/.claude/skills/plan-review-loop/planner.md` with single line:
```
(planner sub-agent prompt — populated in Task 3)
```

- [ ] **Step 4: Verify the skill is discoverable**

Run: `ls -la ~/.claude/skills/plan-review-loop/`

Expected: three files visible (`SKILL.md`, `reviewer.md`, `planner.md`).

Run: `head -5 ~/.claude/skills/plan-review-loop/SKILL.md`

Expected: shows the YAML frontmatter with `name: plan-review-loop`.

- [ ] **Step 5: No git commit yet** — skill files live outside the day-forge repo; commit happens at the end of the day-forge-side spec-and-plan workflow, not per-task on the global skill files. Move on.

---

## Task 2: Populate `reviewer.md` (verbatim copy of plan-debate's reviewer)

**Files:**
- Modify: `~/.claude/skills/plan-review-loop/reviewer.md` (overwrite with full content)

The Reviewer sub-agent's contract is plan-shape-agnostic — it reviews whatever it is pointed at — so we copy `~/.claude/skills/plan-debate/reviewer.md` byte-for-byte.

- [ ] **Step 1: Copy the file**

Run:
```bash
cp ~/.claude/skills/plan-debate/reviewer.md ~/.claude/skills/plan-review-loop/reviewer.md
```

Expected: no output.

- [ ] **Step 2: Verify byte-for-byte equality**

Run:
```bash
diff ~/.claude/skills/plan-debate/reviewer.md ~/.claude/skills/plan-review-loop/reviewer.md
```

Expected: no output (files identical).

- [ ] **Step 3: Verify content sanity**

Run: `wc -l ~/.claude/skills/plan-review-loop/reviewer.md`

Expected: ~158 lines.

Run: `grep -c "Plan-missing protocol" ~/.claude/skills/plan-review-loop/reviewer.md`

Expected: `1` (the section exists — important for our use case since we want it to gracefully handle a missing plan path).

---

## Task 3: Write `planner.md` (Mode B only, Edit-only)

**Files:**
- Modify: `~/.claude/skills/plan-review-loop/planner.md` (overwrite with full content)

The Planner is reduced to Mode B only (revision). Mode A (initial creation) and the clarifying-questions sub-flow are removed. The Planner reads the existing plan via `Read` and mutates it via `Edit`. No `Write` tool.

- [ ] **Step 1: Overwrite planner.md with the full content below**

Write to `~/.claude/skills/plan-review-loop/planner.md`:

````markdown
# Planner — system prompt body

You are a senior software engineer revising a technical implementation
plan for a feature. The plan already exists on disk; your job is to
process structured findings from an independent Reviewer and either
**fix** the plan (using the `Edit` tool) or **rebut** a finding with a
substantive rationale. You do NOT create plans. You do NOT use the
`Write` tool.

## What the orchestrator gives you

The orchestrator prompt will contain:

- `<plan_path>` — read the current PLAN.md from this path using `Read`
  before doing anything else. Re-read every iteration; the file may have
  changed since your last response.
- `<open_findings>` — JSON array of findings the Reviewer has raised and
  the orchestrator considers still open. Each finding has at least
  `id`, `severity`, `location`, `issue`, and optional `suggested_fix`.
  Findings may also carry an `orchestrator_note` (e.g. "claimed fixed
  but PLAN.md diff is empty") — take those seriously.
- `<your_prior_rebuttals>` — JSON array of your own past rebuttals
  carried forward by the orchestrator. Stay consistent with positions
  you have already taken; do not flip-flop without acknowledging why.

## What you do

For each entry in `<open_findings>` you must choose one of two actions:

- **fixed** — modify PLAN.md using the `Edit` tool to address the issue.
  In your response, set `action: "fixed"` and put a short description
  of the actual change in `note` (e.g. "added migration step to §Data
  layer naming the column and default value"). Each fix must
  correspond to a real `Edit` tool call you executed in this turn —
  the orchestrator runs a `git diff` against the plan file after you
  return, and an `action: "fixed"` claim with an empty diff will be
  flagged for the Reviewer to re-open.
- **rebutted** — disagree with the finding. Set `action: "rebutted"`
  and put a clear, substantive rationale in `note`. Be honest: only
  rebut if you have a defensible reason ("it's fine" is not a
  rationale). The Reviewer may accept the rebuttal (`closed_by_rationale`)
  or reject it (`still_open`).

You may also leave a brief `edit_summary` field at the top level
describing what you changed across the file overall — useful when one
Edit call addresses multiple findings.

## Output schema

Return exactly one fenced ```json block (nothing else):

```json
{
  "edit_summary": "optional — overall description of edits applied this iteration",
  "responses": [
    { "id": "F-2-1", "action": "fixed",    "note": "added migration step to §Data layer" },
    { "id": "F-2-2", "action": "rebutted", "note": "the suggested rename violates project naming convention X documented in RULES.md" }
  ]
}
```

The `id` of each response must exactly match an id from `<open_findings>`.
Every open finding must have exactly one response — no skipping, no
extras.

## Tool usage rules

- ALWAYS call `Read` on `<plan_path>` first, every iteration.
- For every `action: "fixed"` response, call the `Edit` tool at least
  once on `<plan_path>` in the same turn before returning JSON.
- Never call `Write` — the file exists; `Edit` is the only correct tool.
- Do NOT touch any file other than `<plan_path>`.

## Output discipline (CRITICAL — read before responding)

Your entire response must be exactly one fenced ```json block. Nothing else.

- NO text before the JSON block (no "Here is my revision...", no
  preamble, no commentary about the codebase).
- NO text after the JSON block (no "Let me know if...", no summary).
- NO additional code blocks beyond the single JSON response.

If you want to convey context, put it inside the `note` or
`edit_summary` field — not as prose around the block.

The orchestrator extracts the first ```json block and discards
everything else. Any prose you write around it is silently dropped and
the user never sees it — so if it matters, put it in the JSON fields.

A response that is not a valid JSON-only payload will be retried once
with a re-prompt. A second malformed response causes the skill to FAIL
with the raw output shown to the user. Be strict.
````

- [ ] **Step 2: Verify the file was written correctly**

Run: `wc -l ~/.claude/skills/plan-review-loop/planner.md`

Expected: ~85 lines (roughly).

Run: `grep -c "Mode A" ~/.claude/skills/plan-review-loop/planner.md`

Expected: `0` (Mode A is removed).

Run: `grep -c "Write" ~/.claude/skills/plan-review-loop/planner.md`

Expected: at least `2` (occurrences are in negative form: "you do NOT use the `Write` tool" and "Never call `Write`"). If 0, the prohibition language is missing.

Run: `grep -c '```json' ~/.claude/skills/plan-review-loop/planner.md`

Expected: `1` (one schema example block).

---

## Task 4: Write `SKILL.md` (orchestrator)

**Files:**
- Modify: `~/.claude/skills/plan-review-loop/SKILL.md` (overwrite with full orchestrator instructions)

- [ ] **Step 1: Overwrite SKILL.md with the full content below**

Write to `~/.claude/skills/plan-review-loop/SKILL.md`:

````markdown
---
name: plan-review-loop
description: Use when the user has an existing plan file and wants to iterate on it with an adversarial review loop, or says things like "review-loop this plan", "iterate on this existing plan with two agents", or "/plan-review-loop". Two independent sub-agents (Reviewer first, then Planner) iterate until zero open findings or 10 iterations. Operates on a user-supplied existing `docs/features/NNNN_PLAN.md` (or any markdown plan path).
---

# plan-review-loop

You are the **orchestrator** of a two-agent adversarial review loop
over an EXISTING plan file. You do **not** edit the plan yourself and
you do **not** review it yourself. Your job is to shuttle structured
findings/rebuttals between two independent sub-agents until convergence
(zero open findings) or the 10-iteration cap.

This skill is the mirror of `plan-debate` for the case where the plan
already exists. Differences:

- No file creation. The plan path comes from the user.
- No clarifying-questions flow. Ambiguity is a finding for the
  Reviewer to raise, not a question for the user.
- Iter 1 runs the Reviewer first (the Planner has nothing to do until
  there are findings).
- Planner uses `Edit` only — never `Write`.

## When this skill is triggered

The user invokes via `/plan-review-loop <path-to-PLAN.md>` or asks in
natural language to iterate on an existing plan with an adversarial
review loop. The single positional argument is required: the path to
an existing markdown plan file (absolute or relative to CWD).

## Setup phase

1. Parse `plan_path` from the user invocation. If empty, emit FAILURE:
   "Usage: /plan-review-loop <path-to-PLAN.md>. The plan file must
   already exist; use /plan-debate to create one from scratch."
2. Run `test -f <plan_path>`. If the file does not exist, emit FAILURE
   with the path and the same usage hint. Stop — do not launch any
   agents.
3. Run `wc -l <plan_path>`. If fewer than 10 lines, emit a warning
   ("plan looks suspiciously short at N lines — proceeding anyway")
   but do not block. The Reviewer's plan-missing protocol will surface
   stub-file cases as a critical finding.
4. **Resolve plan format spec.**
   - If `./commands/plan_feature.md` exists in the current project
     (relative to the orchestrator's CWD), read its content into
     `plan_format_spec`. The Reviewer uses this to judge plan shape.
   - Otherwise leave `plan_format_spec` empty — the Reviewer falls
     back to the canonical rubric embedded in `reviewer.md`.
5. Load the contents of `~/.claude/skills/plan-review-loop/reviewer.md`
   and `~/.claude/skills/plan-review-loop/planner.md` into memory — you
   prepend each to every Agent prompt for its respective role.
6. Capture the initial content hash of `<plan_path>` as `plan_hash` for
   the diff guard later. (Use `git diff --quiet <plan_path>` if the
   file is git-tracked; otherwise compute via the `Bash` tool.)

## Iteration loop

Maintain in orchestrator memory:

- `open_findings: dict[id -> finding]` — starts empty.
- `prior_responses: list[response]` — Planner responses from the
  previous iteration; passed forward to the next Reviewer call.
- `prior_findings_history: list[finding-with-status]` — every finding
  ever raised plus current status and the Planner's response.
- `plan_hash` — content hash from the last orchestrator-observed
  snapshot of `<plan_path>`. Used by the diff guard.

Iterate `iter` from `1` to `10` inclusive.

### Step A — Reviewer (always runs first, every iteration)

Build `your_prior_findings` for the Reviewer: for every finding ever
raised, include `{id, severity, location, issue, author_response}`
where `author_response` comes from the matching entry in
`prior_responses` (or `null` if the finding was raised this iteration
and has no response yet — only possible if you mistakenly call Reviewer
twice in a row, which you should not).

On iter 1, `your_prior_findings = []`.

Launch:

```
Agent(
  description="plan-review-loop Reviewer iter <iter>",
  subagent_type="general-purpose",
  model="opus",
  prompt=<reviewer.md content> + "\n\n---\n\n## Orchestrator input\n\n"
       + "<plan_path>" + plan_path + "</plan_path>\n"
       + "<iter>" + iter + "</iter>\n"
       + "<your_prior_findings>\n" + json(prior_findings_history) + "\n</your_prior_findings>\n"
)
```

Parse the JSON response (extract first ```json block). Retry once on
malformed JSON with the suffix "Your previous output was not valid
JSON. Return only a single fenced ```json block matching the schema in
`reviewer.md`." A second malformed response → FAILURE with raw output.

Update `open_findings`:

1. For each entry in `prior_findings_status`:
   - `closed_by_fix` or `closed_by_rationale` → remove from
     `open_findings`.
   - `still_open` → keep.
2. For each id still in `open_findings` but **not** present in
   `prior_findings_status` → keep, mark `omitted_by_reviewer=true`
   (failsafe).
3. For each entry in `new_findings` → add to `open_findings` with the
   id assigned by the Reviewer.

If `open_findings == {}` after the update → **SUCCESS**. Emit:
- path to `<plan_path>`
- iteration count
- one-paragraph summary synthesised from the Reviewer's
  approval rationales across iterations
- the trace summary (see § Trace summary)

Then stop.

### Step B — Planner (revision)

Only runs if `open_findings != {}` AND `iter < 10`.

Build `<open_findings>` JSON (the full open list, including any
orchestrator notes about empty-diff "fixed" claims) and
`<your_prior_rebuttals>` JSON (all Planner responses with
`action="rebutted"` across all prior iterations, as `[{id, note}]`).

Launch:

```
Agent(
  description="plan-review-loop Planner iter <iter>",
  subagent_type="general-purpose",
  model="opus",
  prompt=<planner.md content> + "\n\n---\n\n## Orchestrator input\n\n"
       + "<plan_path>" + plan_path + "</plan_path>\n"
       + "<open_findings>\n" + json(open_findings_list) + "\n</open_findings>\n"
       + "<your_prior_rebuttals>\n" + json(prior_rebuttals) + "\n</your_prior_rebuttals>\n"
)
```

Parse the response (retry-once policy as above). Each response has
`id`, `action ∈ {"fixed","rebutted"}`, `note`, optional `edit_summary`.

### Step C — Diff guard

Before storing `responses` and looping back to the Reviewer, capture
the diff of the plan file to validate `action="fixed"` claims:

```
git -C <project_root> diff -- <plan_path>
```

(If `git` is unavailable or the file is not tracked, skip this guard
silently — the Reviewer is the ultimate authority on whether a fix
landed.)

For each response with `action="fixed"`: if the diff against the
previous `plan_hash` is empty, mark that finding
`claimed_fixed_no_diff=true`. On the next Reviewer call, append to
that finding's `note`: "Orchestrator note: author claimed fixed but
PLAN.md diff is empty for this section." This nudges the Reviewer
toward re-opening without overriding their judgment.

After the diff check, update `plan_hash` to the file's new content
hash so the next iteration's diff is meaningful. Store the response
list as `prior_responses` for the next Reviewer call.

## Termination

- **SUCCESS** — any iteration where `open_findings == {}` after the
  Reviewer step. Emit path, iter count, summary, and trace. Stop.
- **FAILURE at iter > 10** with non-empty `open_findings`:
  - path to `<plan_path>` (mutated in place; user can revert via `git
    checkout -- <path>` if tracked)
  - list of unresolved findings (`id`, `severity`, `issue`, last
    status)
  - latest Planner rebuttal text for each `still_open + rebutted`
    finding
  - `divergence_signal`: list of findings that ping-ponged between
    `rebutted` and `still_open` for ≥3 iterations
  - User prompt: "Accept plan as-is, continue manually, or revert via
    git?"
  - Trace summary.
  Stop after surfacing this — do not loop further without user input.
- **Malformed JSON, second failure (either agent)** — FAILURE with raw
  output. Stop.
- **Missing plan file at setup** — FAILURE before any agent launch
  (see Setup step 2). Stop.

## What you must not do

- Do not edit `<plan_path>` yourself. The Planner does that.
- Do not raise or judge findings yourself. The Reviewer does that.
- Do not pass the Reviewer's free-text reasoning into the Planner's
  prompt (only the structured `open_findings` list). Same the other
  way: do not pass the Planner's free-text reasoning into the
  Reviewer's prompt (only the structured prior `author_response`).
  This is the α-history discipline — it is the load-bearing
  anti-bias mechanism.
- Do not lower the iteration cap silently. It is exactly 10 by design
  (token budget). If the user wants a different cap, they must say so
  at invocation time.
- Do not create a `REVIEW.md` or any per-iteration on-disk artifact.
  State lives in conversation memory only.
- Do not call the Planner in iteration 1 if the Reviewer returned zero
  findings — that is the legitimate SUCCESS-in-iter-1 path.

## Trace summary (always emit at end)

Whether SUCCESS or FAILURE, the last thing you emit to the user is a
compact trace:

```
plan-review-loop trace
  iterations: <N>
  result: SUCCESS | FAILURE
  plan: <path>
  total findings raised: <K>
  closed_by_fix: <a>, closed_by_rationale: <b>, still_open: <c>
  diff_guard_overrides: <count of claimed_fixed_no_diff events>
  divergence_signals: <count of findings that ping-ponged ≥3x>
```
````

- [ ] **Step 2: Verify SKILL.md content sanity**

Run: `wc -l ~/.claude/skills/plan-review-loop/SKILL.md`

Expected: 200–250 lines.

Run: `head -5 ~/.claude/skills/plan-review-loop/SKILL.md`

Expected: shows YAML frontmatter with `name: plan-review-loop`.

Run: `grep -c "Mode A" ~/.claude/skills/plan-review-loop/SKILL.md`

Expected: `0` (no Mode A references — only Mode B / revision exists).

Run: `grep -c "Reviewer (always runs first" ~/.claude/skills/plan-review-loop/SKILL.md`

Expected: `1`.

---

## Task 5: Smoke test T4 — missing plan file

**Files:**
- Test only: none modified.

Verify the early-FAILURE path triggers before any agent is launched.

- [ ] **Step 1: Restart Claude Code session (or use a fresh session) so the new skill is loaded.**

The user must do this manually — skill discovery happens at session start. Confirm in the next session that `/plan-review-loop` appears in the available skills list.

- [ ] **Step 2: Invoke the skill with a path that does not exist**

In Claude Code, run: `/plan-review-loop /tmp/does-not-exist-9999.md`

Expected behavior:
- Orchestrator runs `test -f /tmp/does-not-exist-9999.md` → fails.
- Orchestrator emits FAILURE with the usage hint message ("Plan file does not exist… use /plan-debate to create one from scratch").
- NO `Agent` tool call is made (verified by checking the session transcript).
- Trace summary shows `iterations: 0, result: FAILURE`.

- [ ] **Step 3: Record observed behavior**

If the orchestrator launches an Agent anyway, that's a bug in `SKILL.md` Setup step 2 — fix and re-test before proceeding to Task 6.

---

## Task 6: Smoke test T1 — clean plan (SUCCESS in iter 1)

**Files:**
- Create (temporary): `/tmp/plan-review-loop-T1-clean.md` — a deliberately well-formed plan that should pass on first review.

- [ ] **Step 1: Author a clean test plan**

Write to `/tmp/plan-review-loop-T1-clean.md`:

```markdown
# Add --version flag to schedules CLI

## Goal
Print the installed day-forge backend version string when the user
runs `python manage.py schedules --version`. Exit code 0, no other
side effects.

## Files changed
- `backend/schedules/management/commands/schedules.py` — add `--version`
  argparse argument; if set, print the version string and call
  `sys.exit(0)` before any other command logic runs.
- `backend/tests/test_schedules_command.py` — add one test that invokes
  the command with `--version` and asserts the stdout matches the
  version string read from `pyproject.toml`.

## Algorithm
1. Read `version` from the project's `pyproject.toml` at module import
   time (cache in a module-level constant).
2. In `Command.add_arguments`, add `parser.add_argument("--version",
   action="store_true")`.
3. In `Command.handle`, if `options["version"]` is truthy, print the
   cached version and return immediately (Django swallows the return
   value; explicit `sys.exit(0)` is not required because no other code
   runs).

## Risk
None — pure additive change behind a CLI flag that defaults to off.
Existing call sites are unaffected.

## Test
- `uv run pytest backend/tests/test_schedules_command.py::test_version_flag -v`
```

- [ ] **Step 2: Invoke the skill**

In Claude Code, run: `/plan-review-loop /tmp/plan-review-loop-T1-clean.md`

Expected behavior:
- Setup completes: file exists, `wc -l` ~30 lines (no warning).
- Reviewer launched (iter 1) with `your_prior_findings = []`.
- Reviewer returns `verdict: "approve"` with `new_findings: []`.
- Orchestrator detects `open_findings == {}` → SUCCESS.
- Planner is NOT launched at all.
- Trace shows `iterations: 1, result: SUCCESS, total findings raised: 0`.

- [ ] **Step 3: If Reviewer raises findings, inspect them**

If the Reviewer raises legitimate findings on this plan, the plan was
not as clean as intended — either tighten the plan content or accept
that the loop converges in 2–3 iterations. Re-run T1 only if zero-iter
convergence is necessary to validate the iter-1 success path; otherwise
treat T2 (Task 7) as covering the multi-iteration path.

- [ ] **Step 4: Clean up**

Run: `rm /tmp/plan-review-loop-T1-clean.md`

---

## Task 7: Smoke test T2 — flawed plan (converge in 2–4 iterations)

**Files:**
- Create (temporary): `/tmp/plan-review-loop-T2-flawed.md` — a deliberately incomplete plan that should trigger 2–4 findings and converge after Planner fixes.

- [ ] **Step 1: Author a flawed test plan**

Write to `/tmp/plan-review-loop-T2-flawed.md`:

```markdown
# Add user export endpoint

## Goal
Let users export their data as JSON.

## Files
- Add a new endpoint.

## Tests
Write some tests.
```

This plan is intentionally vague (no file paths, no algorithm, no
risk analysis, no specific test names, no schema description). The
Reviewer should raise at least 3 findings (severity major or critical):
algorithmic specification, completeness of impact analysis, vague
test rubric.

- [ ] **Step 2: Invoke the skill**

In Claude Code, run: `/plan-review-loop /tmp/plan-review-loop-T2-flawed.md`

Expected behavior:
- Setup completes (warning emitted because file is < 10 lines, but
  loop proceeds).
- Reviewer iter 1 returns 3+ findings.
- Planner iter 1 either fixes (via `Edit`) or rebuts each. Most
  should be fixed — the plan really is deficient.
- After diff guard, Reviewer iter 2 either closes all findings
  (SUCCESS in iter 2) or raises a follow-up.
- Convergence by iter 4 at the latest. Trace: `iterations: 2–4,
  result: SUCCESS`.

- [ ] **Step 3: Inspect the mutated plan**

Run: `cat /tmp/plan-review-loop-T2-flawed.md`

Expected: substantially expanded plan with concrete file paths,
algorithm steps, and test names. (Exact content varies — the Planner
sub-agent decides; we are only verifying the loop functions.)

- [ ] **Step 4: Clean up**

Run: `rm /tmp/plan-review-loop-T2-flawed.md`

---

## Task 8: Final verification — skill end-to-end ready

- [ ] **Step 1: Confirm all three skill files are non-empty and current**

Run:
```bash
ls -la ~/.claude/skills/plan-review-loop/
wc -l ~/.claude/skills/plan-review-loop/*.md
```

Expected:
- `SKILL.md` 200–250 lines
- `reviewer.md` ~158 lines (matches plan-debate/reviewer.md)
- `planner.md` ~85 lines

- [ ] **Step 2: Confirm the description triggers correctly**

Run: `head -5 ~/.claude/skills/plan-review-loop/SKILL.md`

Expected: description includes phrases "`/plan-review-loop`", "existing
plan file", "two independent sub-agents". These are the trigger
keywords the model will see at skill-selection time.

- [ ] **Step 3: Confirm `cp` for reviewer.md still matches source**

Run: `diff ~/.claude/skills/plan-debate/reviewer.md ~/.claude/skills/plan-review-loop/reviewer.md`

Expected: no output. (If plan-debate's reviewer.md was edited in
parallel with this work, re-sync via `cp` and note in commit.)

- [ ] **Step 4: Mark plan complete**

The skill is ready for production use. No further code or doc changes
required on the day-forge side — the implementation plan and design
spec already live in `docs/superpowers/`.

Optional follow-up (not part of this plan): if a future plan-debate
reviewer.md improvement should propagate, document the manual re-sync
step in a top-level skill README or convert the file to a symlink.
This is intentionally deferred — see § Risks in the design spec.

---

## Self-Review Notes

- **Spec coverage:** every section of the design spec maps to a task —
  command interface (Task 5 invocation), file layout (Task 1), Setup
  phase (Task 4 SKILL.md content), iteration loop with Reviewer→Planner
  order (Task 4 + Task 6/7 smoke tests), anti-bias α-history (Task 4
  "What you must not do" section), diff guard (Task 4 Step C), Reviewer
  prompt (Task 2 verbatim copy), Planner prompt (Task 3 Mode-B-only
  rewrite), termination paths (Task 4 Termination section + Task 5/7
  smoke tests), risks/non-goals (covered by the planner.md "Never call
  Write" guardrail and the SKILL.md "What you must not do" list).
- **Placeholder scan:** no TBD/TODO. Code blocks contain full content
  to paste. File paths are absolute (`~/.claude/skills/plan-review-loop/…`)
  or explicit `/tmp/…` test paths. Verification commands have expected
  output.
- **Type consistency:** the JSON schemas across `SKILL.md`,
  `reviewer.md`, and `planner.md` align — `id`, `severity`, `location`,
  `issue`, `suggested_fix`, `note`, `action`, `verdict`, `new_findings`,
  `prior_findings_status` are used consistently with `plan-debate`'s
  conventions.
