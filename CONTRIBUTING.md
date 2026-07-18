# CONTRIBUTING.md (#55)

Thank you for your interest in contributing to the Agentic Stealth Browser! This guide will help you get started.

---

## Development Setup

### 1. Clone the Repository

```bash
git clone https://github.com/shanewas/agentic-stealth-browser.git
cd agentic-stealth-browser
```

### 2. Create a Virtual Environment

```bash
python3 -m venv .venv
source .venv/bin/activate
```

### 3. Install Dependencies

```bash
pip install -e ".[dev]"
playwright install chromium
```

### 4. Run Tests

```bash
# Run all tests
pytest tests/ -v

# Run specific test files
pytest tests/test_stealth_modules.py -v
pytest tests/test_contract_agent_browser.py -v

# Run with coverage (CI-equivalent; coverage gate ratchets +5 each release)
python -m pytest tests/ -m "not e2e and not live_network" --ignore=tests/test_basic.py -q --cov=core --cov=stealth --cov=behavior --cov=recovery --cov=proxy --cov=production --cov=sessions --cov=workflows --cov=audit --cov=mcp_security --cov-fail-under=55
```

---

## Code Style

### Formatting

We use standard Python conventions:
- 4-space indentation
- Maximum line length: 120 characters
- Type hints for all public APIs
- Docstrings for all public methods

### Naming Conventions

- Classes: `PascalCase` (e.g., `AgentBrowser`, `StealthConfig`)
- Functions/Methods: `snake_case` (e.g., `safe_goto`, `warm_up_before_work`)
- Constants: `UPPER_SNAKE_CASE` (e.g., `DEFAULT_PERSONA`, `MAX_RETRIES`)
- Private methods: Leading underscore (e.g., `_run_step`, `_check_circuit_breaker`)

---

## Making Changes

### 1. Create a Branch

```bash
git checkout -b feat/your-feature-name
# or
git checkout -b fix/issue-description
```

### 2. Make Your Changes

- Follow the existing code style
- Add tests for new functionality
- Update documentation if needed

### 3. Run Tests

```bash
# Ensure all tests pass
pytest tests/ -v

# Check for any import issues
python -c "from core.agent_browser import AgentBrowser"
python -c "from stealth.advanced_stealth import get_stealth_script"
```

### 4. Commit Your Changes

```bash
git add .
git commit -m "feat: description of your change

More detailed description if needed.

Closes #123"
```

### 5. Push and Create a Pull Request

```bash
git push origin your-branch-name
```

Then open a PR on GitHub.

---

## Pull Request Guidelines

### Title Format

- `feat: ` for new features
- `fix: ` for bug fixes
- `docs: ` for documentation changes
- `test: ` for test additions/changes
- `refactor: ` for code refactoring
- `perf: ` for performance improvements
- `security: ` for security fixes

### Description

Include:
- What this PR does
- Why this change is needed
- Any related issues (e.g., "Closes #123")
- Testing instructions

### Requirements

- [ ] All tests pass
- [ ] New code has tests
- [ ] Documentation is updated (if applicable)
- [ ] No sensitive data in code or commits

---

## Architecture Overview

```
agentic-stealth-browser/
├── core/
│   ├── agent_browser.py      # Main AgentBrowser class
│   ├── error_messages.py     # User-friendly error messages
│   └── types.py              # Type hints and stubs
├── stealth/
│   ├── advanced_stealth.py   # Stealth script generation
│   ├── tls_fingerprint.py    # TLS profile management
│   ├── headers.py            # HTTP header spoofing
│   ├── profiles.py           # Persona/DeviceProfile system
│   └── presets.py            # Platform presets
├── behavior/
│   ├── human_behavior.py     # Human-like behavior simulation
│   └── orchestration.py      # Behavior orchestration
├── recovery/
│   ├── anti_block_orchestrator.py  # Block detection & recovery
│   └── explain_blocked.py          # Block explanation
├── proxy/
│   └── proxy_manager.py      # Proxy management & rotation
├── sessions/
│   ├── session_manager.py    # Session management
│   └── cookie_manager.py     # Cookie management
├── production/
│   ├── metrics.py            # Metrics collection
│   ├── rate_limiter.py       # Rate limiting
│   ├── cli.py                # CLI entry point
│   └── agent_orchestrator.py # Multi-agent orchestration
├── audit/
│   └── logger.py             # Audit logging
├── scraping/
│   └── scraper.py            # Stealth scraping
├── ai/
│   └── ai_hooks.py           # AI integration hooks
├── tests/                    # Test suite
# (documentation lives in README.md and git history)
└── mcp_security.py           # MCP security hardening
```

---

## Adding New Features

### New Stealth Patches

1. Add the patch to `stealth/advanced_stealth.py`
2. Add tests to `tests/test_stealth_modules.py`
3. Update relevant sections in README.md if behavior changes

### New Platform Preset

1. Add the preset to `stealth/presets.py`
2. Add a recipe to `README.md`
3. Test against the target site

### New Recovery Strategy

1. Update `PLATFORM_STRATEGIES` in `recovery/anti_block_orchestrator.py`
2. Add tests to `tests/test_recovery_state_machine.py`
3. Document rate limiting behavior changes in README.md or relevant code comments

### New Human Behavior

1. Add the behavior to `behavior/human_behavior.py`
2. Respect `self.realism_level` for CI/light mode
3. Add tests

---

## Reporting Issues

When reporting a bug, include:
- Python version
- Playwright version
- Error message and stack trace
- Code snippet that reproduces the issue
- Debug report (`await browser.debug_report(print_report=True)`)
- Health status (`await browser.get_health_status()`)

---

## Security

If you discover a security vulnerability:
1. **Do not** open a public issue
2. Email the maintainer directly
3. Include steps to reproduce and potential impact

---

## License

By contributing, you agree that your contributions will be licensed under the MIT License.

All contributions must be signed off under the [Developer Certificate of Origin](DCO.txt). Add a `Signed-off-by: Your Name <you@example.com>` line to each commit (use `git commit -s`).

## Deprecation Policy

The public API surface is: the SDK (`production.sdk.client.StealthClient`), MCP tool names (`stealth_launch`, `stealth_navigate`, `stealth_scrape`, `stealth_close`), the `agentic-stealth-browser` CLI and its flags, and the `plugins.BasePlugin` protocol.

A deprecated public symbol, flag, or tool emits a `DeprecationWarning` (or documented equivalent) for at least one full MINOR release before removal. Every deprecation and removal is listed in the CHANGELOG under `Deprecated` / `Removed`.
