# ADR-005: Rate Limiting Architecture

**Status:** Accepted
**Date:** 2026-05-12
**Context:** Phase 4 production hardening

## Problem

Uncontrolled request rates trigger anti-bot systems and IP bans.

## Decision

Implement per-domain and per-account rate limiters with sliding windows, cooldown periods, and configurable limits. Rate limiting is now the default in `safe_goto()`.

## Consequences

### Positive
- Prevents rate limit escalation
- Per-account isolation for multi-account operations
- Configurable per domain

### Negative
- Adds latency to navigation
- Requires tuning per target site

## Alternatives Considered

1. **Global rate limit**: Simple but doesn't account for per-domain differences
2. **No rate limiting**: Fastest but triggers blocks quickly
3. **Fixed delays**: Predictable but detectable

## References

- `production/rate_limiter.py`
- Issues: #20, #79, #87, #136
