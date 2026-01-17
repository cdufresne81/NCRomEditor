# Claude Code Instructions

## General Rules

- **"Question:" prefix** - If a prompt starts with "Question:", answer only. Take no actions (no file edits, no commands).
- **Incremental notes** - After completing code changes that add, update, or delete functionality, immediately update the "Recent Completed Work" section in `.claude/notes.md`. Only note meaningful changes (new features, behavior changes, significant fixes). Skip trivial changes (typos, formatting, minor refactors). Always check existing entries to avoid duplicates.

## Session Notes

Check `.claude/notes.md` at the start of each session for:
- Pending tasks from previous sessions
- Important context and decisions

Update this file when ending a session with any important notes for next time.

## Key Documentation

Reference these before modifying related functionality:
- `docs/LOGGING.md` - Logging configuration and exception hierarchy
- `docs/ROM_DEFINITION_FORMAT.md` - XML format for ROM definitions

**Rule:** When creating new documentation in `docs/`, add it to this list with a brief description of when to reference it.

## Landing the Plane (Session Completion)

When ending a work session, complete ALL steps below. Work is NOT complete until `git push` succeeds.

**Checklist:**

1. **Run quality gates** (if code changed):
   ```bash
   pytest
   ```

2. **Commit and push**:
   ```bash
   git add -A
   git commit -m "Description of changes"
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```

3. **Verify** - All changes committed AND pushed

4. **Update notes** in `.claude/notes.md`:
   - Add any pending tasks or context
   - Apply **Incremental notes** rule for any missed completed work
   - Verify "Recent Completed Work" is complete (incremental notes should have captured most changes - only add missing items, no duplicates)
   - Sanity check `README.md` against recent work - add new features, remove references to deleted functionality

5. **Hand off** - Provide context summary for next session

**Rules:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- If push fails, resolve and retry until it succeeds
