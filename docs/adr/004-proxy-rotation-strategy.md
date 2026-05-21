# ADR-004: Proxy Rotation Strategy

**Status:** Accepted
**Date:** 2026-05-10
**Context:** Phase 4 proxy system

## Problem

Single IP addresses get rate-limited and blocked. Residential proxies are expensive and need sticky sessions for consistency.

## Decision

Use tiered proxy selection (datacenter → residential → mobile) based on site sensitivity, with sticky session IDs for session persistence. Proxy rotation triggered by:
- Consecutive failures (health-based)
- Block detection (recovery-driven)
- Manual rotation (user-initiated)

## Consequences

### Positive
- Smart tier selection balances cost vs. stealth
- Health tracking prevents using bad proxies
- Sticky sessions maintain login state

### Negative
- Proxy setup adds latency
- Session rotation loses cookies/state
- Residential proxies are expensive

## Alternatives Considered

1. **Single proxy for all sites**: Simple but gets blocked quickly
2. **Rotate on every request**: Maximum stealth but breaks sessions
3. **No proxy**: Cheapest but highest block rate

## References

- `proxy/proxy_manager.py`
- Issues: #22, #119
