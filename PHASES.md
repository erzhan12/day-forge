# Day-Forge — Implementation Phases

Derived from `day_forge_prd.md`. Each phase is self-contained and results in a working, testable state.

---

## Phase 1: Project Scaffold & Data Layer

**Goal:** Django project running in Docker with database models, admin access, and dev tooling — no frontend yet.

### Functionality
- Django 5.x project with `uv`, Python 3.14, ruff, pytest
- SQLite database with WAL mode
- Models: `Schedule`, `TimeBlock`, `Template`, `Rule`, `AIInteraction`, `DailyReview`
- Django admin registered for all models (useful for manual data inspection throughout development)
- Django built-in auth (single user, username + password)
- `Dockerfile` + `docker-compose.yml` for local dev (hot-reload, volume-mounted DB)
- Seed command: create default weekday/weekend templates with sample blocks

### Milestone
- `docker compose up` starts Django on :8000
- Admin panel at `/admin/` shows all models
- `uv run pytest` passes with model unit tests
- Can create a schedule with time blocks via admin

### Files created
```
backend/
├── day_forge/             # Django project (settings, urls, wsgi, asgi)
├── schedules/             # App: Schedule, TimeBlock models + admin
├── templates_mgr/         # App: Template, Rule models + admin
├── analytics/             # App: DailyReview model + admin
├── ai/                    # App: AIInteraction model + admin (empty service layer)
├── manage.py
docker-compose.yml
Dockerfile
pyproject.toml             # updated with Django, ruff, pytest deps
```

---

## Phase 2: Frontend Foundation (Inertia + Vue 3)

**Goal:** Vue 3 frontend connected to Django via Inertia.js. Daily schedule page renders time blocks as a flat list. Manual CRUD works.

### Functionality
- Inertia.js Django adapter wired into Django views
- Vue 3 + TypeScript + Vite setup in `frontend/`
- Login page (Django auth, Inertia redirect)
- Daily schedule page (`/schedule/{date}/`)
  - Date navigator in top bar (‹ Today ›)
  - Flat list of time blocks with time badges, category color bars, duration indicators
  - Inline title editing (click to edit, blur/Enter to save)
  - Checkbox for completion tracking (PATCH to backend)
  - Add block button/form (title, start time, end time, category)
  - Delete block (with confirmation)
- Gap rendering: empty slots between blocks showing free time duration, clickable to add
- Current time "now line" with auto-scroll and per-minute update

### Milestone
- Navigate between dates, see time blocks rendered
- Add, edit title inline, check off, and delete time blocks — all persisted
- Gaps display correctly between blocks
- Now line visible on today's schedule

### Files created
```
frontend/
├── src/
│   ├── pages/
│   │   ├── Schedule.vue       # Main daily schedule page
│   │   ├── Login.vue          # Auth page
│   │   └── Settings.vue       # Placeholder
│   ├── components/
│   │   ├── TimeBlock.vue      # Single block (badge, color, checkbox, title)
│   │   ├── GapSlot.vue        # Empty time gap display
│   │   ├── DateNavigator.vue  # ‹ Today › bar
│   │   ├── NowLine.vue        # Current time indicator
│   │   └── AddBlockForm.vue   # Quick-add form
│   ├── composables/
│   │   └── useSchedule.ts     # Schedule state & API calls
│   ├── types/
│   │   └── index.ts           # TimeBlock, Schedule interfaces
│   ├── app.ts
│   └── app.css
├── package.json
├── vite.config.ts
└── tsconfig.json
backend/
├── schedules/views.py         # Inertia views for schedule page
├── schedules/urls.py          # URL routing
└── day_forge/settings.py      # Updated: Inertia, static files, Vite
```

---

## Phase 3: Drag-and-Drop & Undo

**Goal:** Time blocks are reorderable via drag-and-drop with automatic conflict resolution. Undo system covers all modifications.

### Functionality
- Drag handle on left edge of each time block
- During drag: ghost element with real-time time badge preview
- On drop: if overlap, subsequent blocks auto-shift forward
- 5-minute snap-to-grid
- Smooth slide animation for shifted blocks (200ms ease)
- Batch reorder API endpoint (`POST /api/blocks/reorder/`)
- Undo stack (in-memory, last 20 actions):
  - Covers: drag-and-drop, inline edits, checkbox toggles, add/delete
  - Ctrl+Z keyboard shortcut
  - Toast notification: "Moved {task} to {time} — Undo" (auto-dismiss 8s)

### Milestone
- Drag a block to new time, overlapping blocks shift automatically
- Time badges update during drag preview
- Ctrl+Z undoes last action, toast shows with clickable undo
- 3+ consecutive undos work correctly

### Files created/modified
```
frontend/src/
├── composables/
│   ├── useDrag.ts             # Drag-and-drop logic, snap-to-grid, conflict resolution
│   └── useUndo.ts             # Undo stack, keyboard shortcut, toast trigger
├── components/
│   ├── TimeBlock.vue          # Modified: drag handle, ghost preview
│   └── UndoToast.vue          # Floating undo notification
backend/
├── schedules/api.py           # /api/blocks/reorder/ endpoint
```

---

## Phase 4: AI Command Bar

**Goal:** Natural language command bar powered by OpenAI. User types commands to add, move, remove, or resize tasks. Bilingual (EN + RU).

### Functionality
- Command bar UI: fixed bottom bar, terminal-style, full-width text input
- Processing spinner while AI responds
- OpenAI service layer:
  - Configurable model (`gpt-4o-mini` for commands, `gpt-4o` for drafts)
  - System prompt with structured JSON output schema
  - Context: current schedule, active template, user rules, current time
  - Bilingual parsing (English + Russian)
- Action types: `add`, `move`, `remove`, `resize`
- Backend validates AI response against schema, applies changes atomically
- Error handling: friendly message if command not understood, fallback if API down
- AI interaction logging to `ai_interactions` table
- API health indicator in command bar
- Each AI modification pushes to undo stack

### Milestone
- Type "add standup at 10:00 for 15 min" → block appears
- Type "move gym to 18:00" → block moves, subsequent blocks shift if needed
- Type "добавь звонок в 10 на 30 минут" → block appears with correct time
- Undo works on AI-applied changes
- Failed commands show helpful error message
- All interactions logged in DB

### Files created/modified
```
backend/
├── ai/
│   ├── service.py             # OpenAI client, prompt builder, response parser
│   ├── prompts.py             # System prompt, context formatter
│   ├── schemas.py             # Pydantic models for AI request/response
│   └── views.py               # /api/ai/command/ endpoint
frontend/src/
├── components/
│   └── CommandBar.vue         # Bottom command bar with input, spinner, status
├── composables/
│   └── useAI.ts               # AI command submission, error handling
```

---

## Phase 5: Templates, Rules & Draft Generation

**Goal:** AI generates morning schedule drafts from templates + history. User manages templates and rules through settings UI.

### Functionality
- Settings page with two sections:
  - **Templates**: weekday/weekend template editor (same drag-and-drop UI as daily schedule)
  - **Rules**: list of natural language rules with toggle (active/inactive) and priority ordering
- Draft generation (`POST /api/ai/generate-draft/`):
  - Triggered automatically when opening a day with no schedule, or manually via button
  - AI context: selected template (weekday/weekend based on day), last 7 days of schedules, active rules, current time
  - Returns full schedule as structured JSON
  - Draft appears with "draft" status badge, user can accept/modify
- Schedule status flow: `draft` → `active` (on first edit or explicit accept) → `reviewed` (after end-of-day review)

### Milestone
- Edit weekday template in settings, see it reflected in next day's draft
- Add rule "Never schedule meetings before 9:00", draft respects it
- Open a new day → AI draft auto-generates based on template + recent history
- Draft badge visible, clears on first interaction

### Files created/modified
```
frontend/src/
├── pages/
│   └── Settings.vue           # Template editor + rules manager
├── components/
│   ├── TemplateEditor.vue     # Reuses TimeBlock + drag for template editing
│   ├── RulesList.vue          # Rules with toggle, priority drag, add/delete
│   └── DraftBadge.vue         # Visual indicator for draft status
backend/
├── templates_mgr/views.py     # Settings page views, template/rule CRUD
├── ai/service.py              # Modified: draft generation with template + history context
├── ai/prompts.py              # Modified: template/rules/history context injection
├── schedules/views.py         # Modified: auto-generate draft on empty day
```

---

## Phase 6: Analytics & End-of-Day Review

**Goal:** Daily review panel with completion stats, category breakdown, and streak tracking.

### Functionality
- Review panel (accessible from past days or manually for today):
  - Completion rate: X/Y tasks (percentage bar)
  - Time planned vs. completed: total hours comparison
  - Category breakdown: horizontal bars showing time distribution (work/personal/health/other)
  - Skipped tasks list
  - Optional user notes text field
- Streak counter: consecutive days with >80% completion
- `DailyReview` record auto-generated when navigating away from a past day, or on manual trigger
- Analytics data injected into AI context for draft quality improvement
- Analytics page at `/analytics/{date}/`

### Milestone
- Complete some tasks, skip others → review panel shows accurate stats
- Category breakdown reflects actual time distribution
- Streak counter increments on qualifying days
- AI drafts improve after a week of review data (qualitative check)

### Files created/modified
```
frontend/src/
├── pages/
│   └── Analytics.vue          # Daily review page
├── components/
│   ├── CompletionBar.vue      # Percentage bar for completion rate
│   ├── CategoryBreakdown.vue  # Horizontal bars by category
│   ├── StreakCounter.vue       # Consecutive days display
│   └── SkippedTasks.vue       # List of uncompleted tasks
backend/
├── analytics/
│   ├── views.py               # Analytics page view, review generation
│   └── services.py            # Stats calculation, streak logic
├── ai/prompts.py              # Modified: include review data in AI context
```

---

## Phase 7: Persistent Undo & Production Deployment

**Goal:** Undo survives page reloads. App deployed to VPS with Docker, HTTPS, and backups.

### Functionality
- `schedule_snapshots` table: stores schedule state on every modification
- On page load: restore undo stack from snapshots (last 20 per schedule)
- Cross-session undo: reload page, Ctrl+Z still works
- Snapshot cleanup: keep only last 50 per schedule, cron or management command
- Docker production setup:
  - Multi-stage Dockerfile (builder → slim runtime)
  - `docker-compose.prod.yml` with Caddy reverse proxy (auto HTTPS)
  - SQLite volume mount for persistence
  - `.env` based configuration
  - Backup script: daily SQLite file copy to backup volume
- GitHub Actions CI: lint + test on push

### Milestone
- Make changes, reload page, Ctrl+Z restores previous state
- `docker compose -f docker-compose.prod.yml up` runs on VPS with HTTPS
- Backup script runs, produces recoverable DB copy
- CI pipeline passes on push to main

### Files created/modified
```
backend/
├── schedules/models.py        # Modified: ScheduleSnapshot model
├── schedules/api.py           # Modified: snapshot creation on mutations
docker-compose.prod.yml
Dockerfile                     # Modified: multi-stage production build
caddy/Caddyfile
scripts/backup.sh
.github/workflows/ci.yml
```

---

## Phase Dependencies

```
Phase 1 (Scaffold & Data)
  └─► Phase 2 (Frontend Foundation)
        ├─► Phase 3 (Drag & Undo)
        │     └─► Phase 4 (AI Command Bar)
        │           └─► Phase 5 (Templates & Drafts)
        └─► Phase 6 (Analytics)
Phase 7 (Persistent Undo & Deploy) — after Phase 3 + Phase 6
```

Phases 3→4→5 are sequential (each builds on the previous). Phase 6 can run in parallel with Phases 4–5. Phase 7 ties everything together.
