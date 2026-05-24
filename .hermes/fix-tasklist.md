# Fix All Open Issues - Task List

## Goal
Fix 6 GitHub issues in agentic-stealth-browser, then update README and release v1.0.1.

## Context
Repo at `/root/agentic-stealth-browser`. All changes are in this repo.
DO NOT commit, push, or create PRs. Just make the code changes.

## Issues to Fix

### I1 - #420: mcp_security redaction regex broken
**File:** `mcp_security.py`
**Problem:** The `SENSITIVE_PATTERNS` regex replacements capture the secret VALUE in group 1, then use `\1=[REDACTED_*]` — this outputs the actual secret followed by a label. The redaction doesn't actually redact.
**Fix:** Change each pattern so group 1 captures the KEY/PREFIX instead of the VALUE:
```python
# Before (broken):
(r'(?:api[_-]?key|apikey)\s*[:=]\s*["\']?([A-Za-z0-9_\-]{16,})["\']?', r'\1=[REDACTED_API_KEY]'),
# After (correct):
(r'((?:api[_-]?key|apikey)\s*[:=]\s*["\']?)[A-Za-z0-9_\-]{16,}["\']?', r'\1[REDACTED_API_KEY]'),
```
Fix ALL 8 patterns in the list (lines 152-168).

### I2 - #421: JS injection from unescaped f-strings
**Files:** `workflows/player.py`, `workflows/recovery.py`
**Problem:** Multiple `_evaluate()` calls use f-strings to interpolate selectors/URLs into JavaScript without proper escaping.
**Fix:** Replace all f-string interpolation patterns with `json.dumps()`:
- In `workflows/player.py`: Lines 231, 250, 274, 279, 295, 309, 321, 329, 338, 353, 362, 381, 395
- In `workflows/recovery.py`: Lines 109, 125, 185
- Pattern: `f'...{variable}...'` → `f'...{json.dumps(variable)}...'`
- Add `import json` at the top of both files if not already imported.

### I3 - #422: Wrong timeout recovery action dispatch
**File:** `workflows/recovery.py`
**Problem:** `_handle_timeout_error` lines 186-202: for `verify` and `wait_for_element` step types, the handler falls into `safe_type()` call instead of retrying the correct step logic.
**Fix:** Add explicit handling for `verify` and `wait_for_element` before the catch-all `else`:
```python
elif step_type in ("click", "fill", "type", "verify", "wait_for_element"):
    selector = params.get("selector", "")
    if step_type == "click" and hasattr(self.browser, "safe_click"):
        await ... safe_click ...
    elif step_type in ("fill", "type") and hasattr(self.browser, "safe_type"):
        value = params.get("value", "")
        await ... safe_type ...
    elif step_type in ("verify", "wait_for_element"):
        # These shouldn't try safe_type — just wait and retry
        await asyncio.sleep(timeout_s)
    else:
        await asyncio.sleep(timeout_s)
```

### I4 - #423: Hardcoded Upwork profile URL
**Files:** 
- `workflows/library/upwork/add-portfolio-item.yaml`
- `workflows/library/upwork/edit-title.yaml`
- `workflows/library/upwork/update-rate.yaml`
**Problem:** Each YAML hardcodes `https://upwork.com/freelancers/shanewas` in the navigate step.
**Fix:** Add a `profile_url` variable with a sensible default and use `{{profile_url}}` in the navigate step.

### I5 - #424: Empty apply.yaml stub
**File:** `workflows/library/upwork/apply.yaml`
**Problem:** Contains `steps: []` — empty workflow.
**Fix:** Either:
  a) Implement it with actual proposal flow steps (similar to submit-proposal.yaml but without the job-specific parts), OR
  b) Remove the file entirely
  Since submit-proposal.yaml already exists, option (b) is cleaner — just delete the file.

### I6 - #425: SSN detection pattern in recorder
**File:** `workflows/recorder.py`
**Problem:** `_detect_variable` has a heuristic SSN pattern (`^\d{3}-\d{2}-\d{4}$`) that causes false positives (matches any 3-2-4 digit pattern).
**Fix:** Remove the SSN pattern from `_VARIABLE_PATTERNS` (line 46) — it's low-precision and shouldn't be in production recording logic.

## Success Criteria
- All 6 issues addressed with the described fixes
- `python -c "from mcp_security import redact_sensitive_data; print(redact_sensitive_data('api_key = abc123def456ghi789')); print('OK')"` shows redacted output
- `python -c "from workflows.recorder import _detect_variable; print(_detect_variable('123-45-6789')); print('OK')"` returns `None` (SSN pattern removed)
- Workflow files have `{{profile_url}}` variable instead of hardcoded URL
- `apply.yaml` is deleted
- `python -m py_compile mcp_security.py workflows/player.py workflows/recovery.py workflows/recorder.py` passes
