---
allowed-tools: Bash, Read, Write, Edit, Glob, Grep
argument-hint: <table_name> [script_path] [issue_description]
description: Visual debugging workflow with before/after screenshots
---

# Visual Debugging Workflow

You are entering a **visual debugging session**. This workflow ensures systematic before/after comparison using the test runner.

## Arguments Provided

- **Table name**: $1
- **Script path** (optional): $2
- **Issue description** (optional): $3

## Current Context

- Available test scripts: !`ls -1 tests/gui/*.txt 2>/dev/null || echo "No scripts found"`
- Existing screenshots: !`ls -1 docs/screenshots/*.png 2>/dev/null | tail -5 || echo "No screenshots yet"`

## Your Workflow

### Step 1: Clarify Intent (if needed)

If arguments are missing or ambiguous, ask:
- What table to inspect?
- What behavior to debug?
- Use AskUserQuestion if the issue description ($3) is empty and you cannot infer intent.

If intent is clear, **assume debugging mode** and proceed.

### Step 2: Create or Select Test Script

If no script provided ($2 is empty):
1. Create a temporary script at `tests/gui/debug_session.txt`
2. Include: load ROM, open table "$1", open graph, wait for render

If script provided, use it directly.

### Step 3: Capture BEFORE State

**MANDATORY** before any code changes:

```bash
python tools/test_runner.py --script <script_path> --quiet
```

Then take screenshots with **meaningful names**:
- Pattern: `{issue_short_name}_before.png`
- Example: `graph_overlap_before.png`

Use this naming in the script or via CLI:
```bash
python tools/test_runner.py --rom examples/lf9veb.bin --table "$1" --screenshot {issue}_before
```

After capturing, **read the screenshot** and describe what you observe:
```
Read file: docs/screenshots/{issue}_before.png
```

Report the screenshot path clearly:
```
📸 BEFORE screenshot: docs/screenshots/{issue}_before.png
```

### Step 4: Diagnose

Analyze the screenshot. Describe:
- What appears wrong
- What you expect to see instead
- Hypothesis for the root cause

### Step 5: Implement Fix

Make code changes to address the issue.

### Step 6: Capture AFTER State

**MANDATORY** after code changes:

Re-run the **exact same script** to ensure identical conditions:
```bash
python tools/test_runner.py --script <script_path> --quiet
```

Take AFTER screenshot:
- Pattern: `{issue_short_name}_after.png`
- Example: `graph_overlap_after.png`

Read and analyze:
```
Read file: docs/screenshots/{issue}_after.png
```

Report:
```
📸 AFTER screenshot: docs/screenshots/{issue}_after.png
```

### Step 7: Compare and Verify

Explicitly compare before/after:
- What changed?
- Is the issue resolved?
- Any new issues introduced?

### Step 8: Iterate or Complete

If issue persists:
- Return to Step 4
- Keep the same naming convention (before stays, update after)

If resolved:
- Confirm success
- Optionally clean up debug screenshots:
  ```bash
  python tools/test_runner.py --cleanup-pattern "debug_*"
  ```

## Screenshot Naming Convention

| Scenario | Before | After |
|----------|--------|-------|
| Graph overlap bug | `graph_overlap_before.png` | `graph_overlap_after.png` |
| Table rendering | `table_render_before.png` | `table_render_after.png` |
| Generic debug | `debug_before.png` | `debug_after.png` |

Use the issue description ($3) to derive the name. If not provided, ask or use `debug`.

## Output Format

Always provide clickable paths in your responses:
```
📸 BEFORE: docs/screenshots/{name}_before.png
📸 AFTER: docs/screenshots/{name}_after.png
```

## Rules

1. **NEVER skip the BEFORE screenshot** — it's your baseline
2. **ALWAYS re-run the same script** for AFTER — ensures identical conditions
3. **ALWAYS read screenshots after capturing** — you must see what you captured
4. **Use descriptive names** — not `test1.png`, use `graph_focus_before.png`
5. **Report paths clearly** — user needs to find the files easily
