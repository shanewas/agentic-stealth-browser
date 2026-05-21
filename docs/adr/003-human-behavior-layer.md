# ADR-003: Human Behavior Orchestration Layer

**Status:** Accepted
**Date:** 2026-05-08
**Context:** Phase 5 human behavior system

## Problem

Automated browser actions are detectable through behavioral analysis:
- Mouse moves in straight lines at constant speed
- Typing has uniform rhythm with no mistakes
- Scrolling is perfectly smooth
- No idle moments or distractions
- Actions are too consistent across sessions

## Decision

Implement `HumanBehavior` class that orchestrates realistic human-like actions:
- Bézier curve mouse paths with wobble and micro-movements
- Variable typing speed with occasional mistakes and corrections
- Incremental scrolling with backticks (re-read patterns)
- Thinking pauses before/after actions
- Distraction simulation (cursor drift, tab hesitation, clock check)
- Fatigue-aware behavior that degrades over time

Configurable via `realism_level` (off/light/medium/full) and `AGENTIC_STEALTH_REALISM` environment variable.

## Consequences

### Positive
- Actions look human to behavioral analysis systems
- Fatigue adds realistic degradation over long sessions
- Realism levels allow performance tuning for CI/testing

### Negative
- Significantly slower than direct automation
- Hard to test without real browser
- Some patterns may become detectable if overused

## Alternatives Considered

1. **Pre-recorded human sessions**: Not flexible, detectable patterns
2. **ML-generated behavior**: Too complex, hard to control
3. **Simple random delays**: Insufficient for behavioral analysis

## References

- `behavior/human_behavior.py`
- Issues: #110, #131, #178, #296
