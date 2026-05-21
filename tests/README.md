# Test Suite

Comprehensive testing framework for the Agentic Stealth Browser.

## Quick Start

```bash
# Run all fast tests (CI mode)
python -m pytest tests/ -q -m "not e2e"

# Run all tests including slow E2E
RUN_E2E_ANTI_BLOCK=1 python -m pytest tests/ -v

# Run specific test category
python -m pytest tests/test_stealth_modules.py -v
python -m pytest tests/test_account_health.py -v
```

## Test Categories

### Core Unit Tests

| File | Tests | Description |
|------|-------|-------------|
| `test_stealth_modules.py` | 60+ | Stealth module functionality (webdriver spoofing, canvas noise, fingerprint consistency) |
| `test_contract_agent_browser.py` | 57 | API contract tests for AgentBrowser class |
| `test_detectors.py` | 16 | Block detector interface (TitleDetector, ContentDetector, consensus) |
| `test_human_behavior_fuzz.py` | 23 | Property-based/fuzz testing for human behavior parameters |

### Account Management

| File | Tests | Description |
|------|-------|-------------|
| `test_account_health.py` | 23 | Health scoring, risk events, cooling off, checkpoint/restore |
| `test_account_warming.py` | 25 | Warming schedule, phase progression, session limits |
| `test_persona_rotator.py` | 26 | Behavioral persona evolution, trait transitions |

### Infrastructure

| File | Tests | Description |
|------|-------|-------------|
| `test_stealth_cache.py` | 24 | Stealth script/profile caching, LRU eviction, TTL |
| `test_session_checkpoint.py` | 18 | Session checkpoint/export, browser state capture/restore |

### E2E & Integration

| File | Tests | Description |
|------|-------|-------------|
| `test_e2e_anti_block_recovery.py` | 2 | Real E2E anti-block recovery (opt-in, `RUN_E2E_ANTI_BLOCK=1`) |
| `test_e2e_protected_sites_placeholder.py` | 1 | Protected site access placeholder |
| `test_basic.py` | 1 | Basic browser launch smoke test |
| `test_mcp_contract.py` | 1 | MCP session contract test |
| `test_phase7_fixes.py` | 8 | Phase 7 regression tests (rate limiter, recovery, mouse bezier) |
| `test_recovery_phase1.py` | 1 | Recovery phase 1 test |

## Detection Testing

### Files

- `detection_runner.py` — Main test runner against real protected sites (Cloudflare, LinkedIn, Amazon, Upwork)
- `fingerprint_scorecard.py` — Fingerprinting checks (Canvas, WebGL, AudioContext, Webdriver)
- `detection_check.py` — Single-site detection check
- `run_detection_tests.py` — Batch detection test runner
- `debug_nowsecure.py` — Debug helper for nowsecure.nl

### Usage

```bash
# Run full detection suite
python tests/detection_runner.py

# Run the key E2E recovery test
RUN_E2E_ANTI_BLOCK=1 python tests/test_e2e_anti_block_recovery.py

# Run via pytest
RUN_E2E_ANTI_BLOCK=1 python -m pytest tests/test_e2e_anti_block_recovery.py -q -s
```

Results saved to `tests/detection_results_*.json`.

## What It Measures

1. **Detection Signals** — CAPTCHA, "unusual activity", rate limits, blocks
2. **Fingerprinting Vectors** — Canvas, WebGL, AudioContext, webdriver flag
3. **Pass/Fail Rate** — How often the browser survives without triggering protection
4. **Recovery Effectiveness** — Anti-block orchestrator (backoff, rotation, retry)
5. **Behavioral Realism** — Human-like mouse, typing, scroll, distraction patterns
6. **Account Health** — Risk scoring, cooling off, warming progression

## Test Count

| Category | Count |
|----------|-------|
| Core Unit Tests | 156 |
| Account Management | 74 |
| Infrastructure | 42 |
| E2E & Integration | 14 |
| **Total** | **286** |

## Writing Tests

- Use `MockPage` for browser-less testing (see `test_human_behavior_fuzz.py`)
- Use `asyncio.get_event_loop().run_until_complete()` for async tests (avoids pytest-asyncio dependency)
- Property-based tests should verify invariants, not exact values
- Fuzz tests should cover edge cases, extreme values, and invalid inputs

## CI Configuration

```bash
# Fast CI (excludes E2E)
python -m pytest tests/ -q -m "not e2e"

# Full CI
RUN_E2E_ANTI_BLOCK=1 python -m pytest tests/ -v
```

## Status

- All 246 core tests passing
- E2E tests require live browser (opt-in)
- Detection tests require network access to protected sites
