# ADR-006: Session Management & Persistence

**Status:** Accepted
**Date:** 2026-05-15
**Context:** Phase 4 session resilience

## Problem

Browser sessions are lost on restart, requiring re-login and re-warming.

## Decision

Use Playwright's persistent contexts with user data directories for automatic cookie/localStorage persistence. Add `SessionCheckpoint` for explicit state capture/restore across hosts.

## Consequences

### Positive
- Automatic session persistence across restarts
- Explicit checkpoint/restore for cross-host migration
- Cookie health tracking and rotation

### Negative
- User data directories consume disk space
- Checkpoint files may contain sensitive data

## Alternatives Considered

1. **Manual cookie export**: Flexible but error-prone
2. **No persistence**: Simplest but requires re-login every time
3. **Database-backed sessions**: More robust but adds complexity

## References

- `core/session_checkpoint.py`
- `sessions/cookie_manager.py`
- Issues: #62, #82
