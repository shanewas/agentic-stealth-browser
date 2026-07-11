# Stealth harness (P0 — the ruler)

The measurement gate every stealth-hardening phase is graded by. Build the ruler
before touching TLS/CDP so each later change is provably better and can't silently
regress. See the full plan: *GhostScrape TLS-CDP Engine Plan*.

## What it grades

`collect.py` drives the real `AgentBrowser` through the surfaces hard anti-bot
systems gate on and returns a flat dict:

| Signal | Source | Phase that fixes it |
|---|---|---|
| JA3 / JA4 / HTTP2 (Akamai) / PQ keyshare | `tls.peet.ws/api/all` (navigated by the page) | P1 real Chrome, P2 curl_cffi |
| `navigator.webdriver` (must be **undefined**, not false) | in-page JS | P1 Patchright |
| WebGL renderer (SwiftShader/llvmpipe = GPU-less tell) | in-page JS | P1 real Chrome + headful/Xvfb |
| plugins length, hardwareConcurrency, deviceMemory | in-page JS | P1 |
| UA major == `userAgentData` major == reference | in-page JS | P1 coherence |
| `isTrusted` on mousemove + wheel | synthesized input | P3 trusted input |

`test_stealth.py` is the pytest merge-gate: it grades `collect()` output against a
**real-Chrome reference** and hard pass criteria. It **skips** (never fails) when no
browser/env is present, so it's safe in CI everywhere; it only grades when you opt in.

## How to run (needs a real browser env with disk)

> The dev Windows box is disk-starved; run this on a GPU-less Linux env that
> matches prod headless reality (or a clean throwaway VM). It makes outbound calls
> to third-party detectors, hence the explicit opt-in flag.

```bash
# 1. Install the engine + a browser in that env (see repo README / Dockerfile).
# 2. Capture the engine's current signals:
STEALTH_HARNESS_LIVE=1 python -m tests.stealth_harness.collect > tests/stealth_harness/baseline.json

# 3. Capture a REAL-CHROME reference (hand-driven Chrome of the same major),
#    save as reference-chrome-<major>.json. Every "match" criterion means
#    "match this file", never a hardcoded constant. Regenerate it whenever Chrome
#    bumps a major — that's the ~0.5-1 day/month maintenance the plan budgets.

# 4. Grade (red/green):
STEALTH_HARNESS_LIVE=1 pytest tests/stealth_harness/test_stealth.py -v
```

## Roadmap for this harness

- **P0.1 (determinism):** vendor CreepJS + rebrowser-bot-detector as static assets
  served from `localhost` (no rate-limit, reproducible), add their score rows.
- Add the **P5 gauntlet** (N=100 rotating: CF-managed, DataDome, Amazon PDP, Google
  SERP) once proxies + real Chrome land, with rolling success-rate criteria.

Nothing here ships to production — test-only, assets vendored.
