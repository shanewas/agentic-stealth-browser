# ADR-008: Persona & DeviceProfile System

**Status:** Accepted
**Date:** 2026-05-20
**Context:** Phase 8 persona system

## Problem

TLS profile, user-agent, viewport, hardware, and behavior parameters were independent and hardcoded, making realistic multi-account operation difficult.

## Decision

Create `DeviceProfile` and `Persona` classes that bundle all fingerprint + behavior parameters. Support runtime switching via `PersonaRotator` for gradual evolution over time.

## Consequences

### Positive
- Consistent persona across all fingerprint vectors
- Runtime switching without browser relaunch
- Gradual evolution prevents sudden behavior changes

### Negative
- Adds complexity to browser launch
- Persona switching requires careful state management

## Alternatives Considered

1. **Hardcoded profiles**: Simple but inflexible
2. **Per-parameter configuration**: Flexible but inconsistent
3. **External persona service**: More scalable but adds dependency

## References

- `stealth/profiles.py`
- `behavior/persona_rotator.py`
- Issues: #46, #56, #51, #129
