# RULES.md

Project-specific patterns, pitfalls, and conventions discovered during development.
This is a living document — update it as new patterns emerge.

## Secrets & Environment Files

- Never commit `.env` files. `.gitignore` excludes `.env` and `.env.*`, with `!.env.example` carved out so a sanitized template can be committed.
- Secrets belong in env vars, not code or fixtures. See `backend/day_forge/settings.py` and the env var list in `CLAUDE.md` (`LLM_API_KEY`, `DJANGO_SECRET_KEY`, etc.).
- Before committing, sanity-check with `git ls-files | grep -E '(^|/)\.env'` — should return nothing except `.env.example` if one exists.
- User commands sent to `POST /api/ai/schedules/<date>/command/` are logged verbatim to `AIInteraction` (capped at 2 KB). Treat this table as sensitive; don't paste real secrets into the command bar while testing.
