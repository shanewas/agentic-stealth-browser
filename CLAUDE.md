# CLAUDE.md

Guidance for Claude Code (claude.ai/code) when working with code in this repo.

## What this is

Production-grade stealth browser automation on top of Playwright (Python, async). Goal: pass modern anti-bot systems (Cloudflare, LinkedIn, Amazon) in headless Chromium by looking human at every layer — TLS, navigator APIs, WebGL/Canvas, behavior timing, block recovery. Not real uTLS stack (TLS spoofing process/init-script level, not `curl_cffi` wire-level). No CAPTCHA solving — recovery chain *detects* and surfaces to operator dashboard; solving left to `BasePlugin`.

## Commands

Setup:
```bash
python3 -m venv .venv && source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
playwright install chromium        # CI uses --with-deps
```

Test (mirror CI to reproduce failures):
```bash
# Full CI-equivalent run: skips e2e/live, ignores 3 known-excluded files, enforces 45% coverage
python -m pytest tests/ -m "not e2e and not live_network" \
  --ignore=tests/test_recovery_phase1.py --ignore=tests/test_basic.py --ignore=tests/test_phase7_fixes.py \
  -q --cov=core --cov=stealth --cov=behavior --cov=recovery --cov=proxy --cov=production --cov-fail-under=45

pytest tests/test_stealth_modules.py -v          # single file
pytest tests/test_contract_agent_browser.py::TestName::test_case   # single test
pytest -m contract        # pure-logic, no browser
pytest -m mcp             # MCP server/tools/contract
RUN_E2E_ANTI_BLOCK=1 pytest -m e2e   # live protected-site E2E (opt-in, flaky, off by default)
```

Lint / types (both block in CI):
```bash
ruff check .
ruff format --check .     # drop --check to auto-fix; double quotes, 4-space indent
mypy core/ --ignore-missing-imports --exclude 'tests'   # non-blocking in CI, informative only
```

Import smoke test (CI `build` job runs this — catches packaging breakage):
```bash
python -c "from core.agent_browser import AgentBrowser; from stealth.advanced_stealth import get_stealth_script; from sessions.cookie_manager import CookieManager; print('OK')"
```

Run:
```bash
agentic-stealth-browser dashboard         # operator dashboard (production.cli:main)
stealth-browser health --preset linkedin_2026 --region us
python -m production.mcp_server            # MCP server for AI agent clients
```

## Architecture

Layered stealth pipeline. `core.agent_browser.AgentBrowser` spine — async context manager wrapping Playwright browser. Composes other packages, doesn't own their logic:

- **`stealth/`** — fingerprint layer. `advanced_stealth.get_stealth_script()` generates init-scripts injected before first paint (patches `navigator.webdriver`, plugins, WebGL/Canvas buffers). `tls_fingerprint.py` sets region client-hello profiles; `presets.py` holds per-platform presets (e.g. `linkedin_2026`); `profiles.py` Persona/DeviceProfile system.
- **`behavior/`** — human simulation. Bézier mouse curves, variable typing, fatigue/distraction. Respects `self.realism_level` so CI/light mode stays fast.
- **`recovery/`** — `anti_block_orchestrator.py` drives block-detection → proxy/session rotation → retry. Per-platform tactics live in `PLATFORM_STRATEGIES`.
- **`sessions/`**, **`proxy/`** — session/cookie persistence and proxy rotation, consumed by recovery.
- **`production/`** — operator surface. `mcp_server.py` (MCP tools: `stealth_launch`→`stealth_navigate`→`stealth_scrape`→`stealth_close`), `sdk/` (`StealthClient` async API without MCP), `workflow_orchestrator.py` (queue/schedule/domain-concurrency), `hermes_dashboard.py`, security stack (`mcp_input_validator.py`, `mcp_session_isolation.py`, `policy_engine.py`, `approval_gate.py`). `cli.py` = `agentic-stealth-browser` entry point.
- **`production/adapters/`** — `BackendAdapter` protocol (v2.5.0): pluggable execution backends (CDP-bridge, playwright-mcp, agentic-stealth-mcp). Dashboard drives all three through same adapter shim (`dashboard_adapter_bridge.py`).
- **`mcp_security.py`** (repo root, standalone `py-module`) — MCP hardening.
- **`plugins/`** — `BasePlugin` lifecycle hooks; extension point for custom behavior and CAPTCHA-solver integrations.

Two run modes: **launch** (spawn fresh Chromium, full stealth incl. TLS) vs **attach** (`attach_over_cdp()` connects to existing Chrome on `--remote-debugging-port=9222`). Attach degrades stealth: init-script patches still apply, TLS/JA3 doesn't; adopted tabs preserved on `close()`. See `docs/ATTACH_OVER_CDP.md`.

## Conventions

- Line length 120 (ruff `E501` ignored). Type hints on public APIs; docstrings on public methods.
- `PascalCase` classes, `snake_case` funcs, `UPPER_SNAKE_CASE` constants, `_leading_underscore` private.
- PR titles use Conventional Commits (`feat:`/`fix:`/`docs:`/`test:`/`refactor:`/`perf:`/`security:`). Branch off `master`.
- New stealth patch → `stealth/advanced_stealth.py` + test in `tests/test_stealth_modules.py`. New platform preset → `stealth/presets.py`. New recovery tactic → `PLATFORM_STRATEGIES` in `recovery/anti_block_orchestrator.py`.
- `mypy strict` on globally but `ignore_errors` set for most runtime packages (`core.*`, `stealth.*`, etc.) — new code should still type-check clean where enforced.

## Testing notes

- pytest `asyncio_mode = auto` — no `@pytest.mark.asyncio` needed on async tests.
- Markers: `e2e`, `live_network`, `slow`, `contract`, `mcp`. Default local `pytest` runs everything under `tests/`; CI narrows to `not e2e and not live_network`.
- `test_recovery_phase1.py` and `test_phase7_fixes.py` now run in CI (`-m "not e2e"` excludes their browser-launching tests). Only `test_basic.py` stays excluded from the CI test job, as a manual browser smoke — don't rely on it gating.
- Detection canary runs every 4h (`docs/canary.md`, `canary/`); "zero-flag" = snapshot, not guarantee.