# Phase 3: Detection Testing Suite

Automated testing framework to measure how well the stealth browser evades detection.

## Files

- `detection_runner.py` — Main test runner against real protected sites (Cloudflare, LinkedIn, Amazon, Upwork). (Bug fix applied: uses correct `.page.content()`)
- `test_e2e_anti_block_recovery.py` — **Real E2E test for full anti-block recovery (#256)**. Opt-in, CI-friendly, exercises `safe_goto` + `AntiBlockOrchestrator` (detect_block on live content, recover with backoff/rotation, retries) against nowsecure.nl + deterministic simulations.
- `fingerprint_scorecard.py` — Basic fingerprinting checks (Canvas, WebGL, AudioContext, Webdriver)
- `test_phase7_fixes.py`, `test_recovery_phase1.py`, `test_basic.py`, `test_mcp_contract.py` — Unit / smoke / regression tests

## Usage

```bash
# Run full detection suite
python tests/detection_runner.py

# Run the key E2E recovery test (skipped by default)
RUN_E2E_ANTI_BLOCK=1 python tests/test_e2e_anti_block_recovery.py

# Or via pytest (with output)
RUN_E2E_ANTI_BLOCK=1 python -m pytest tests/test_e2e_anti_block_recovery.py -q -s

# Regular fast CI / pytest (excludes the heavy E2E by default)
python -m pytest tests/ -q -m "not e2e"
```

Results from detection_runner are saved to `tests/detection_results_*.json`.

## What It Measures

1. **Detection Signals** — CAPTCHA, "unusual activity", rate limits, blocks
2. **Fingerprinting Vectors** — Canvas, WebGL, AudioContext, webdriver flag
3. **Pass/Fail Rate** — How often the browser survives without triggering protection
4. **Recovery Effectiveness (#256)** — Whether the full anti-block orchestrator (backoff, session/proxy rotation hooks, content-based detection, retry) actually fires and handles real protected-site challenges gracefully.

## Current Status

- Basic test runner implemented (and fixed)
- Dedicated high-value E2E recovery test added (opt-in, solid, uses async context manager + instrumentation)
- Fingerprint scorecard implemented
- Manual testing still recommended alongside automated runs
- All core smoke tests (phase7, recovery phase1, MCP contract) pass in both direct and pytest modes

## Next Improvements

- Add historical tracking of detection rates
- Integrate with nightly CI (the E2E test can be included in a dedicated "e2e" workflow/job)
- Add more sophisticated fingerprinting checks (fonts, plugins, hardware)
- Consider lightweight mock-server for recovery unit tests (to avoid any live calls even when enabled)
