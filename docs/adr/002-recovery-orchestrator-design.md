# ADR-002: Recovery Orchestrator Design

**Status:** Accepted
**Date:** 2026-05-05
**Context:** Phase 3-4 recovery system

## Problem

Automated browsers get blocked by anti-bot systems. Simple retry logic is insufficient because:
- Different platforms require different recovery strategies
- Blocks have different severity levels (soft, captcha, hard, account restriction)
- Recovery actions must be sequenced (backoff → rotate → retry)
- State must be preserved across recovery attempts

## Decision

Implement `AntiBlockOrchestrator` with:
- Platform-specific recovery strategies (LinkedIn, Cloudflare, Amazon, Upwork)
- Block type detection via content analysis + HTTP status + response time
- Sequenced recovery actions with configurable backoff
- Proxy and session rotation hooks
- Maximum retry limits with exponential backoff

The orchestrator wraps navigation functions via `execute_with_recovery(func, platform, url)`.

## Consequences

### Positive
- Centralized recovery logic prevents scattered retry code
- Platform-specific strategies improve success rates
- Backoff prevents rate limit escalation
- Rotation hooks enable proxy/session changes during recovery

### Negative
- Adds latency to navigation (detection + recovery overhead)
- Complex state management across recovery attempts
- Platform strategies require maintenance as sites change

## Alternatives Considered

1. **Simple retry with fixed delay**: Too naive, escalates rate limits
2. **Global exception handler**: Loses context about platform and block type
3. **Per-site recovery code**: Duplicated logic, hard to maintain

## References

- `recovery/anti_block_orchestrator.py`
- `recovery/detectors.py`
- Issues: #256, #273, #17
