# Claude Code Instructions

## Session Start

1. **Refresh codebase snapshot** (if using repomix):
   ```bash
   repomix mix
   ```

## Landing the Plane (Session Completion)

When ending a work session, complete ALL steps below. Work is NOT complete until `git push` succeeds.

**Checklist:**

1. **Run quality gates** (if code changed):
   ```bash
   pytest
   ```

2. **Refresh Repomix** (if using):
   ```bash
   repomix mix
   git add repomix-output.xml
   ```

3. **Commit and push**:
   ```bash
   git add -A
   git commit -m "Description of changes"
   git pull --rebase
   git push
   git status  # MUST show "up to date with origin"
   ```

4. **Verify** - All changes committed AND pushed

5. **Hand off** - Provide context summary for next session

**Rules:**
- Work is NOT complete until `git push` succeeds
- NEVER stop before pushing - that leaves work stranded locally
- If push fails, resolve and retry until it succeeds
