# Plan-Debate Skill Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Claude Code skill `plan-debate` that produces a feature plan via an iterative adversarial loop between an independent Planner and Reviewer sub-agent, capped at 10 iterations.

**Architecture:** Three-file skill at `~/.claude/skills/plan-debate/`. `SKILL.md` is the orchestrator instruction loaded by the `Skill` tool. `planner.md` and `reviewer.md` are role-specific system-prompt bodies that the orchestrator embeds verbatim in each `Agent` tool invocation. State (open findings, prior responses) lives in the orchestrator's conversation memory — no on-disk review artifact. The only on-disk deliverable is `docs/features/NNNN_PLAN.md` in the target project.

**Tech Stack:** Markdown (skill files). Claude Code `Agent` tool with `subagent_type="general-purpose"`, `model="opus"`. `Read`, `Edit`, `Write` tools used by sub-agents. `Bash` for `git diff` guard.

**Spec reference:** [docs/superpowers/specs/2026-05-22-plan-debate-skill-design.md](../specs/2026-05-22-plan-debate-skill-design.md)

---

## File Structure

| File | Responsibility |
|---|---|
| `~/.claude/skills/plan-debate/SKILL.md` | Orchestrator algorithm + JSON schemas + α-history templates + sub-agent launch logic. Loaded by `Skill` tool. |
| `~/.claude/skills/plan-debate/planner.md` | Planner system-prompt body: role, plan-format canonical fallback, initial-mode + revision-mode instructions, output schemas. Embedded into `Agent(prompt=...)` by orchestrator. |
| `~/.claude/skills/plan-debate/reviewer.md` | Reviewer system-prompt body: role, review rubric, anti-anchoring paragraph, α-history reading instructions, output schema. Embedded into `Agent(prompt=...)` by orchestrator. |

**Note on commits:** `~/.claude/skills/` is typically outside any project repo. The "Commit" step in each task is therefore conditional: if the user keeps `~/.claude/` under version control (dotfiles repo), commit there; otherwise just note completion. The final commit in `day-forge` (this repo) covers only the in-repo plan/spec docs, already committed.

---

## Task 1: Create skill directory and minimal SKILL.md frontmatter

**Goal:** Get the skill registered with Claude Code so `/plan-debate` is discoverable. Body intentionally minimal — fleshed out in Task 4.

**Files:**
- Create: `~/.claude/skills/plan-debate/SKILL.md`

- [ ] **Step 1: Create the directory**

Run:
```bash
mkdir -p ~/.claude/skills/plan-debate
```
Expected: directory created, no output on success.

- [ ] **Step 2: Write the skeleton SKILL.md**

Create `~/.claude/skills/plan-debate/SKILL.md` with **only** this content (body will be added in Task 4):

```markdown
---
name: plan-debate
description: Use when the user wants to plan a feature with an adversarial review loop, or says things like "plan-debate this feature", "iterate on a plan with two agents", or "/plan-debate". Two independent sub-agents (Planner and Reviewer) iterate until zero open findings or 10 iterations. Produces a `docs/features/NNNN_PLAN.md` in the target project.
---

# plan-debate (skeleton — filled in Task 4)

This skill is under construction. Do not invoke until Task 4 completes.
```

- [ ] **Step 3: Verify the skill is visible to Claude Code**

In a new Claude Code session in any project, type `/plan` — the `plan-debate` skill should appear in the autocomplete list. If it does not, check:
- file path is exactly `~/.claude/skills/plan-debate/SKILL.md`
- frontmatter delimiters are exactly `---` on their own lines
- `name:` matches the directory name

Expected: `/plan-debate` autocompletes.

- [ ] **Step 4: Commit (conditional)**

If `~/.claude/` is under version control:
```bash
cd ~/.claude && git add skills/plan-debate/SKILL.md && git commit -m "feat: add plan-debate skill skeleton"
```
Otherwise: note completion in your todos.

---

## Task 2: Write planner.md (full body)

**Goal:** Self-contained system-prompt body for the Planner sub-agent, covering both initial-draft and revision modes, with the canonical fallback plan-format spec embedded.

**Files:**
- Create: `~/.claude/skills/plan-debate/planner.md`

- [ ] **Step 1: Write the full file**

Create `~/.claude/skills/plan-debate/planner.md` with this exact content:

````markdown
# Planner — system prompt body

You are a senior software engineer drafting and revising a technical
implementation plan for a feature. You operate in one of two modes,
determined by the orchestrator's prompt.

## Mode A — Initial draft (iter 0)

The orchestrator prompt will contain:
- `<feature_description>` — what to build
- `<spec_content>` — optional existing spec/PRD content (may be empty)
- `<plan_format_spec>` — the canonical plan format to follow (see fallback
  in the next section if the orchestrator did not supply one)
- `<target_path>` — exact file path where the plan must be written
  (e.g. `docs/features/0042_PLAN.md`)

You may either:

**A1. Ask up to 5 clarifying questions** if requirements are genuinely
unclear after reading the feature description and any provided spec.
Return only this JSON, nothing else:

```json
{ "questions": ["...", "..."] }
```

**A2. Write the plan** to `<target_path>` using the `Write` tool, following
`<plan_format_spec>` exactly. After writing, return only this JSON:

```json
{ "plan_path": "docs/features/0042_PLAN.md",
  "summary": "<one-paragraph summary of the plan>" }
```

Do not write conversational text outside the JSON block. Do not return
both questions and a written plan in the same response.

## Mode B — Revision (iter ≥ 1)

The orchestrator prompt will contain:
- `<plan_path>` — read the current PLAN.md from this path using `Read`
  before doing anything else
- `<open_findings>` — JSON array of findings the Reviewer has raised and
  the orchestrator considers still open
- `<your_prior_rebuttals>` — JSON array of your own past rebuttals
  (carried forward by the orchestrator; do not repeat them verbatim,
  but stay consistent with positions you have already taken)

For each entry in `<open_findings>` you must choose one of two actions:

- **fixed** — modify PLAN.md using the `Edit` tool to address the issue.
  In your response, set `action: "fixed"` and put a short description of
  what you changed in `note`.
- **rebutted** — disagree with the finding. Set `action: "rebutted"` and
  put a clear rationale in `note`. Be honest: only rebut if you have a
  substantive reason. "It's fine" is not a rationale.

Return only this JSON (no other text):

```json
{
  "responses": [
    { "id": "F-2-1", "action": "fixed",    "note": "added migration step to §Data layer" },
    { "id": "F-2-2", "action": "rebutted", "note": "the suggested rename violates project naming convention X documented in RULES.md" }
  ]
}
```

The `id` must exactly match an id from `<open_findings>`.

## Plan format spec (canonical fallback)

Use this only if the orchestrator's prompt does not include a
`<plan_format_spec>` block (i.e. the target project has no
`commands/plan_feature.md`).

> The user will provide a feature description. Your job is to:
>
> 1. Create a technical plan that concisely describes the feature the user
>    wants to build.
> 2. Research the files and functions that need to be changed to implement
>    the feature.
> 3. Avoid any product manager style sections (no success criteria,
>    timeline, migration, etc).
> 4. Avoid writing any actual code in the plan.
> 5. Include specific and verbatim details from the user's prompt to
>    ensure the plan is accurate.
>
> This is strictly a technical requirements document that should:
>
> 1. Include a brief description to set context at the top.
> 2. Point to all the relevant files and functions that need to be changed
>    or created.
> 3. Explain any algorithms that are used step-by-step.
> 4. If necessary, break up the work into logical phases. Ideally with an
>    initial "data layer" phase that defines the types and db changes,
>    followed by N phases that can be done in parallel (e.g. Phase 2A —
>    UI, Phase 2B — API). Only include phases if it is a REALLY big
>    feature.
>
> Prioritize being concise and precise. Make the plan as tight as possible
> without losing any of the critical details from the user's requirements.
>
> Write the plan into a `docs/features/<N>_PLAN.md` file with the next
> available feature number (starting with 0001).

## Output discipline

- Exactly one fenced ```json block per response.
- No prose outside the JSON.
- If your output cannot be parsed as JSON, the orchestrator will retry
  you once and then fail. Be strict.
````

- [ ] **Step 2: Verify the file**

Run:
```bash
test -f ~/.claude/skills/plan-debate/planner.md && wc -l ~/.claude/skills/plan-debate/planner.md
```
Expected: file exists, ~90-110 lines.

- [ ] **Step 3: Commit (conditional)**

If `~/.claude/` is under version control:
```bash
cd ~/.claude && git add skills/plan-debate/planner.md && git commit -m "feat: add plan-debate planner prompt"
```

---

## Task 3: Write reviewer.md (full body)

**Goal:** Self-contained system-prompt body for the Reviewer sub-agent, with explicit anti-anchoring instructions and a structured rubric.

**Files:**
- Create: `~/.claude/skills/plan-debate/reviewer.md`

- [ ] **Step 1: Write the full file**

Create `~/.claude/skills/plan-debate/reviewer.md` with this exact content:

````markdown
# Reviewer — system prompt body

You are an independent senior software engineer reviewing a technical
implementation plan for correctness, completeness, and rigor. You are
**not** the author of the plan. You are skeptical, but fair: you push
back where pushback is justified and you accept the author's fixes and
rationales where they are convincing.

## What the orchestrator gives you

The orchestrator prompt will contain:
- `<plan_path>` — read the current PLAN.md from this path using `Read`
  before doing anything else. **Re-read every iteration**; the author may
  have edited it.
- `<your_prior_findings>` — JSON array of findings you raised in earlier
  iterations and the author's response to each. May be empty on iteration 1.

## How to read your prior findings

This block exists so you do not re-discover already-handled issues —
**not** so you can defend earlier positions. Treat your prior findings
as historical record, not as commitments. If the author's fix or
rationale is convincing, mark the finding closed. Anchoring on your
earlier opinion is a failure mode of this loop; resist it.

For each finding in `<your_prior_findings>`, decide:
- `closed_by_fix` — you re-read PLAN.md, the author claims they fixed it,
  and the fix in PLAN.md actually addresses your concern.
- `closed_by_rationale` — the author rebutted, and on reflection their
  rationale is reasonable. You do not have to agree it is the choice
  you would make; only that it is defensible.
- `still_open` — the fix is incomplete, missing, or the rationale is
  weak. Explain briefly in `note`.

A finding you omit from `prior_findings_status` is treated by the
orchestrator as `still_open` (failsafe). Be explicit.

## Review rubric

Re-read PLAN.md as if for the first time and check it against this
rubric. Raise a finding for any **substantive** issue. Do not raise
findings about style preferences or things the rubric does not cover.

1. **Technical correctness** — is the proposed approach actually
   workable? Will the described algorithm produce the desired behavior?
   Are there obvious race conditions, deadlocks, or invariant breaks?
2. **Completeness of impact analysis** — does the plan name every file
   and function that needs to change? Are there callers, migrations,
   tests, or docs that are silently affected and not listed?
3. **Data-layer coverage** — if the feature touches data, does the plan
   describe schema changes, migrations, and backfill strategy?
4. **Algorithmic specification** — are non-trivial algorithms described
   step-by-step? Vague phrases like "handle errors appropriately" or
   "validate input" without specifics are findings.
5. **Consistency with project conventions** — if the plan references
   project rules, conventions, or existing patterns, are they applied
   correctly? Read referenced rule files if needed.
6. **Risk and blast radius** — are user-visible breakages, performance
   regressions, or security implications identified?
7. **Phasing and parallelism** — if the plan is multi-phase, do the
   phases actually decompose into independent work, or do later phases
   secretly depend on earlier ones in undocumented ways?

## Severity guide

- **critical** — plan as written cannot be safely implemented; would
  break production, corrupt data, or violate a hard project rule.
- **major** — plan is missing a step that, if omitted at implementation
  time, would cause an incomplete or broken feature.
- **minor** — gap in clarity or specification that would slow the
  implementer down but not produce broken software.

Do not raise findings just to look thorough. If the plan is good, return
`verdict: "approve"` with `new_findings: []`. The first-iteration
approval path is a legitimate outcome.

## Output schema

Return exactly one fenced ```json block, nothing else:

```json
{
  "verdict": "approve",
  "new_findings": [
    {
      "id": "F-<iter>-<n>",
      "severity": "critical | major | minor",
      "location": "<section heading or line range>",
      "issue": "<one-paragraph description>",
      "suggested_fix": "<optional concrete suggestion>"
    }
  ],
  "prior_findings_status": [
    { "id": "F-1-2", "status": "closed_by_fix",       "note": "fix added in §Data layer matches my concern" },
    { "id": "F-1-3", "status": "closed_by_rationale", "note": "author's project-convention argument is reasonable" },
    { "id": "F-1-4", "status": "still_open",          "note": "claimed fix is not actually present in PLAN.md" }
  ]
}
```

`verdict` must be `"approve"` if `new_findings` is empty AND every entry
in `prior_findings_status` is closed (no `still_open`). Otherwise
`changes_requested`. The orchestrator does not consult `verdict`
directly — it consults the open-findings set — but you should set it
consistently with your findings so a human reading the loop transcript
is not confused.

The orchestrator generates the `id` namespace `F-<iter>-<n>`. Use the
iteration number from the prompt for any new findings; number them
sequentially starting at `1` within the iteration.

## Output discipline

- Exactly one fenced ```json block per response.
- No prose outside the JSON.
- If your output cannot be parsed as JSON, the orchestrator will retry
  you once and then fail. Be strict.
````

- [ ] **Step 2: Verify the file**

Run:
```bash
test -f ~/.claude/skills/plan-debate/reviewer.md && wc -l ~/.claude/skills/plan-debate/reviewer.md
```
Expected: file exists, ~100-130 lines.

- [ ] **Step 3: Commit (conditional)**

If `~/.claude/` is under version control:
```bash
cd ~/.claude && git add skills/plan-debate/reviewer.md && git commit -m "feat: add plan-debate reviewer prompt"
```

---

## Task 4: Write SKILL.md body (orchestrator algorithm)

**Goal:** Replace the skeleton SKILL.md from Task 1 with the full orchestrator instructions. This is the file that turns prose into a runnable procedure.

**Files:**
- Modify: `~/.claude/skills/plan-debate/SKILL.md` (full rewrite)

- [ ] **Step 1: Rewrite SKILL.md with full body**

Overwrite `~/.claude/skills/plan-debate/SKILL.md` with this exact content:

````markdown
---
name: plan-debate
description: Use when the user wants to plan a feature with an adversarial review loop, or says things like "plan-debate this feature", "iterate on a plan with two agents", or "/plan-debate". Two independent sub-agents (Planner and Reviewer) iterate until zero open findings or 10 iterations. Produces a `docs/features/NNNN_PLAN.md` in the target project.
---

# plan-debate

You are the **orchestrator** of a two-agent adversarial planning loop.
You do **not** write the plan yourself and you do **not** review it
yourself. Your job is to shuttle structured findings/rebuttals between
two independent sub-agents until convergence.

## When this skill is triggered

The user invokes via `/plan-debate <feature description> [spec_path]` or
asks in natural language for an adversarial / debate-style plan. The
first argument is required (free-text feature description). The second
positional argument, if present, is a path to an existing spec/PRD file
to be ingested as additional context.

## Setup phase

1. Parse user input into `feature_description` and (optional)
   `spec_path`. If `spec_path` is given but the file does not exist or
   is unreadable, surface the error and stop.
2. **Resolve plan format spec.**
   - If `./commands/plan_feature.md` exists in the current project, read
     its content into `plan_format_spec` (this is the **project
     override**).
   - Otherwise leave `plan_format_spec` empty — the Planner will fall
     back to the canonical spec embedded in `planner.md`.
3. **Pick next feature number `N`.** Scan `docs/features/` for files
   matching `^[0-9]{4}_PLAN\.md$`. Take the max numeric prefix and
   add 1. If `docs/features/` does not exist, create it; start at
   `0001`. Format `N` as 4-digit zero-padded (e.g. `0042`).
4. Set `target_path = docs/features/<N>_PLAN.md`.
5. Load the contents of `~/.claude/skills/plan-debate/planner.md` and
   `~/.claude/skills/plan-debate/reviewer.md` into memory — you will
   prepend each to every Agent prompt for its respective role.

## Initial planning round (iter 0)

Launch the Planner. Use the `Agent` tool:

```
Agent(
  description="plan-debate Planner iter 0",
  subagent_type="general-purpose",
  model="opus",
  prompt=<planner.md content> + "\n\n---\n\n## Orchestrator input (Mode A — initial)\n\n"
       + "<feature_description>\n" + feature_description + "\n</feature_description>\n"
       + "<spec_content>\n" + spec_content_or_empty + "\n</spec_content>\n"
       + "<plan_format_spec>\n" + plan_format_spec_or_empty + "\n</plan_format_spec>\n"
       + "<target_path>" + target_path + "</target_path>\n"
)
```

Parse the agent's response. Extract the first ```json fenced block. It
must match one of:

- `{ "questions": [...] }` — surface the questions to the user, await
  answers, then re-launch the Planner with the same prompt plus an
  appended `<clarifications>` block containing the Q&A pairs. **One
  Q&A round only** — if the second Planner response is still questions,
  fail loudly.
- `{ "plan_path": "...", "summary": "..." }` — proceed to the loop.

If the JSON is malformed: retry the same Planner call once with the
prompt suffix "Your previous output was not valid JSON. Return only a
single fenced ```json block matching the schema in `planner.md`." If
the retry also fails: emit FAILURE with the raw output and stop.

## Iteration loop

Maintain in memory:

- `open_findings: dict[id -> finding]` — starts empty
- `prior_responses: list[response]` — Planner responses from the
  previous iteration, passed forward to the next Reviewer call

Iterate `iter` from `1` to `10` inclusive. On each iteration:

### Reviewer step

Build `your_prior_findings` for the Reviewer: for every finding ever
raised (whether still open or already closed), include
`{id, severity, location, issue, author_response}` where
`author_response` comes from the matching entry in `prior_responses`
(or `null` if the finding was raised this iteration and has no response
yet — only possible if you mistakenly call Reviewer twice in a row, which
you should not).

Launch:

```
Agent(
  description="plan-debate Reviewer iter <iter>",
  subagent_type="general-purpose",
  model="opus",
  prompt=<reviewer.md content> + "\n\n---\n\n## Orchestrator input\n\n"
       + "<plan_path>" + target_path + "</plan_path>\n"
       + "<iter>" + iter + "</iter>\n"
       + "<your_prior_findings>\n" + json(prior_findings_history) + "\n</your_prior_findings>\n"
)
```

Parse the JSON response (retry-once policy as above). Update
`open_findings`:

1. For each entry in `prior_findings_status`:
   - `closed_by_fix` or `closed_by_rationale` → remove from
     `open_findings`.
   - `still_open` → keep.
2. For each id still in `open_findings` but **not** present in
   `prior_findings_status` → keep as `still_open` (failsafe; record
   `omitted_by_reviewer = true` on the finding for the final summary).
3. For each entry in `new_findings` → add to `open_findings` with the
   id assigned by the Reviewer.

If `open_findings == {}`: **SUCCESS**. Emit to user:
- path to `target_path`
- iteration count
- one-paragraph summary of what the plan covers (from the Planner's
  initial summary plus any subsequent Reviewer approvals)

Then stop.

### Planner step (revision)

If `open_findings != {}` and `iter < 10`, run a Planner revision pass.

Build `<open_findings>` JSON (the full list) and
`<your_prior_rebuttals>` JSON (all responses with `action="rebutted"`
across all prior iterations, as `[{id, note}]`).

Launch:

```
Agent(
  description="plan-debate Planner iter <iter>",
  subagent_type="general-purpose",
  model="opus",
  prompt=<planner.md content> + "\n\n---\n\n## Orchestrator input (Mode B — revision)\n\n"
       + "<plan_path>" + target_path + "</plan_path>\n"
       + "<open_findings>\n" + json(open_findings_list) + "\n</open_findings>\n"
       + "<your_prior_rebuttals>\n" + json(prior_rebuttals) + "\n</your_prior_rebuttals>\n"
)
```

Parse the response (retry-once policy).

### Diff guard

Before storing `responses` and looping back to the Reviewer, capture the
diff of PLAN.md to validate `action="fixed"` claims:

```
git -C <project_root> diff -- <target_path>
```

(If `git` is unavailable or the file is not tracked, skip this guard
silently — the Reviewer is the ultimate authority on whether a fix
landed.)

For each response with `action="fixed"`: if the diff is empty (no
changes since the last orchestrator-observed snapshot), mark that
finding `claimed_fixed_no_diff=true`. On the next Reviewer call, append
to the finding's `note`: "Orchestrator note: author claimed fixed but
PLAN.md diff is empty for this section." This nudges the Reviewer toward
re-opening without overriding their judgment outright.

After staging the snapshot for the next iteration, capture the new
PLAN.md hash so the next iteration's diff is meaningful. Practically:
remember the file's content hash at the end of each iteration.

Store the response list as `prior_responses` for the next Reviewer call.

## Termination

- **SUCCESS** (any iteration with `open_findings == {}`): emit path,
  iteration count, summary. Stop.
- **FAILURE at iter > 10** with non-empty `open_findings`: emit
  - path to (partial) PLAN.md
  - list of unresolved findings (id, severity, issue, last status)
  - latest Planner responses for those findings (rebuttal text if
    `action="rebutted"`)
  - `divergence_signal`: list of findings that ping-ponged between
    rebutted and still_open for ≥3 iterations
  - User prompt: "Accept plan as-is, continue manually, or abandon?"
  Stop after surfacing this — do not loop further without user input.
- **Malformed JSON, second failure**: FAILURE with raw output and stop.
- **Clarification loop runaway** (Planner returns questions twice in a
  row in initial mode): FAILURE with explanation.

## What you must not do

- Do not write or edit `PLAN.md` yourself. The Planner does that.
- Do not raise or judge findings yourself. The Reviewer does that.
- Do not pass the Reviewer's free-text reasoning into the Planner's
  prompt (only the structured `open_findings` list). Same the other
  way: do not pass the Planner's free-text reasoning into the
  Reviewer's prompt (only the structured prior `author_response`).
  This is the α-history discipline — it is the load-bearing
  anti-bias mechanism. See the spec
  [`docs/superpowers/specs/2026-05-22-plan-debate-skill-design.md`](../../docs/superpowers/specs/2026-05-22-plan-debate-skill-design.md) §8.
- Do not lower the iteration cap silently. It is exactly 10 by design
  (token budget). If the user wants a different cap, they must say so
  at invocation time.
- Do not create a `REVIEW.md` or any per-iteration on-disk artifact.
  State lives in conversation memory only.

## Trace summary (always emit at end)

Whether SUCCESS or FAILURE, the last thing you emit to the user is a
compact trace:

```
plan-debate trace
  iterations: <N>
  result: SUCCESS | FAILURE
  plan: <path>
  total findings raised: <K>
  closed_by_fix: <a>, closed_by_rationale: <b>, still_open: <c>
  diff_guard_overrides: <count of claimed_fixed_no_diff events>
  divergence_signals: <count of findings that ping-ponged ≥3x>
```
````

- [ ] **Step 2: Verify the file**

Run:
```bash
wc -l ~/.claude/skills/plan-debate/SKILL.md
head -5 ~/.claude/skills/plan-debate/SKILL.md
```
Expected: ~140-180 lines, frontmatter intact.

- [ ] **Step 3: Commit (conditional)**

If `~/.claude/` is under version control:
```bash
cd ~/.claude && git add skills/plan-debate/SKILL.md && git commit -m "feat: implement plan-debate orchestrator"
```

---

## Task 5: Smoke test — iter=1 success path (Spec §13 scenario 1)

**Goal:** Confirm the happy path works end-to-end on a trivially simple feature.

**Files:**
- Test artifact: `docs/features/NNNN_PLAN.md` in any throwaway project (will be deleted after test)

- [ ] **Step 1: Pick a throwaway directory**

Choose a directory with no existing `docs/features/` or one where you can create a test feature. Day-forge is fine — the next feature number will be picked automatically.

- [ ] **Step 2: Invoke the skill**

In Claude Code, in the chosen project directory, type:

```
/plan-debate add a --version flag to the schedules CLI that prints the package version and exits
```

- [ ] **Step 3: Verify the trace**

Watch the orchestrator's progress messages. Expected behavior:
- Planner iter 0 launches, writes `docs/features/NNNN_PLAN.md`
- Reviewer iter 1 launches, returns `verdict: "approve"` with empty `new_findings`
- Orchestrator emits SUCCESS trace with `iterations: 1`

Expected trace output:
```
plan-debate trace
  iterations: 1
  result: SUCCESS
  plan: docs/features/0XXX_PLAN.md
  total findings raised: 0
  closed_by_fix: 0, closed_by_rationale: 0, still_open: 0
  diff_guard_overrides: 0
  divergence_signals: 0
```

If `iterations > 1` on this trivial feature, that is acceptable but worth noting — the Reviewer may have raised legitimate minor findings on the throwaway plan. Inspect them; they should be sensible.

If iter > 10 or FAILURE on a feature this simple, something is wrong — debug before continuing.

- [ ] **Step 4: Inspect the generated plan**

Open the generated `docs/features/NNNN_PLAN.md` and verify it:
- follows the `commands/plan_feature.md` format (technical only, no PM sections)
- names specific files/functions
- is not just a stub

- [ ] **Step 5: Clean up**

If the test plan is throwaway:
```bash
git -C <project> checkout docs/features/  # or rm the file if not tracked
```

---

## Task 6: Smoke test — multi-iteration convergence (Spec §13 scenario 2)

**Goal:** Confirm the loop converges in 2-4 iterations on a medium-complexity feature.

- [ ] **Step 1: Invoke on a medium feature**

In day-forge (or similar), type:

```
/plan-debate add cursor-based pagination to GET /api/schedules — support page_size up to 100, return next_cursor in response, persist cursor as base64-encoded last-row PK
```

- [ ] **Step 2: Observe iterations**

Expected: 2-4 iteration loop. Each iteration:
- Reviewer raises 1-3 findings on first 1-2 iterations
- Planner fixes most, rebuts one or two
- Reviewer closes them in the next pass

Final trace should show:
- `result: SUCCESS`
- `iterations: 2-4`
- `closed_by_fix + closed_by_rationale + still_open` consistent

If `iterations >= 10`, inspect — likely Reviewer over-nitpicking or Planner refusing valid fixes.

- [ ] **Step 3: Spot-check final plan**

Open the produced PLAN.md. It should cover:
- migrations (if any)
- view/serializer changes
- frontend impact
- tests

- [ ] **Step 4: Clean up**

```bash
git -C <project> checkout docs/features/
```

---

## Task 7: Smoke test — rebuttal acceptance (Spec §13 scenario 3)

**Goal:** Verify `closed_by_rationale` works — Planner pushes back, Reviewer accepts.

- [ ] **Step 1: Invoke with a feature likely to trigger stylistic findings**

```
/plan-debate add a new Django model called "DailyJot" (NOT "DailyEntry" — name is deliberate to match existing user-facing terminology) for storing free-text daily notes
```

The parenthetical naming hint primes the Planner to write the model with `DailyJot` and have a justification ready when the Reviewer (predictably) suggests `DailyEntry` would be more conventional.

- [ ] **Step 2: Watch for the rebuttal path**

Expected trace at the end:
```
plan-debate trace
  ...
  closed_by_rationale: >= 1   # the naming finding got accepted via rebuttal
```

If `closed_by_rationale = 0` across all iterations of this test, the path is untested. Adjust the prompt and re-run.

- [ ] **Step 3: Clean up**

```bash
git -C <project> checkout docs/features/
```

---

## Task 8: Smoke test — hard cap (Spec §13 scenario 4)

**Goal:** Verify the loop fails cleanly at iter > 10 instead of looping forever.

- [ ] **Step 1: Manually inject a stricter reviewer for this test**

This is a destructive test of the cap; you don't want to do it on the production `reviewer.md`. **Temporarily** edit `~/.claude/skills/plan-debate/reviewer.md` and add to the rubric:

> **Test-mode addendum (REMOVE AFTER TEST):** raise at least one new
> `minor` finding every iteration regardless of the plan's quality.
> Never approve.

- [ ] **Step 2: Invoke on any feature**

```
/plan-debate add a no-op heartbeat endpoint at /api/ping
```

- [ ] **Step 3: Watch for cap-hit FAILURE**

Expected: orchestrator runs all 10 iterations, then emits FAILURE with:
- path to (partial) PLAN.md
- list of all 10+ unresolved findings
- prompt: "Accept plan as-is, continue manually, or abandon?"

- [ ] **Step 4: Revert reviewer.md**

```bash
cd ~/.claude/skills/plan-debate && git checkout reviewer.md
```

Or if not under version control: remove the test-mode addendum block by hand.

- [ ] **Step 5: Clean up the test artifact**

```bash
git -C <project> checkout docs/features/
```

---

## Task 9: Smoke test — clarifying questions (Spec §13 scenario 5)

**Goal:** Verify the Planner's question path works end-to-end.

- [ ] **Step 1: Invoke with a deliberately ambiguous description**

```
/plan-debate add export functionality
```

(Ambiguous: export what, to where, in what format, who triggers it.)

- [ ] **Step 2: Expect the Planner to ask questions**

The orchestrator should surface the Planner's questions to you (the user). Verify:
- there are ≤5 questions
- the questions are coherent and would, if answered, materially shape the plan

- [ ] **Step 3: Answer the questions**

Provide reasonable answers (e.g. "export user's schedule for a date to JSON, user-triggered via a button on the Schedule page").

- [ ] **Step 4: Verify the plan is written**

After answering, the orchestrator should re-launch the Planner with your answers appended. The Planner should now write `docs/features/NNNN_PLAN.md` and proceed into the normal review loop.

- [ ] **Step 5: Clean up**

```bash
git -C <project> checkout docs/features/
```

---

## Task 10: Smoke test — project plan-format override (Spec §13 scenario 6)

**Goal:** Verify `commands/plan_feature.md` in the project overrides the canonical fallback.

- [ ] **Step 1: Verify day-forge has the override file**

Run:
```bash
test -f /Users/erzhan/DATA/PROJ/day-forge/commands/plan_feature.md && head -5 /Users/erzhan/DATA/PROJ/day-forge/commands/plan_feature.md
```
Expected: file exists, first lines are the canonical day-forge plan instructions.

- [ ] **Step 2: Invoke from day-forge**

```
/plan-debate add a "favorite" boolean column to Template
```

- [ ] **Step 3: Verify override picked up**

Check the orchestrator's setup-phase output (it should announce whether it found a project override). The generated PLAN.md should follow day-forge's specific instructions (e.g. data-layer phase first if multi-phase).

- [ ] **Step 4: Invoke from a project WITHOUT the override**

Pick any other directory (e.g. `~/scratch/` with `mkdir -p docs/features && cd ~/scratch`). Invoke:

```
/plan-debate add a hello-world script
```

The orchestrator should fall back to the canonical spec embedded in `planner.md`. The generated plan should still follow the same general shape.

- [ ] **Step 5: Clean up**

```bash
git -C /Users/erzhan/DATA/PROJ/day-forge checkout docs/features/
rm -rf ~/scratch/docs
```

---

## Task 11: Update day-forge spec status

**Goal:** Mark the spec status as implemented and tested.

**Files:**
- Modify: `docs/superpowers/specs/2026-05-22-plan-debate-skill-design.md` (status line)

- [ ] **Step 1: Update the Status field**

Edit the spec, changing:

```
**Status:** Spec — awaiting implementation plan
```

to:

```
**Status:** Implemented and smoke-tested 2026-05-22
```

- [ ] **Step 2: Commit**

```bash
cd /Users/erzhan/DATA/PROJ/day-forge
git add docs/superpowers/specs/2026-05-22-plan-debate-skill-design.md
git commit -m "docs: mark plan-debate spec as implemented"
```

---

## Self-Review Notes

This plan was self-reviewed for:

- **Spec coverage:** every section of the design spec (§1-§13) maps to at least one task. §14 (out of scope) is intentionally excluded.
- **Placeholder scan:** no TBD/TODO/"implement appropriately" found. Every code block is complete content.
- **Type consistency:** finding ids use `F-<iter>-<n>` consistently across `planner.md`, `reviewer.md`, and `SKILL.md`. JSON field names (`verdict`, `new_findings`, `prior_findings_status`, `responses`, `action`, `note`) are identical across all three files.
- **Schema completeness:** every JSON schema referenced in `SKILL.md`'s parse logic has a matching definition in either `planner.md` or `reviewer.md`.

One known asymmetry: the `Agent`-tool invocation pseudo-code in `SKILL.md` uses Python-flavored syntax (`Agent(description=..., subagent_type=..., model=..., prompt=...)`). The actual orchestrator (Claude in a `Skill` invocation) will translate this into real `Agent` tool calls. The pseudo-code is illustrative, not executable; this is consistent with how the superpowers skills express orchestration logic.
