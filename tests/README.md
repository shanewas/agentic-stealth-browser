# Phase 3: Detection Testing Suite

Automated testing framework to measure how well the stealth browser evades detection.

## Files

- `detection_runner.py` — Main test runner against real protected sites (Cloudflare, LinkedIn, Amazon, Upwork)
- `fingerprint_scorecard.py` — Basic fingerprinting checks (Canvas, WebGL, AudioContext, Webdriver)

## Usage

```bash
# Run full detection suite
python tests/detection_runner.py

# Results are saved to tests/detection_results_*.json
```

## What It Measures

1. **Detection Signals** — CAPTCHA, "unusual activity", rate limits, blocks
2. **Fingerprinting Vectors** — Canvas, WebGL, AudioContext, webdriver flag
3. **Pass/Fail Rate** — How often the browser survives without triggering protection

## Current Status

- Basic test runner implemented
- Fingerprint scorecard implemented
- Manual testing still recommended alongside automated runs

## Next Improvements

- Add historical tracking of detection rates
- Integrate with nightly CI
- Add more sophisticated fingerprinting checks (fonts, plugins, hardware)
