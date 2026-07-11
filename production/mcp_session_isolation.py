"""
MCP Session Isolation Enforcement — v1.4.0

Prevents cross-session data access:
- One session's tool calls cannot access another session's browser instance.
- session_name must match the caller's authorized session.
- Token-based session binding for concurrent clients.

NOT YET INTEGRATED (honesty note): SessionEnforcer is defined and unit-tested but
is NOT called from the MCP dispatch path in production/mcp_server.py. Its model
isolates *concurrent client contexts* from each other via per-context tokens, but
the current MCP transport is single-client stdio and carries no per-call context
token to key check_access() on. With one trust domain there is nothing to isolate
from, and _resolve_browser() already rejects unknown/closed sessions — so wiring a
constant global token here would be security theater, not enforcement. This class
becomes meaningful only under a multi-client transport (e.g. HTTP/SSE) that supplies
a real per-client context token to bind_session()/check_access(). Until then it
enforces nothing at runtime; do not rely on it for isolation.
"""

from __future__ import annotations

import asyncio
import secrets
import time
from typing import Any, Dict, Optional, Set


class SessionBinding:
    """A single bound MCP session — links a session_name to a caller token."""

    __slots__ = ("session_name", "token", "created_at", "last_access", "browser")

    def __init__(
        self, session_name: str, token: Optional[str] = None, browser: Any = None
    ):
        self.session_name = session_name
        self.token = token or secrets.token_hex(16)
        self.created_at = time.time()
        self.last_access = time.time()
        self.browser = browser

    def touch(self) -> None:
        self.last_access = time.time()


class SessionIsolationError(Exception):
    def __init__(self, session_name: str, reason: str):
        self.session_name = session_name
        self.reason = reason
        super().__init__(
            f"Session isolation violation: {reason} (session={session_name})"
        )


class SessionEnforcer:
    """Enforces session isolation for MCP tool calls.

    Each call context is associated with a token. Tools can only operate on
    sessions bound to their call context's token. A single client/context cannot
    access another context's browser instances.

    NOT WIRED: no call site in production/mcp_server.py's dispatch path. Requires a
    multi-client transport that supplies a per-context token — the current stdio
    transport does not. See the module docstring. This is a defined-but-inert
    security control, not an active one.
    """

    def __init__(self) -> None:
        self._bindings: Dict[str, SessionBinding] = {}
        self._contexts: Dict[str, str] = {}  # context_token -> session_name
        self._lock = asyncio.Lock()

    async def bind_session(
        self, session_name: str, context_token: str, browser: Any = None
    ) -> SessionBinding:
        async with self._lock:
            if context_token in self._contexts:
                existing = self._contexts[context_token]
                if existing != session_name:
                    self._unbind_context(context_token)
            binding = self._bindings.get(session_name)
            if binding is None:
                binding = SessionBinding(
                    session_name, token=secrets.token_hex(16), browser=browser
                )
                self._bindings[session_name] = binding
            self._contexts[context_token] = session_name
            return binding

    def _unbind_context(self, context_token: str) -> None:
        self._contexts.pop(context_token, None)

    async def check_access(
        self, session_name: str, context_token: str
    ) -> SessionBinding:
        async with self._lock:
            if context_token not in self._contexts:
                raise SessionIsolationError(
                    session_name,
                    f"context {context_token[:8]}... has no bound session",
                )

            bound_session = self._contexts[context_token]
            if bound_session != session_name:
                raise SessionIsolationError(
                    session_name,
                    f"context {context_token[:8]}... is bound to '{bound_session}', "
                    f"not '{session_name}'",
                )

            binding = self._bindings.get(session_name)
            if binding is None:
                raise SessionIsolationError(
                    session_name,
                    "session binding not found (may have been closed)",
                )

            binding.touch()
            return binding

    def unbind_session(self, session_name: str) -> None:
        binding = self._bindings.pop(session_name, None)
        if binding:
            for ctx, sess in list(self._contexts.items()):
                if sess == session_name:
                    del self._contexts[ctx]

    def get_owned_sessions(self, context_token: str) -> Set[str]:
        sessions: Set[str] = set()
        for ctx, sess in self._contexts.items():
            if ctx == context_token:
                sessions.add(sess)
        return sessions

    def unbind_context(self, context_token: str) -> None:
        self._unbind_context(context_token)
