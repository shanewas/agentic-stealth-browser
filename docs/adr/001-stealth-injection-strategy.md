# ADR-001: Stealth Injection Strategy

**Status:** Accepted
**Date:** 2026-05-01
**Context:** Phase 1-2 initial architecture

## Problem

Modern anti-bot systems (Cloudflare, Datadome, PerimeterX) detect automated browsers through multiple vectors:
- `navigator.webdriver` flag
- Missing plugins/mimeTypes
- Canvas/WebGL fingerprint differences
- AudioContext fingerprint
- Chrome runtime absence
- Permission query behavior
- iframe contentWindow access

## Decision

Inject a comprehensive stealth JavaScript script via `browser.add_init_script()` at the context level, ensuring it runs for:
- The initial page
- All subsequently created pages
- Every navigation and reload
- All subframes

The script is generated dynamically per session with:
- Unique fingerprint seed for canvas/WebGL/audio noise
- Persona-correlated hardware fingerprint
- Screen profile matching viewport settings

## Consequences

### Positive
- Stealth applied automatically to all pages without per-page injection
- Per-session variation prevents fingerprint correlation across sessions
- Hardware/screen correlation prevents detection inconsistencies

### Negative
- Script is large (~15KB), adding to initial page load
- Must be regenerated when persona/hardware changes
- Some sites detect the stealth script itself (arms race)

## Alternatives Considered

1. **Per-page injection**: More flexible but misses subframes and newly created pages
2. **Browser extension**: More robust but requires extension loading, detectable
3. **CDP protocol interception**: Lower level but more complex and fragile

## References

- `stealth/advanced_stealth.py:get_stealth_script()`
- `core/agent_browser.py` launch method
- Issues: #25, #27, #94, #150, #210, #262, #95
