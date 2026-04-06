# Day-Forge — Product Requirements Document

**AI-Powered Daily Schedule Assistant**

| Field   | Value        |
|---------|--------------|
| Version | 1.0          |
| Date    | April 2026   |
| Author  | Yerzhan      |
| Status  | Draft        |

---

## 1. Overview

Day-Forge is a personal daily schedule assistant that replaces paper-based todo planning with an intelligent, AI-augmented web application. It generates daily schedule drafts based on learned patterns and user-defined templates, and allows rapid editing through a natural language command bar and drag-and-drop interface.

The core insight: planning a day on paper is fast because it has zero friction. Day-Forge must match or beat that speed while adding the intelligence that paper cannot provide — pattern learning, automatic conflict resolution, and end-of-day analytics.

---

## 2. Goals & Non-Goals

### 2.1 Goals

- Replace paper-based daily schedule planning with a faster digital alternative
- Generate smart schedule drafts using OpenAI API, learning from historical patterns and user-defined templates
- Provide natural language command bar for rapid schedule modifications (English + Russian)
- Support drag-and-drop reordering with automatic time-shift conflict resolution
- Track task completion and provide end-of-day planned vs. actual analytics
- Run in Docker for both local development and VPS deployment

### 2.2 Non-Goals (for now)

- Mobile-responsive design (desktop-only for MVP and near-term)
- Multi-user / team / family sharing
- Calendar sync (Google Calendar, Outlook, etc.)
- Voice input
- Real-time notifications or reminders
- Native mobile app

---

## 3. User Persona

**Single user (self).** Power user, developer, plans days with ~50% predictable routine and ~50% ad-hoc tasks. Currently uses paper/whiteboard. Plans either the night before or first thing in the morning. Wants the speed of paper with the intelligence of AI. Bilingual input (English + Russian).

---

## 4. Core User Flows

### 4.1 Morning Draft Generation

1. User opens the app (or navigates to today's date).
2. System checks: does today already have a schedule? If not, auto-generate a draft.
3. AI uses: (a) weekday vs. weekend template as baseline, (b) recent day history for pattern learning, (c) any rules the user has configured.
4. Draft appears as a flat list with time badges. User reviews and adjusts.

### 4.2 Command Bar Editing

1. User types a natural language command in the bottom bar, e.g.: `"new call at 10:00 for 30 minutes"` or `"добавь звонок в 10:00 на 30 минут"`.
2. AI interprets the command and modifies the schedule (add, move, remove, resize tasks).
3. Changes apply instantly. A toast notification shows what changed with an Undo button.
4. Full command history is persisted for AI context and learning.

### 4.3 Drag-and-Drop Rearrangement

1. User drags a task to a new time position.
2. If the dropped position overlaps with existing tasks, all subsequent tasks auto-shift forward.
3. Time badges update in real-time during drag.
4. Undo is available via Ctrl+Z or the undo toast.

### 4.4 End-of-Day Review

1. User marks tasks as done/not done throughout the day via checkboxes.
2. At end of day (or when reviewing past days), a summary panel shows: completion rate, planned time vs. actual, tasks skipped.
3. This data feeds back into the AI for future draft improvement.

---

## 5. Information Architecture & UI Layout

The UI consists of a single-page layout with the following zones:

| Zone        | Content                                                                 | Behavior                                                       |
|-------------|-------------------------------------------------------------------------|----------------------------------------------------------------|
| Top Bar     | Date navigator (‹ Today ›), settings gear icon                          | Click arrows or date to navigate days                          |
| Main Area   | Flat list of time blocks with time badges, category colors, checkboxes, drag handles | Gaps shown as empty slots. Current time slot highlighted. Drag to reorder. |
| Now Line    | Horizontal line indicating current time                                 | Auto-scrolls into view, updates every minute                   |
| Command Bar | Text input at bottom, full-width, terminal-style                        | Always visible. Enter sends command to AI. Shows processing spinner. |
| Undo Toast  | Bottom-right floating notification                                      | Appears on any AI or drag modification. Auto-dismisses after 8s. |

### 5.1 Time Block Anatomy

Each time block in the flat list displays:

- **Drag handle** (left edge)
- **Time badge**: start time – end time (e.g., `09:20 – 09:45`)
- **Category color bar** (left border: blue=work, green=personal, orange=health, gray=other)
- **Task title** (editable inline on click)
- **Checkbox** (right side, for completion tracking)
- **Duration indicator** (subtle, e.g., "25 min")

### 5.2 Gap Handling

When there is no task between two time blocks (e.g., 09:45 to 13:00), the UI renders an empty slot showing the gap duration. These empty slots are clickable to quickly add a new task in that window. A subtle dashed border and muted text like "3h 15m free" indicates the gap.

---

## 6. AI Assistant Specification

### 6.1 LLM Provider

OpenAI API (`gpt-4o` or `gpt-4o-mini`, configurable). API key stored as environment variable, never exposed to frontend.

### 6.2 Context Window Strategy

Each AI request includes the following context:

- Current day's schedule (full state)
- Active template (weekday or weekend)
- Last 7 days of schedules (for pattern learning)
- User-defined rules (stored as structured text)
- The user's command (natural language, English or Russian)
- Current time (for time-aware suggestions)

### 6.3 AI Output Format

The AI returns structured JSON describing schedule modifications (not free text). The backend validates and applies the changes atomically. The response schema:

```json
{
  "actions": [
    {
      "type": "add|move|remove|resize",
      "task_id": "...",
      "title": "...",
      "start_time": "HH:MM",
      "end_time": "HH:MM",
      "category": "work|personal|health|other"
    }
  ],
  "explanation": "..."
}
```

### 6.4 Command Examples

| User Input                                      | Expected AI Action                                  |
|-------------------------------------------------|-----------------------------------------------------|
| `"add standup at 10:00 for 15 min"`             | Add: standup, 10:00–10:15, category=work            |
| `"move gym to 18:00"`                           | Move: gym block to 18:00, keep duration             |
| `"cancel the 15:00 meeting"`                    | Remove: task at 15:00                               |
| `"extend lunch by 30 minutes"`                  | Resize: lunch end_time += 30 min                    |
| `"добавь звонок в 10 на 30 минут"`              | Add: звонок, 10:00–10:30                            |
| `"I have a free afternoon, fill it with deep work blocks"` | Add: multiple 90-min deep work blocks with breaks |

### 6.5 Error Handling

- If AI cannot parse the command, show a friendly error in the command bar area: "I didn't understand that. Try something like: add meeting at 14:00 for 1 hour."
- If OpenAI API is down or rate-limited, fall back to manual editing only and show a status indicator.
- All AI commands are logged with request/response for debugging.

---

## 7. Templates & Rules System

### 7.1 Templates

Two template types: **Weekday** and **Weekend**. Each template is a list of default time blocks that the AI uses as the baseline when generating a draft. Templates are editable through a dedicated settings page (same drag-and-drop UI as the daily schedule).

### 7.2 Rules

User-defined natural language rules that the AI always respects. Stored as text, injected into every AI prompt. Examples:

- "Always schedule gym before 10:00 AM"
- "Never schedule meetings before 9:00 AM"
- "Lunch must be between 12:00 and 14:00"
- "Keep at least 15 minutes between back-to-back meetings"
- "Friday afternoons are for deep work only"

---

## 8. Data Model

SQLite database with the following core tables:

### `schedules`

| Field  | Type    | Notes                          |
|--------|---------|--------------------------------|
| id     | INTEGER | Primary key                    |
| date   | DATE    | Unique, one schedule per day   |
| status | VARCHAR | draft, active, reviewed        |

### `time_blocks`

| Field        | Type    | Notes                              |
|--------------|---------|------------------------------------|
| id           | INTEGER | Primary key                        |
| schedule_id  | FK      | References schedules               |
| title        | VARCHAR | Task name                          |
| start_time   | TIME    | 5-minute granularity               |
| end_time     | TIME    | 5-minute granularity               |
| category     | VARCHAR | work, personal, health, other      |
| is_completed | BOOLEAN | Checkbox state                     |
| sort_order   | INTEGER | For ordering within same time slot |

### `templates`

| Field  | Type    | Notes                                   |
|--------|---------|-----------------------------------------|
| id     | INTEGER | Primary key                             |
| name   | VARCHAR | Display name                            |
| type   | VARCHAR | weekday or weekend                      |
| blocks | JSON    | Array of default time blocks            |

### `rules`

| Field     | Type    | Notes                          |
|-----------|---------|--------------------------------|
| id        | INTEGER | Primary key                    |
| text      | TEXT    | Natural language rule          |
| is_active | BOOLEAN | Toggle on/off                  |
| priority  | INTEGER | Higher = more important to AI  |

### `ai_interactions`

| Field        | Type     | Notes                              |
|--------------|----------|------------------------------------|
| id           | INTEGER  | Primary key                        |
| schedule_id  | FK       | References schedules               |
| user_command | TEXT     | Raw user input                     |
| ai_response  | TEXT     | Raw AI response                    |
| actions_json | JSON     | Parsed actions applied             |
| created_at   | DATETIME | Timestamp                          |

### `daily_reviews`

| Field           | Type    | Notes                          |
|-----------------|---------|--------------------------------|
| id              | INTEGER | Primary key                    |
| schedule_id     | FK      | References schedules           |
| planned_count   | INTEGER | Total tasks planned            |
| completed_count | INTEGER | Tasks marked done              |
| skipped_count   | INTEGER | Tasks not completed            |
| notes           | TEXT    | Optional user notes            |

---

## 9. Technical Architecture

### 9.1 Stack

| Layer              | Technology                              |
|--------------------|-----------------------------------------|
| Backend Framework  | Django 5.x (Python 3.12+)              |
| Frontend Bridge    | Inertia.js (Django adapter)            |
| Frontend Framework | Vue 3 (Composition API, TypeScript)    |
| Database           | SQLite (single file, no external DB)   |
| AI Provider        | OpenAI API (gpt-4o / gpt-4o-mini)     |
| Package Manager    | uv (Python), npm (JS)                 |
| Linter / Formatter | ruff (Python), ESLint + Prettier (JS) |
| Containerization   | Docker + Docker Compose                |
| Auth               | Django built-in auth (username + password) |
| Deployment         | Docker on VPS (local dev also via Docker) |

### 9.2 Project Structure

```
day_forge/
├── backend/
│   ├── day_forge/          # Django project settings
│   ├── schedules/         # Core app (models, views, serializers)
│   ├── ai/                # AI service layer (OpenAI integration)
│   ├── templates_mgr/     # Template & rules management
│   └── analytics/         # Daily review & analytics
├── frontend/
│   ├── src/
│   │   ├── pages/         # Inertia page components
│   │   ├── components/    # Shared Vue components
│   │   ├── composables/   # Vue composables (drag, undo, etc.)
│   │   └── types/         # TypeScript interfaces
│   └── package.json
├── docker-compose.yml
├── Dockerfile
└── pyproject.toml
```

### 9.3 Key API Endpoints

| Method | Path                       | Description                                         |
|--------|----------------------------|-----------------------------------------------------|
| GET    | `/schedule/{date}/`        | Inertia page: load or auto-generate daily schedule  |
| PATCH  | `/api/blocks/{id}/`        | Update a single time block (inline edit, checkbox)  |
| POST   | `/api/blocks/reorder/`     | Batch update after drag-and-drop (positions + times)|
| POST   | `/api/ai/command/`         | Send natural language command, receive JSON actions  |
| POST   | `/api/ai/generate-draft/`  | Generate AI draft for a given date                  |
| GET    | `/api/schedule/{date}/undo/` | Retrieve last state for undo                      |
| GET/PUT| `/settings/templates/`     | Manage weekday/weekend templates                    |
| GET/PUT| `/settings/rules/`         | Manage AI rules                                     |
| GET    | `/analytics/{date}/`       | Daily review summary                                |

---

## 10. Drag-and-Drop Specification

- **Library**: Vue Draggable (or SortableJS wrapper for Vue 3).
- **Drag handle** on the left edge of each time block. Entire block is NOT draggable (to allow inline text editing).
- **During drag**: ghost element shows with real-time time badge preview based on position.
- **On drop**: if the new position causes overlap, all subsequent blocks shift forward by the overlap duration. Time badges recalculate.
- **Snap-to-grid**: 5-minute increments. Dropping between grid lines snaps to the nearest 5-minute mark.
- **Undo**: every drag operation pushes the previous state to an undo stack. Ctrl+Z or undo toast triggers restore.
- **Animate transitions**: blocks below the dropped item slide down smoothly (200ms ease).

---

## 11. Category System

| Category | Color  | Hex       | Examples                      |
|----------|--------|-----------|-------------------------------|
| Work     | Blue   | `#2B579A` | Meetings, coding, standups    |
| Personal | Green  | `#2E7D32` | Reading, errands, family      |
| Health   | Orange | `#E65100` | Gym, walk, meditation         |
| Other    | Gray   | `#616161` | Lunch, commute, misc          |

Categories are assignable per task. The AI infers the category from the task title but the user can override. Displayed as a 4px left border on each time block.

---

## 12. End-of-Day Analytics

Available when viewing past days or triggered manually for today. Displays:

- **Completion rate**: X of Y tasks completed (percentage + bar)
- **Time planned vs. time spent**: total hours planned vs. tasks marked done × their durations
- **Category breakdown**: pie chart or horizontal bars showing time distribution by category
- **Skipped tasks**: list of uncompleted tasks
- **Streak**: consecutive days with >80% completion (gamification-lite)

Analytics data is stored in the `daily_reviews` table and used by the AI as context for future draft generation.

---

## 13. Undo System

- Every modification (AI command, drag-and-drop, inline edit, checkbox) creates a snapshot of the schedule state.
- Snapshots stored in-memory on the frontend (last 20 actions) and persisted to a `schedule_snapshots` table for cross-session recovery.
- Undo triggers: Ctrl+Z keyboard shortcut, undo button in the toast notification.
- Toast notification format: "Added standup at 10:00 — Undo". Auto-dismisses after 8 seconds.
- Redo is not supported (KISS principle).

---

## 14. Development Phases

### Module 1: Foundation (Weeks 1–3)

- Django project scaffold with uv, ruff, Docker, docker-compose
- SQLite database with schedules and time_blocks models
- Inertia.js + Vue 3 setup with TypeScript
- Basic auth (Django built-in, login page)
- Daily schedule page: flat list rendering, date navigation
- Manual CRUD: add/edit/delete time blocks via UI forms
- Checkbox completion tracking

### Module 2: Drag & Command (Weeks 4–6)

- Drag-and-drop with auto-shift conflict resolution
- Command bar UI (bottom bar, terminal-style)
- OpenAI integration: command parsing, structured JSON responses
- Undo system (in-memory + toast)
- Bilingual command support (English + Russian)
- AI interaction logging

### Module 3: Intelligence (Weeks 7–10)

- Template system (weekday / weekend, settings page)
- Rules management (natural language rules, settings page)
- AI draft generation (morning auto-draft from templates + history)
- Pattern learning from past 7 days of schedule data
- Gap visualization (empty slot rendering with click-to-add)
- Current time indicator (now line + highlight)

### Module 4: Analytics & Polish (Weeks 11–14)

- End-of-day review panel with completion stats
- Category breakdown charts
- Streak tracking
- Persistent undo (schedule_snapshots table)
- Performance optimization (lazy loading, debounced saves)
- VPS deployment with Docker Compose, HTTPS, backups

---

## 15. Technical Considerations & Trade-offs

### 15.1 Why SQLite?

Single-user app, no concurrent writes at scale. SQLite is zero-config, file-based (easy backup: copy one file), and fast enough for this use case. If multi-user is ever needed, migration to PostgreSQL via Django ORM is straightforward.

### 15.2 Why Inertia.js?

Avoids building a separate REST API + SPA. Django handles routing and auth server-side, Vue handles interactivity client-side. No CORS, no token management, no duplicate routing. The trade-off: slightly less flexibility for future mobile apps (would need a separate API layer then).

### 15.3 AI Cost Management

- Use `gpt-4o-mini` for simple commands (add, remove, move). Estimated cost: ~$0.01–$0.03 per command.
- Use `gpt-4o` for draft generation (more context, better quality). Estimated cost: ~$0.05–$0.15 per draft.
- Cache template + rules in the prompt prefix to reduce repeated tokens.
- Daily cost estimate: 5–10 commands + 1 draft = ~$0.20–$0.50/day.
- Configurable model selection in settings.

### 15.4 Offline Resilience

If the OpenAI API is unavailable, the app remains fully functional for manual editing (drag, inline edit, checkbox). Only AI features degrade. A status indicator in the command bar shows API health.

---

## 16. Success Criteria

- **Daily usage**: the app is used every day for at least 2 weeks without reverting to paper.
- **Draft quality**: AI-generated drafts require fewer than 3 manual adjustments on average.
- **Speed**: creating a full day schedule takes under 2 minutes (vs. ~3–5 minutes on paper).
- **Reliability**: zero data loss over a month of daily use.
- **Command accuracy**: AI correctly interprets >90% of natural language commands.

---

## 17. Risks & Mitigations

| Risk                              | Impact | Mitigation                                                  |
|-----------------------------------|--------|-------------------------------------------------------------|
| OpenAI API cost creep             | Medium | Configurable model, usage dashboard, daily cap setting      |
| AI hallucinating schedule changes | High   | Structured JSON output with schema validation, undo system  |
| SQLite write contention (future)  | Low    | Single user, WAL mode, migrate to PostgreSQL if needed      |
| Scope creep (mobile, multi-user)  | Medium | Strict module-by-module roadmap, non-goals documented       |
| App feels slower than paper       | High   | Optimistic UI updates, instant apply, minimal round-trips   |

---

## 18. Open Questions

- Should the AI proactively suggest schedule improvements, or only respond to commands?
- Should there be a weekly planning view in addition to daily?
- How many days of history should the AI context include? (Currently: 7 days. May need tuning.)
- Should categories be user-customizable or fixed to 4?
- Should completed tasks visually dim/strikethrough, or keep full visibility?
