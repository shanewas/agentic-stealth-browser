# ADR-007: MCP Security Model

**Status:** Accepted
**Date:** 2026-05-18
**Context:** Phase 6 security hardening

## Problem

MCP servers can access agent's environment and filesystem, and sampling allows external servers to drive LLM calls without controls.

## Decision

Implement centralized `mcp_security.py` module with:
- File access policy (whitelist-based)
- LLM authentication for sampling
- Stderr redaction for sensitive data
- Tool description sanitization

## Consequences

### Positive
- Prevents unauthorized file access
- Redacts sensitive data from logs
- Controls LLM call authorization

### Negative
- Adds complexity to MCP setup
- May break legitimate tool usage if policy too restrictive

## Alternatives Considered

1. **No security controls**: Simplest but dangerous
2. **Per-server security**: More flexible but duplicated effort
3. **External security proxy**: More robust but adds latency

## References

- `mcp_security.py`
- Issues: #77, #68, #54, #49
